"""Exercise review, approval and path defaults through offline Place commands."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import argparse
import copy
import io
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from checks import ROOT
import approval_gate_checks as plans
SOURCE=Path(os.environ.get('GUIDANCE_SOURCE_ROOT',ROOT))
RECIPE=SOURCE/'.agents/skills/recipes/coolify-hetzner'
plans.SKILL=SOURCE/'.agents/skills/setup-hosting'
sys.path.insert(0,str(RECIPE/'scripts'))
import setup as flow
import node
import lane
import retire
from place_checks import resources


def terminal(action, answers, live=False):
    # Synthetic input to a controlling terminal is fixture machinery only.
    sys.stdout.flush();sys.stderr.flush()
    pid,fd=pty.fork()
    if pid==0:
        try:
            status=action()
        except BaseException:
            import traceback
            traceback.print_exc();status=1
        sys.stdout.flush();sys.stderr.flush();os._exit(status or 0)
    output=b'';sent=set();deadline=time.monotonic()+20;pending=None;observed=False
    try:
        while time.monotonic()<deadline:
            if select.select([fd],[],[],0.05)[0]:
                try:chunk=os.read(fd,65536)
                except OSError:chunk=b''
                output+=chunk
            for i,(marker,answer) in enumerate(answers):
                if marker in output and i not in sent:
                    if live and i==0 and answer:
                        os.write(fd,answer[:1].encode());pending=answer[1:];observed=True
                    else:os.write(fd,(answer+'\n').encode())
                    sent.add(i)
            if pending is not None and output.endswith(answers[0][1][:1].encode()):
                os.write(fd,(pending+'\n').encode());pending=None
            done,status=os.waitpid(pid,os.WNOHANG)
            if done:
                while select.select([fd],[],[],0)[0]:
                    try:chunk=os.read(fd,65536)
                    except OSError:break
                    if not chunk:break
                    output+=chunk
                if live:assert observed and pending is None,'Checksum was not visible before Enter: '+repr(output)
                return os.waitstatus_to_exitcode(status),output.decode(errors='replace')
        os.kill(pid,9);os.waitpid(pid,0)
        raise AssertionError('Terminal command did not reach the expected prompt: '+repr(output))
    finally:os.close(fd)


class Fixture:
    def __init__(self,work):
        self.work=work;self.home=(work/'home').resolve();self.home.mkdir()
        self.gate=plans.load(plans.SKILL);self.root=plans.fixture_plans(work)
        self.record=json.loads((ROOT/'.agents/tests/fixtures/place/place-record.json').read_text())
        self.shown=json.loads((ROOT/'.agents/tests/fixtures/place/fresh.show.json').read_text())
        self.choice=work/'choice.json'
        choice=dict(schema_version='1.0',choice=dict(host='coolify-hetzner',proven=False,answers={},accepted_shortfalls=[]))
        self.choice.write_text(json.dumps(choice))
        self.secrets=work/'fixture.env'
        self.secrets.write_text('STATE_PASSPHRASE='+plans.PASSPHRASE+'\nHETZNER_PROJECT_TOKEN=synthetic-project-only\nTAILSCALE_AUTH_KEY=tskey-auth-synthetic-only\nCOOLIFY_TEAM_TOKEN=synthetic-coolify-only\n')
        self.secrets.chmod(0o600)
        self.progress=work/'progress.json'
        self.state=dict(root=str(self.root),done=[],uncertain=None,record=self.record,
            choice_path=str(self.choice),choice_sha256=flow.fingerprint(choice),
            journal=flow.journal_identity(work/'place-attempts'),config=dict(place=self.record['place'],
                encrypted_state=self.record['encrypted_state'],secrets=str(self.secrets),canary_name='place-canary',scopes=sorted(flow.SCOPES)))
        flow.save(self.progress,self.state)
        self.original=self.gate.tofu
        self.calls=[]
    def tofu(self,*args):
        self.calls.append(args)
        if args[0]=='show':return subprocess.CompletedProcess(args,0,json.dumps(self.shown).encode(),b'')
        if args[0]=='apply':
            (self.work/'applied-plan-sha').write_text(self.gate.digest(Path(args[1]).read_bytes()))
            return subprocess.CompletedProcess(args,0,b'',b'')
        if args[0]=='output':
            return subprocess.CompletedProcess(args,0,json.dumps({key:dict(value=value) for key,value in
                dict(server_id=101,firewall_id=102,ssh_key_id=103,ipv4_address='192.0.2.10').items()}).encode(),b'')
        return self.original(*args)
    def raw(self,*args):
        with patch.object(sys,'argv',['setup',*map(str,args),'--progress',str(self.progress)]),patch.object(flow,'approval_gate',return_value=self.gate):
            return flow.main()
    def command(self,*args):
        out=io.StringIO()
        with redirect_stdout(out),redirect_stderr(out):status=self.raw(*args)
        return status,out.getvalue()
    def load(self):return json.loads(self.progress.read_text())
    def save(self,**changes):
        state=self.load();state.update(changes);flow.save(self.progress,state)
    def approve(self,extra=(),words='',confirmation=None,live=False):
        path=Path(self.load().get('saved_plan',self.root/'first.plan'))
        checksum=self.gate.short_hash(self.gate.digest(path.read_bytes()))
        answers=[(b'Type the checksum alone',checksum if confirmation is None else confirmation),
                 (b'In your own words, what do you approve?',words)]
        return terminal(lambda:self.raw('approve',*extra),answers,live=live)


def summary(f):
    path=f.root/'first.plan'
    status,text=f.command('summary','--plan',path)
    assert status==0,text
    for value in ('name: not set -> test-place','server_type: not set -> cx23','location: not set -> fsn1',
                  'image: not set -> ubuntu-24.04','labels.purpose: not set -> ai-host-kit',
                  'ipv4_enabled: not set -> enabled','ipv6_enabled: not set -> disabled'):
        assert value in text,value
    assert text.strip().endswith('Read-back checksum: '+f.gate.short_hash(f.gate.digest(path.read_bytes())))
    assert 'tskey-auth-synthetic-only' not in text and '#!/bin/bash' not in text
    original=copy.deepcopy(f.shown)
    server=next(r for r in f.shown['resource_changes'] if r['type']=='hcloud_server')
    for mask in ('before_sensitive','after_sensitive','after_unknown'):
        for field,value in [('name','private-fixture-name'),('image','private-fixture-image'),('labels',{'private_label':'private-fixture-label'})]:
            saved=copy.deepcopy(server['change'])
            server['change']['after'][field]=value;server['change'][mask]={field:True}
            status,text=f.command('summary','--plan',path)
            assert status==0 and 'private-fixture' not in text,(mask,field)
            server['change']=saved
    server['change']['after']['name']='ghp_'+'0123456789abcdefghijklmnopqrstuvwxyz'
    server['change']['after']['labels']['purpose']='token=private-fixture-label'
    server['change']['after']['labels']['api_token']='private-fixture-value'
    assert 'private-fixture' not in f.command('summary','--plan',path)[1]
    assert 'ghp_' not in f.command('summary','--plan',path)[1]
    f.shown=original
    firewall=next(r for r in f.shown['resource_changes'] if r['type']=='hcloud_firewall')
    firewall['change']['after']['rule']=[dict(direction='in',protocol='tcp',port='443',source_ips=['0.0.0.0/0','::/0'])]
    status,text=f.command('summary','--plan',path)
    assert status==0 and 'port: not set -> 443' in text and 'all sources (0.0.0.0/0)' in text and 'all sources (::/0)' in text
    for r in f.shown['resource_changes']:
        change=r['change'];change.update(actions=['delete'],before=change['after'],after=None,after_unknown=False)
        if r['type']=='hcloud_server':change['before']['ipv4_address']='192.0.2.10'
    status,text=f.command('summary','--plan',path)
    assert status==0 and 'name: test-place -> not set' in text and 'server_type: cx23 -> not set' in text
    assert 'ipv4_address: 192.0.2.10 -> not set' in text
    assert 'Possibly affects' not in text and 'network or public-access change' not in text
    assert 'hcloud_server.place: destruction removes the server disk' in text
    assert 'hcloud_firewall.coolify: destruction' not in text and 'hcloud_ssh_key.place: destruction' not in text


def approval(f):
    path=f.root/'first.plan';dest=f.work/'review.json'
    extra=('--plan',path,'--approval',dest)
    status,text=f.approve(extra,live=True)
    assert status==0 and dest.exists(),text
    record=f.gate.validate_record(dest)
    assert record['words']=='' and record['confirmation']=='approve '+f.gate.short_hash(record['plan_sha256'])
    with plans.directory(f.root):
        f.gate.match_record(record,record['plan_sha256'],f.gate.read_plan(path))
    dest.unlink()
    for confirmation,words in [('', ''),('0000-0000-0000',''),('token=private-fixture-secret',''),(None,'token=private-fixture-secret')]:
        status,text=f.approve(extra,confirmation=confirmation,words=words)
        assert status!=0 and not dest.exists(),text
        assert 'private-fixture-secret' not in text
    assert not any(call[0]=='apply' for call in f.calls)


def effect(f):
    f.save(applied=True)
    effect_path=f.work/'claim.json';approved=f.work/'claim-approved.json'
    status,prepared=f.command('prepare','--step','claim','--effect',effect_path)
    assert status==0,prepared
    value=json.loads(effect_path.read_text())
    assert value['effect'] not in prepared,'Prepare printed the effect before approval'
    checksum=f.gate.short_hash(f.gate.effect_sha(value))
    def approve_effect():
        with patch.object(sys,'argv',['gate','approve-effect',str(effect_path),str(approved)]):return f.gate.main()
    status,text=terminal(approve_effect,[(b'Type the checksum alone',checksum),(b'Your words, optional','')],live=True)
    assert status==0,text
    assert (prepared+text).count(value['effect'])==1,'Effect was printed twice'
    f.gate.match_effect(value,approved)
    assert json.loads(approved.read_text())['words']==''
    approved.unlink()
    for answer,words in [('', ''),('0000-0000-0000',''),(checksum,'password=private-fixture-secret')]:
        status,text=terminal(approve_effect,[(b'Type the checksum alone',answer),(b'Your words, optional',words)])
        assert status!=0 and not approved.exists() and 'private-fixture-secret' not in text
    class API:
        def __init__(self,*args):pass
        def firewall_rules(self,*args):return []
    record=f.work/'record.json';record.write_text(json.dumps(f.record))
    lane_path=f.work/'lane.json'
    out=io.StringIO()
    with patch.object(lane,'approval_gate',return_value=f.gate),patch.object(lane,'API',API),patch.object(sys,'argv',
         ['lane','prepare','--record',str(record),'--lane','public','--port','443','--effect',str(lane_path),'--secrets',str(f.secrets)]),redirect_stdout(out):
        assert lane.main()==0
    assert json.loads(lane_path.read_text())['effect'] not in out.getvalue(),'Lane prepare duplicated the effect'


def paths(f):
    # Stale shell names are deliberately set and never used by the command.
    with patch.dict(os.environ,{'CREATE':str(f.root/'first.plan'),'DESTROY':str(f.root/'second.plan')}):
        status,text=f.command('plan');assert status==0,text
        first=Path(f.load()['saved_plan'])
        assert first==f.home/'.local/share/ai-host-kit/plans/test-place/create-1.plan'
        status,text=f.command('plan');assert status==0,text
    second=Path(f.load()['saved_plan']);assert second.name=='create-2.plan' and first.exists()
    assert 'prune-plans' in text
    assert f.command('summary')[0]==0
    status,text=f.approve();assert status==0,text
    approval_path=Path(f.load()['saved_approval']);assert approval_path.parent==second.parent and approval_path.name=='approval-1.json'
    assert f.command('approve')[0]!=0,'A non-terminal approved a plan'
    assert f.command('apply')[0]==0
    assert f.command('apply')[0]!=0,'A place was applied twice'
    other=second.parent/'destroy-1.plan';other.write_bytes(b'fixture retained opposite operation')
    sidecar=f.gate.identity_path(first);assert sidecar.exists()
    status,text=terminal(lambda:f.raw('prune-plans'),[(b'Type delete','')])
    assert status==0 and first.exists() and sidecar.exists()
    status,text=terminal(lambda:f.raw('prune-plans'),[(b'Type delete','delete')])
    assert status==0 and not first.exists() and not sidecar.exists() and second.exists() and other.exists() and approval_path.exists()
    owned=resources(f.record)
    f.shown=dict(format_version='1.2',resource_changes=[dict(address='module.place.hcloud_'+kind+('.coolify' if kind=='firewall' else '.place'),type='hcloud_'+kind,change=dict(actions=['delete'],before=value,after=None)) for kind,value in owned.items()])
    assert f.command('plan-destroy')[0]==0
    destroy=Path(f.load()['saved_plan']);assert destroy.name=='destroy-2.plan'
    assert 'saved_approval' not in f.load(),'Old approval selected for a new plan'
    status,text=f.approve();assert status==0,text
    assert Path(f.load()['saved_approval']).name=='approval-2.json'
    record_path=f.work/'retire-record.json';record_path.write_text(json.dumps(f.record))
    class API:
        def __init__(self,*args):pass
        def owned_resources(self,**kwargs):return owned
        def inventory(self,kind):return []
    with patch.object(retire,'API',API):
        before=sum(call[0]=='apply' for call in f.calls)
        status,text=terminal(lambda:f.raw('retire','--choice',record_path),[(b'Type test-place (shown):','wrong-place')])
        assert status!=0 and sum(call[0]=='apply' for call in f.calls)==before,text
        status,text=terminal(lambda:f.raw('retire','--choice',record_path),[(b'Type test-place (shown):','test-place')])
        assert status==0 and 'Destruction completed' in text,text
        assert (f.work/'applied-plan-sha').read_text()==f.gate.digest(destroy.read_bytes())

    # Locks and unsafe folders refuse before invoking OpenTofu planning.
    f.save(applied=False,record=f.record)
    before=len(f.calls)
    with flow.progress_lock(f.progress):
        status,text=f.command('plan');assert status!=0 and 'Another setup command' in text
        assert len(f.calls)==before
    with flow.plan_folder(f.gate,'test-place'):
        status,text=f.command('plan');assert status!=0 and 'Another plan command' in text
    assert len(f.calls)==before
    original_folder=flow.plan_folder
    @contextmanager
    def progressed(*args):
        with original_folder(*args) as directory:
            f.save(uncertain='apply')
            yield directory
    with patch.object(flow,'plan_folder',side_effect=progressed):
        status,text=f.command('plan');assert status!=0 and len(f.calls)==before,'A stale progress read passed the plan lock'
    f.save(uncertain=None)
    folder=second.parent
    parked=folder.with_name('parked');folder.rename(parked);folder.symlink_to(parked,target_is_directory=True)
    assert f.command('plan')[0]!=0
    folder.unlink();parked.rename(folder)
    subprocess.run(['git','init','-q',str(folder)],check=True)
    assert f.command('plan')[0]!=0 and len(f.calls)==before


def bootstrap(f):
    f.save(applied=True,outputs=dict(server_id=101,firewall_id=102,ssh_key_id=103,ipv4_address='192.0.2.10'))
    facts=dict(status=dict(BackendState='Running',MagicDNSSuffix='fixture.ts.net',Self=dict(HostName='test-place',
        TailscaleIPs=['100.64.0.10'],Tags=['tag:server'],KeyExpiry=None)),prefs=dict(RunSSH=True),instance_id='101',key_file_gone=True,
        cloud_init={'v1':{'errors':[]}},cloud_init_state='done',coolify_healthy=True)
    status=dict(BackendState='Running',Peer={'node':dict(HostName='test-place',DNSName='test-place.fixture.ts.net.',
        TailscaleIPs=['100.64.0.10','fd7a:115c:a1e0::10'])})
    original=subprocess.run;calls=[]
    def client(args,**kwargs):
        if args[0]!='tailscale':return original(args,**kwargs)
        calls.append(args)
        assert args==['tailscale','status','--json'],args
        assert set(kwargs['env'])=={'PATH'} and kwargs['stdin']==subprocess.DEVNULL
        return subprocess.CompletedProcess(args,0,json.dumps(status).encode(),b'')
    reads=[]
    def read(address):reads.append(address);return facts
    with patch.object(node.subprocess,'run',side_effect=client),patch.object(flow,'read_node',side_effect=read):
        code,text=f.command('bootstrap');assert code==0,text
        assert reads==['100.64.0.10'] and calls
        for peers in ({},{'a':status['Peer']['node'],'b':status['Peer']['node']},
                      {'x':dict(HostName='different',TailscaleIPs=['100.64.0.10'])},
                      {'x':dict(HostName='test-place',TailscaleIPs=['192.0.2.10'])}):
            status['Peer']=peers;before=len(reads)
            code,text=f.command('bootstrap');assert code!=0 and len(reads)==before,text
        assert 'unique' in text or 'usable' in text
        code,text=f.command('bootstrap','--address','100.64.0.10');assert code==0,text
        bad=copy.deepcopy(facts);bad['instance_id']='999'
        with patch.object(flow,'read_node',return_value=bad):assert f.command('bootstrap','--address','100.64.0.10')[0]!=0


def guidance(f):
    assert f.command('plan','--plan',f.work/'create.plan')[0]==0
    with plans.directory(f.root):
        record=plans.record_for(f.gate,f.work/'create.plan')
    (f.work/'approved.json').write_text(json.dumps(record))
    status,text=f.command('apply','--plan',f.work/'create.plan','--approval',f.work/'approved.json')
    assert status==0,text
    assert 'Cloud-init takes several minutes' in text and 'bootstrap waits for it' in text
    assert 'Run bootstrap' in text and 'administrator claim' in text


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=['summary','approval','effect','paths','bootstrap','guidance'])
    args=parser.parse_args()
    cases=[args.case] if args.case else ['summary','approval','effect','paths','bootstrap','guidance']
    for case in cases:
        with tempfile.TemporaryDirectory(prefix='ai-host-kit-guidance-') as temp:
            f=Fixture(Path(temp))
            with patch.object(Path,'home',return_value=f.home),patch.dict(os.environ,plans.ENV),patch.object(f.gate,'tofu',side_effect=f.tofu):
                globals()[case](f)
        print('Place command regression passed: '+case)
    return 0

if __name__=='__main__':sys.exit(main())
