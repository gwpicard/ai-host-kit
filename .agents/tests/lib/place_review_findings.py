"""Review regressions through Place commands, with synthetic inputs and transports."""
from contextlib import contextmanager
import argparse
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
from place_stage_checks import Scenario, Services, standins, flow, node, transport, COOLIFY, CLOUD
from place_secrets_checks import protected, VALUES
from checks import ROOT

@contextmanager
def available_terminal():
    yield None

def inventory(work):
    for mode in ('later-match','complete','malformed','repeated','failed-page','overfull'):
        svc=Services();case=Scenario(work/mode,'register')
        with standins(svc):
            svc.closed=False
            assert case.run()[0]!=0
            receipt=json.loads(case.receipt().read_text())
            receipt['write_state']='dispatched';flow.save(case.receipt(),receipt)
            case.recovery(True)
            before=case.progress.read_bytes();saved=case.receipt().read_bytes()
            calls=[];actual=transport.API.request
            def pages(api,method,url,token,body=None):
                if urlsplit(url).path=='/api/v1/services':
                    page=int(parse_qs(urlsplit(url).query).get('page',['1'])[0]);calls.append(page)
                    if mode=='overfull':return [dict(uuid=str(i),name='other') for i in range(51)]
                    if page==1 or mode=='repeated':return [dict(uuid='first',name='other')]
                    if mode=='failed-page':raise OSError('Synthetic unavailable page')
                    if mode=='malformed':return {'data':[]}
                    if page==2:return [dict(uuid='second',name='test-place-register' if mode=='later-match' else 'another')]
                    return []
                return actual(api,method,url,token,body)
            with patch.object(transport.API,'request',pages):status,text=case.recover()
            if mode=='complete':
                assert status==0 and calls==[1,2,3],(calls,text)
                assert json.loads(case.receipt().read_text())['status']=='not-written'
                assert case.run()[0]!=0 and not svc.writes
            else:
                assert status!=0 and case.progress.read_bytes()==before and case.receipt().read_bytes()==saved,(mode,calls,text)
                if mode=='later-match':assert 2 in calls,calls

def terminal(work):
    svc=Services();case=Scenario(work/'case','claim');svc.progress=case.progress;svc.closed=False
    gate=case.gate
    before=case.progress.read_bytes();receipts=list(case.journal.iterdir())
    def inputs(g,label):
        if label.startswith('Hetzner'):return CLOUD
        if label.startswith('Coolify'):return COOLIFY
        return transport.hidden_value(g,label)
    with standins(svc),patch.object(flow,'approval_gate',return_value=gate),patch.object(flow,'prompt',side_effect=inputs):
        status,text=case.run()
    assert status!=0 and 'terminal' in text,text
    assert svc.restarts==0 and case.progress.read_bytes()==before and list(case.journal.iterdir())==receipts
    gate.match_effect(json.loads(case.effect.read_text()),case.approval)
    class TerminalOutput(io.StringIO):
        def isatty(self): return True
    with standins(svc),patch.object(io,'StringIO',TerminalOutput),patch.object(flow,'approval_gate',return_value=gate),patch.object(sys.stdin,'isatty',return_value=True),patch.object(sys.stdout,'isatty',return_value=True),patch('builtins.open') as opened,patch.object(gate.os,'tcgetpgrp',return_value=os.getpgrp()+1):
        opened.return_value.__enter__.return_value.fileno.return_value=0
        status,text=case.run()
    assert status!=0 and 'foreground' in text and svc.restarts==0,text
    assert case.progress.read_bytes()==before and list(case.journal.iterdir())==receipts

def repository_race(work,mode):
    svc=Services();case=Scenario(work/'case','project');gate=case.gate
    case.state['done']=['claim'];flow.save(case.progress,case.state)
    directory=work/'inputs';directory.mkdir()
    secrets=protected(directory/'private.env',dict(VALUES,COOLIFY_TEAM_TOKEN=COOLIFY))
    command=('discover','--server-uuid','server-one','--destination-uuid','destination-one','--secrets',secrets)
    svc.server['ip']='localhost'
    original_run=subprocess.run
    def git_run(args,**kwargs):
        if args[0]=='git' or (args[0]==sys.executable and '-I' in args):
            assert kwargs['env']=={'PATH':os.environ['PATH'],'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}
        return original_run(args,**kwargs)
    with standins(svc),patch.object(flow,'approval_gate',return_value=gate),patch.object(flow,'prompt',transport.hidden_value),patch.object(subprocess,'run',side_effect=git_run),patch.dict(os.environ,{'TF_VAR_host_state_passphrase':VALUES['STATE_PASSPHRASE'],'PROVIDER_TOKEN':VALUES['HETZNER_PROJECT_TOKEN']}):
        assert case.command(*command)[0]==0

    before=case.progress.read_bytes();calls=len(svc.calls)
    original_open=os.open;original_run=subprocess.run;triggered=[];opened=[]
    parked=work/'parked'
    def opening(path,*args,**kwargs):
        if str(path) in (str(secrets),'private.env') and not triggered:
            triggered.append(True)
            if mode=='directory':
                directory.rename(parked);directory.mkdir()
                os.link(parked/'private.env',secrets)
            elif mode!='git-directory':
                original_run(['git','init','-q',str(directory)],check=True)
                if mode=='staged':original_run(['git','-C',str(directory),'add','private.env'],check=True)
        result=original_open(path,*args,**kwargs)
        if str(path) in (str(secrets),'private.env'):opened.append(True)
        return result
    def directory_probe(args,**kwargs):
        if mode=='git-directory' and opened and (args[0]=='git' or (args[0]==sys.executable and '-I' in args)):
            directory.rename(parked);directory.mkdir()
            try:
                original_run(['git','init','-q',str(parked)],check=True)
                original_run(['git','-C',str(parked),'add','private.env'],check=True)
                return original_run(args,**kwargs)
            finally:
                directory.rmdir();parked.rename(directory)
        return original_run(args,**kwargs)
    with standins(svc),patch.object(flow,'approval_gate',return_value=gate),patch.object(flow,'prompt',transport.hidden_value),patch.object(gate.os,'open',side_effect=opening),patch.object(subprocess,'run',side_effect=directory_probe):
        status,text=case.command(*command)
    assert triggered and status!=0 and case.progress.read_bytes()==before,(mode,text)
    assert len(svc.calls)==calls and not gate.SECRET_VALUES, 'Unsafe file values reached a transport'

def environment(work):
    svc=Services();case=Scenario(work/'case','claim');svc.progress=case.progress;svc.closed=False
    original_run=subprocess.run;seen=[]
    tools=work/'bin';tools.mkdir()
    child=tools/'tailscale'
    child.write_text('#!'+sys.executable+'\nimport os,sys\nassert set(os.environ) <= {"PATH", "LC_CTYPE"}\nassert "docker restart coolify" in sys.stdin.read()\n')
    child.chmod(0o755)
    def ssh(command,**kwargs):
        if command[0]=='tailscale':
            result=original_run(command,**kwargs);seen.append(result.returncode);svc.closed=True
            return result
        return original_run(command,**kwargs)
    with standins(svc),patch.object(flow,'approval_gate',return_value=case.gate),patch.object(case.gate,'terminal',available_terminal),patch.object(subprocess,'run',side_effect=ssh),patch.dict(os.environ,{'PATH':str(tools)+':'+os.environ['PATH'],'TF_VAR_host_state_passphrase':VALUES['STATE_PASSPHRASE'],'PROVIDER_TOKEN':VALUES['HETZNER_PROJECT_TOKEN']}):
        status,text=case.run()
    assert status==0 and seen==[0],(seen,text)

def initialisation(work):
    svc=Services();case=Scenario(work/'case','claim');gate=case.gate
    case.state.pop('record');flow.save(case.progress,case.state)
    backend=json.loads((ROOT/'.agents/skills/recipes/coolify-hetzner/tofu/backend.example.json').read_text())
    (case.folder/'backend.json').write_text(json.dumps(backend))
    with patch.object(flow,'approval_gate',return_value=gate),patch.object(flow,'prompt',return_value=VALUES['STATE_PASSPHRASE']):
        status,text=case.command('init')
        reason='The bundled encryption fragment is missing. Include it, then save and approve a new plan.'
        assert status!=0 and reason in text,text
        for method in ('s3_settings','require_encryption'):
            with patch.object(gate,method,side_effect=ValueError('synthetic-private-marker')):
                status,text=case.command('init')
            assert status!=0 and 'synthetic-private-marker' not in text and 'Values are withheld.' in text,text

def main():
    cases={'inventory':inventory,'terminal':terminal,'repository':lambda w:repository_race(w,'repository'),
           'staged':lambda w:repository_race(w,'staged'),'directory':lambda w:repository_race(w,'directory'),'git-directory':lambda w:repository_race(w,'git-directory'),
           'environment':environment,'init':initialisation}
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=['all',*cases],default='all');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='place-review-findings-') as tmp:
        for name,test in cases.items():
            if args.case not in ('all',name):continue
            path=Path(tmp)/name;path.mkdir();test(path);print('Passed: '+name)

if __name__=='__main__':main()
