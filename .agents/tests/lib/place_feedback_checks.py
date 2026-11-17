"""Real encrypted summaries and fixed transport failures, with no provider calls."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import urllib.error

from checks import ROOT
import approval_gate_checks as fixtures

RECIPE=ROOT/'.agents/skills/recipes/coolify-hetzner'
sys.path.insert(0,str(RECIPE/'scripts'))
import setup as flow
import check
import lane
import retire
import api


def invoke(module,*args):
    out=io.StringIO()
    with patch.object(sys,'argv',[module.__name__,*map(str,args)]),redirect_stdout(out),redirect_stderr(out):
        result=module.main()
    text=out.getvalue()
    assert 'synthetic-private-marker' not in text
    return result,text


def summary(work):
    root=work/'root';root.mkdir()
    shutil.copyfile(ROOT/'tofu/encryption.tf',root/'encryption.tf')
    (root/'main.tf').write_text('resource "terraform_data" "fixture" { input = "fixture" }')
    fixtures.tofu(root,'init','-input=false')
    gate=fixtures.load();plan=root/'saved.plan'
    with fixtures.directory(root),patch.dict(os.environ,fixtures.ENV):gate.plan(plan)
    # S3 metadata and workspace replies stand in only for local identity reads.
    # The saved plan is real and decrypted by the actual pinned OpenTofu.
    backend=json.loads((RECIPE/'tofu/backend.example.json').read_text())
    metadata=root/'.terraform/terraform.tfstate'
    metadata.parent.mkdir(exist_ok=True)
    metadata.write_text(json.dumps(dict(backend=dict(type='s3',config=backend))))
    actual=gate.tofu
    def tofu(*args):
        if args==('workspace','show'):return subprocess.CompletedProcess(args,0,b'default',b'')
        return actual(*args)
    secrets=work/'absent.env'
    progress=work/'progress.json'
    progress.write_text(json.dumps(dict(root=str(root),config=dict(place=dict(name='fixture'),secrets=str(secrets)),done=[],uncertain=None)))
    storage=['fixture-access','synthetic-storage-private']
    def configure(*args):
        gate.SECRET_VALUES=dict(STATE_PASSPHRASE=fixtures.PASSPHRASE,STORAGE_ACCESS_KEY=storage[0],STORAGE_SECRET_KEY=storage[1])
        gate.S3_CREDENTIALS=None
    with patch.object(flow,'approval_gate',return_value=gate),patch.object(gate,'configure_secrets',side_effect=configure,create=True),patch.object(gate,'storage_credentials',side_effect=lambda:tuple(storage)),patch.object(flow,'prompt',return_value=fixtures.PASSPHRASE),patch.object(gate,'tofu',side_effect=tofu):
        configure()
        with fixtures.directory(root),patch.dict(os.environ,fixtures.ENV):
            identity=dict(schema_version='1.0',plan_sha256=gate.digest(plan.read_bytes()),target=gate.target_identity())
        gate.identity_path(plan).write_text(json.dumps(identity))
        # Identity is checked before decrypting, with the freshly supplied key.
        storage[1]='synthetic-private-marker'
        status,text=invoke(flow,'summary','--progress',progress,'--plan',plan)
        assert status!=0 and 'The plan-time identity record is missing, malformed or does not match this plan or target.' in text,text
        storage[1]='synthetic-storage-private'
        # Local metadata avoids any S3 call from OpenTofu show in this case.
        metadata.unlink()
        configure()
        with fixtures.directory(root),patch.dict(os.environ,fixtures.ENV):identity['target']=gate.target_identity()
        gate.identity_path(plan).write_text(json.dumps(identity))
        with patch.object(flow,'prompt',return_value='synthetic-private-marker'):
            status,text=invoke(flow,'summary','--progress',progress,'--plan',plan)
        assert status!=0 and 'OpenTofu could not read the saved plan. Check the encryption passphrase' in text,text
        # Unexpected errors may contain values, so their text must stay withheld.
        with patch.object(gate,'planned_identity',side_effect=ValueError('synthetic-private-marker')):
            status,text=invoke(flow,'summary','--progress',progress,'--plan',plan)
        assert status!=0 and 'values withheld' in text


def commands(work):
    gate=fixtures.load()
    record=json.loads((ROOT/'.agents/tests/fixtures/place/place-record.json').read_text())
    place=work/'place.json';place.write_text(json.dumps(record))
    package=work/'package.json';package.write_text(json.dumps(dict(name='@masonator/coolify-mcp',version='3.10.1')))
    progress=work/'progress.json';progress.write_text(json.dumps(dict(config=dict(place=record['place'],secrets=str(work/'absent.env')),root=str(work))))
    paths=[(flow,['summary','--progress',progress,'--plan',work/'unused.plan']),
           (check,['--record',place,'--mcp-package',package]),
           (lane,['prepare','--record',place,'--lane','internal','--effect',work/'effect.json']),
           (retire,['--record',place,'--plan',work/'unused.plan','--approval',work/'approval.json'])]
    for module,args in paths:
        target=api if module==check else module
        for kind in ('gate','unknown','http'):
            def fail(*args):
                if kind=='gate':gate.refuse('The effect confirmation did not match.')
                if kind=='unknown':raise ValueError('synthetic-private-marker')
                raise urllib.error.HTTPError('https://api.hetzner.cloud/v1/servers?token=synthetic-private-marker',401,'synthetic-private-marker',{},io.BytesIO(b'synthetic-private-marker'))
            with patch.object(target,'approval_gate',return_value=gate),patch.object(gate,'configure_secrets',create=True),patch.object(gate,'SECRET_VALUES',{},create=True),patch.object(gate,'terminal',side_effect=fail):
                status,text=invoke(module,*args)
            assert status!=0
            if kind=='gate':assert 'The effect confirmation did not match.' in text,(module.__name__,text)
            if kind=='http':assert 'Hetzner answered 401.' in text,(module.__name__,text)
    # check_place catches read failures into rows; the HTTP status must survive.
    def failed_read(*args,**kwargs):raise urllib.error.HTTPError('http://100.64.0.10:8000/api/v1/version',403,'synthetic-private-marker',{},None)
    @contextmanager
    def terminal():yield None
    with patch.object(gate,'terminal',terminal),patch.object(gate,'typed',return_value='fixture'),patch.object(api,'approval_gate',return_value=gate),patch.object(gate,'configure_secrets',create=True),patch.object(api,'hidden_value',return_value='fixture'),patch.object(check,'outside_probe',return_value=False),patch('node.read_node',return_value={}),patch('node.node_rows',return_value=[]),patch.object(check.urllib.request,'build_opener',return_value=SimpleNamespace(open=failed_read)):
        status,text=invoke(check,*paths[1][1])
    assert status!=0 and 'Coolify answered 403.' in text,text


def key(work):
    gate=fixtures.load()
    shown=json.loads((ROOT/'.agents/tests/fixtures/place/fresh.show.json').read_text())
    summary=gate.summarise(shown)
    text=gate.render('0'*64,summary)
    assert 'one day' in text and 'one hour' not in text
    config=json.loads((RECIPE/'setup.example.json').read_text())
    assert config['inputs']['tailnet_key_settings']['expiry_seconds']==86400
    # Exercise the plan prompt through the real command path, without tofu plan.
    progress=work/'progress.json';progress.write_text(json.dumps(dict(root=str(work),config=dict(place=dict(name='fixture'),secrets=str(work/'absent.env')),done=[],uncertain=None)))
    labels=[]
    def prompt(g,label):labels.append(label);return 'synthetic-only'
    with patch.object(flow,'approval_gate',return_value=gate),patch.object(flow,'prompt',side_effect=prompt),patch.object(gate,'plan'),patch.object(flow,'bind_provider'):
        status,text=invoke(flow,'plan','--progress',progress,'--plan',work/'saved.plan')
    assert status==0,text
    assert any('shortest available' in label and 'one day' in label for label in labels)
    assert all('one hour' not in label for label in labels)


def main():
    cases=dict(summary=summary,commands=commands,key=key)
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=['all',*cases],default='all');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='place-feedback-') as tmp:
        for name,run in cases.items():
            if args.case not in ('all',name):continue
            work=Path(tmp)/name;work.mkdir();run(work);print('Passed: '+name)


if __name__=='__main__':main()
