"""Synthetic file and terminal inputs through the real Place command entry points."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import copy
import io
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from checks import ROOT
import approval_gate_checks as approval

RECIPE=ROOT/'.agents/skills/recipes/coolify-hetzner'
sys.path.insert(0,str(RECIPE/'scripts'))
import setup as flow
import check
import lane
import retire
import api
from place import journal_identity
from place_checks import resources

VALUES=dict(STATE_PASSPHRASE='synthetic-state-passphrase-only',
            HETZNER_PROJECT_TOKEN='synthetic-project-value',STORAGE_ACCESS_KEY='fixture-access-id',
            STORAGE_SECRET_KEY='synthetic-storage-private',TAILSCALE_AUTH_KEY='synthetic-one-off-auth',
            COOLIFY_TEAM_TOKEN='synthetic-coolify-private',TAILSCALE_API_TOKEN='synthetic-service-private',
            TAILSCALE_OAUTH_CLIENT_ID='fixture-client-id',TAILSCALE_OAUTH_CLIENT_SECRET='synthetic-oauth-private')


def protected(path, values=VALUES):
    path.write_bytes(('# Fixture only\r\n'+''.join(k+'='+v+'\r\n' for k,v in values.items())).encode())
    path.chmod(0o600)
    return path


def invoke(module, *args, **kwargs):
    output=io.StringIO()
    with patch.object(sys,'argv',[module.__name__,*map(str,args)]), redirect_stdout(output), redirect_stderr(output):
        status=module.main(**kwargs)
    text=output.getvalue()
    for value in VALUES.values():
        assert value not in text, 'A file value reached command output'
    return status,text


def terminal_pastes():
    # Use an actual controlling PTY, including its CRLF translation and queue.
    sys.stdout.flush();sys.stderr.flush()
    pid,fd=pty.fork()
    if pid==0:
        try:
            gate=approval.load()
            with gate.terminal() as tty:
                first=gate.typed(tty,'First (hidden): ')
                second=gate.typed(tty,'Second (hidden): ')
                third=gate.typed(tty,'Third (hidden): ')
                shown=gate.typed(tty,'Identifier (shown): ')
                try:
                    gate.typed(tty,'Unsafe words (shown): ')
                except gate.InputRefused:
                    pass
                else:
                    raise AssertionError('Secret-shaped shown input was accepted')
            assert (first,second,third)==('first-private-1234','second-private-5678','third-private-9012')
            assert shown=='fixture-client-id'
            print('Paste checks passed.',flush=True)
            os._exit(0)
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(1)
    output=b'';sent=set();deadline=time.monotonic()+15
    try:
        while time.monotonic()<deadline:
            if select.select([fd],[],[],0.1)[0]:
                try: output+=os.read(fd,65536)
                except OSError: pass
            for marker,data in [(b'First (hidden): ',b'first-private-1234\r\nqueued-unwanted\n'),
                                (b'Second (hidden): ',b'second-private-5678\r\n'),
                                (b'Third (hidden): ',b'\n'),
                                (b'The value was empty.',b'third-private-9012\n'),
                                (b'Identifier (shown): ',b'fixture-client-id\n'),
                                (b'Unsafe words (shown): ',b'token=synthetic-private-do-not-show\n')]:
                if marker in output and marker not in sent:
                    os.write(fd,data);sent.add(marker)
            done,status=os.waitpid(pid,os.WNOHANG)
            if done:
                assert os.waitstatus_to_exitcode(status)==0, 'Safe paste command failed: '+repr(output)
                assert b'Length: 19; last four: 5678' in output
                assert b'first-private' not in output and b'second-private' not in output
                assert b'queued-unwanted' not in output
                assert b'fixture-client-id' in output and b'synthetic-private-do-not-show' not in output
                return
        os.kill(pid,9);os.waitpid(pid,0)
        raise AssertionError('Safe paste fixture timed out')
    finally: os.close(fd)


def shown_echo():
    """Shown prompts display input as typed, never a secret-shaped burst."""
    # Each step waits for the previous output, including echoed characters,
    # so the parent proves the text appeared before Enter was sent.
    sys.stdout.flush();sys.stderr.flush()
    pid,fd=pty.fork()
    if pid==0:
        try:
            gate=approval.load()
            results=[]
            with gate.terminal() as tty:
                results.append(gate.typed(tty,'Live (shown): '))
                results.append(gate.typed(tty,'Type test-place (shown): ',expected='test-place'))
                for prompt in ('Again test-place (shown): ','Words (shown): '):
                    try:
                        gate.typed(tty,prompt,expected='test-place' if prompt.startswith('Again') else None)
                    except gate.InputRefused:results.append('refused')
                    else:results.append('accepted')
                results.append(gate.typed(tty,'Optional (shown): ',optional=True))
            assert results==['abcd','test-place','refused','refused',''],results
            print('Echo checks passed.',flush=True)
            os._exit(0)
        except BaseException:
            import traceback
            traceback.print_exc();sys.stderr.flush();os._exit(1)
    steps=[(b'Live (shown): ',b'abc'),(b'Live (shown): abc',b'X'),(b'abcX',b'\x7fd\n'),
           (b'Type test-place (shown): ',b'test-pl'),(b'(shown): test-pl',b'ace\r\n'),
           (b'Again test-place (shown): ',b'test-plx\n'),
           (b'Words (shown): ',b'note '),(b'(shown): note ',b'token=synthetic-private-do-not-show\n'),
           (b'Optional (shown): ',b'\n')]
    output=b'';step=0;deadline=time.monotonic()+15
    try:
        while time.monotonic()<deadline:
            if select.select([fd],[],[],0.05)[0]:
                try:output+=os.read(fd,65536)
                except OSError:pass
            if step<len(steps) and steps[step][0] in output:
                os.write(fd,steps[step][1]);step+=1
            done,status=os.waitpid(pid,os.WNOHANG)
            if done:
                assert os.waitstatus_to_exitcode(status)==0 and step==len(steps),'Shown echo command failed: '+repr(output)
                # Typed characters appeared before Enter; backspace erased one.
                assert b'Live (shown): abcX\x08 \x08d' in output,output
                # Known text: a wrong character is refused before display.
                assert b'test-plx' not in output
                # A secret-shaped burst is refused, and the shown words are erased.
                assert b'synthetic-private-do-not-show' not in output and b'note \x08 \x08\x08 \x08' in output,output
                return
        os.kill(pid,9);os.waitpid(pid,0)
        raise AssertionError('Shown echo fixture timed out at step '+str(step)+': '+repr(output))
    finally:os.close(fd)


def stage_input_boundaries(work):
    """The same failed input must leave each real command's approval unused."""
    gate=approval.load()
    record=json.loads((ROOT/'.agents/tests/fixtures/place/place-record.json').read_text())
    class API:
        def __init__(self,*args):pass
        def token_abilities(self):return None
        def registration_closed(self):return True
        def coolify_version(self):return '4.7.5'
        def request(self,*args):return {'ports':['tcp:443']}
    @contextmanager
    def terminal():yield None
    for step,target in [('claim','Coolify'),('claim','Hetzner'),('oauth-id','TAILSCALE_OAUTH_CLIENT_ID'),
                        ('oauth-secret','TAILSCALE_OAUTH_CLIENT_SECRET'),('register','Tailscale API'),
                        ('start-register','Tailscale API'),('record','Tailscale API')]:
        folder=work/(step+'-'+target.replace(' ','-'));folder.mkdir()
        choice=folder/'choice.json';choice.write_text('{}')
        journal=folder/'place-attempts'
        state=dict(root=str(folder),record=record,done=flow.STEPS[:flow.STEPS.index(step)],uncertain=None,
            choice_path=str(choice),choice_sha256=flow.fingerprint({}),journal=journal_identity(journal),
            config=dict(place=record['place'],secrets=str(folder/'absent.env'),canary_name='place-canary',scopes=sorted(flow.SCOPES)),
            project_uuid='project-one',docktail_uuid='docktail-one',register_uuid='register-one',server_uuid='server-one',destination_uuid='destination-one')
        progress=folder/'progress.json';flow.save(progress,state)
        effect=flow.effect_for(state,step);effect_path=folder/'effect.json';effect_path.write_text(json.dumps(effect))
        approved=folder/'approval.json';approved.write_text(json.dumps(dict(effect_sha256=gate.effect_sha(effect),effect=effect['effect'],words='Synthetic fixture approval',approved_at='2026-11-17T12:00:00Z',method='foreground-terminal')))
        before=progress.read_bytes();receipts=list(journal.iterdir())
        requested=[]
        def missing(g,label):
            if label.startswith(target):
                requested.append(label)
                raise flow.OperationRefused('Synthetic missing input.')
            return 'claimed '+record['place']['name'] if 'type claimed' in label else 'synthetic-only'
        with patch.object(gate,'terminal',terminal),patch.object(gate,'configure_secrets'),patch.object(gate,'SECRET_VALUES',{'COOLIFY_TEAM_TOKEN':'synthetic-only'}),patch.object(flow,'approval_gate',return_value=gate),patch.object(flow,'prompt',side_effect=missing),patch.object(flow,'API',API):
            assert invoke(flow,'run','--step',step,'--progress',progress,'--effect',effect_path,'--approval',approved)[0]!=0
        assert requested, 'The fixture did not reach the missing input at '+step
        assert progress.read_bytes()==before and list(journal.iterdir())==receipts, 'Input failure consumed approval at '+step
        gate.match_effect(effect,approved)
    print('Existing stage inputs fail before an attempt is recorded.')


def exercise(work):
    gate=approval.load()
    reader=flow.load_reader()
    record=json.loads((ROOT/'.agents/tests/fixtures/place/place-record.json').read_text())
    choice=dict(schema_version='1.0',choice=dict(host='coolify-hetzner',proven=False,answers={},accepted_shortfalls=[]))
    choice_path=work/'hosting/place-record.json';choice_path.parent.mkdir();choice_path.write_text(json.dumps(choice))
    config=json.loads((RECIPE/'setup.example.json').read_text())
    config['place']=record['place'];config['encrypted_state']=record['encrypted_state']
    secrets=protected(work/'inputs.env');config['secrets']=str(secrets)
    settings=work/'setup.json';settings.write_text(json.dumps(config))
    progress=work/'progress.json';root=work/'root'
    def command(*args):
        with patch.object(flow,'approval_gate',return_value=gate):
            return invoke(flow,*args,'--progress',progress)
    assert command('root','--config',settings,'--choice',choice_path,'--directory',root)[0]==0
    state=json.loads(progress.read_text());state.update(record=record,done=['claim'])
    flow.save(progress,state)
    requests=[]
    class API:
        def __init__(self, r, cloud, coolify=None):
            if coolify: assert coolify==VALUES['COOLIFY_TEAM_TOKEN']
        def request(self,method,url,*args):
            requests.append(url)
            if url.endswith('/destinations'): return [{'uuid':'destination-one'}]
            return {'ip':'host.docker.internal','name':'localhost'}
        def registration_state(self): return "open"
        def token_abilities(self): return None # Real pinned API has no introspection.
        def firewall_rules(self,*args): return []
        def owned_resources(self,**kwargs): return resources(record)
    with patch.object(flow,'API',API):
        assert command('discover','--server-uuid','server-one','--destination-uuid','destination-one')[0]==0
        # Every unsafe file is refused on the command path before a transport.
        repository=work/'repository';repository.mkdir()
        subprocess.run(['git','init','-q',str(repository)],check=True)
        in_repo=protected(repository/'inputs.env')
        subprocess.run(['git','-C',str(repository),'add','inputs.env'],check=True)
        untracked=protected(repository/'untracked.env')
        permissive=protected(work/'permissive.env');permissive.chmod(0o644)
        link=work/'symlink.env';link.symlink_to(secrets)
        directory=work/'directory.env';directory.mkdir()
        malformed=protected(work/'malformed.env',{'BAD KEY':'synthetic-private'})
        for path in (in_repo,untracked,permissive,link,directory,malformed):
            before=len(requests)
            assert command('discover','--secrets',path,'--server-uuid','server-one','--destination-uuid','destination-one')[0]!=0
            assert len(requests)==before
        with patch.object(gate.os,'getuid',return_value=os.getuid()+1):
            assert command('discover','--server-uuid','server-one','--destination-uuid','destination-one')[0]!=0
        # Missing input must not spend a valid synthetic effect approval.
        state=json.loads(progress.read_text());state['done']=flow.STEPS[:flow.STEPS.index('register')]
        state.update(project_uuid='project-one',docktail_uuid='docktail-one')
        flow.save(progress,state)
        effect=work/'register-effect.json';approval_path=work/'register-approval.json'
        assert command('prepare','--step','register','--effect',effect)[0]==0
        value=json.loads(effect.read_text())
        approval_path.write_text(json.dumps(dict(effect_sha256=gate.effect_sha(value),effect=value['effect'],
            words='Synthetic fixture approval',approved_at='2026-11-17T12:00:00Z',method='foreground-terminal')))
        missing=protected(work/'missing.env',{k:v for k,v in VALUES.items() if k!='TAILSCALE_API_TOKEN'})
        before=progress.read_bytes();journal=choice_path.parent/'place-attempts'
        receipts=list(journal.iterdir())
        status,text=command('run','--step','register','--effect',effect,'--approval',approval_path,'--secrets',missing)
        assert status!=0 and progress.read_bytes()==before
        assert list(journal.iterdir())==receipts and approval_path.exists()
        gate.match_effect(value,approval_path)
        # OAuth inputs must also be resolved before starting their attempt.
        for step,key in [('oauth-id','TAILSCALE_OAUTH_CLIENT_ID'),('oauth-secret','TAILSCALE_OAUTH_CLIENT_SECRET')]:
            state['done']=flow.STEPS[:flow.STEPS.index(step)];flow.save(progress,state)
            effect=work/(step+'.json');approval_path=work/(step+'-approval.json')
            assert command('prepare','--step',step,'--effect',effect)[0]==0
            value=json.loads(effect.read_text());approval_path.write_text(json.dumps(dict(effect_sha256=gate.effect_sha(value),
                effect=value['effect'],words='Synthetic fixture approval',approved_at='2026-11-17T12:00:00Z',method='foreground-terminal')))
            missing=protected(work/(step+'.env'),{k:v for k,v in VALUES.items() if k!=key})
            before=progress.read_bytes()
            assert command('run','--step',step,'--effect',effect,'--approval',approval_path,'--secrets',missing)[0]!=0
            assert progress.read_bytes()==before and list(journal.iterdir())==receipts
    # Password-manager output and failures never reach command output.
    state['done']=['claim'];flow.save(progress,state)
    reference=protected(work/'reference.env',dict(VALUES,COOLIFY_TEAM_TOKEN='op://fixture/item/token'))
    with patch.object(flow,'API',API),patch.object(gate.shutil,'which',return_value=None):
        status,text=command('discover','--secrets',reference,'--server-uuid','server-one','--destination-uuid','destination-one')
        assert status!=0 and 'Install the 1Password CLI' in text
    actual=gate.subprocess.run
    def op_read(args,**kwargs):
        if args[0]=='/fixture/op':
            assert args==['/fixture/op','read','op://fixture/item/token']
            assert not any(v in kwargs['env'].values() for v in VALUES.values())
            return subprocess.CompletedProcess(args,0,(VALUES['COOLIFY_TEAM_TOKEN']+'\r\n').encode(),b'')
        return actual(args,**kwargs)
    # Restore discover's stage after the input-failure probes.
    state['done']=['claim'];flow.save(progress,state)
    with patch.object(flow,'API',API),patch.object(gate.shutil,'which',return_value='/fixture/op'),patch.object(gate.subprocess,'run',side_effect=op_read):
        assert command('discover','--secrets',reference,'--server-uuid','server-one','--destination-uuid','destination-one')[0]==0
    # Read-only entry points accept the file with non-terminal stdin and stdout.
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return b'4.7.5'
    def version(r):
        assert r.get_header('Authorization')=='Bearer '+VALUES['COOLIFY_TEAM_TOKEN']
        return Response()
    with patch.object(api,'approval_gate',return_value=gate),patch.object(check.urllib.request,'build_opener',return_value=SimpleNamespace(open=lambda r,**kw:version(r))),patch.object(check,'check_place',side_effect=lambda r,probe,read:[('Version','passed' if read('100.64.0.10')=='4.7.5' else 'failed')]),patch('node.read_node',return_value={}),patch('node.node_rows',return_value=[]):
        place=work/'place.json';place.write_text(json.dumps(record))
        assert invoke(check,'--record',place,'--config',settings)[0]==0
    with patch.object(lane,'approval_gate',return_value=gate),patch.object(lane,'API',API):
        assert invoke(lane,'prepare','--record',place,'--lane','internal','--effect',work/'lane-effect.json','--config',settings)[0]==0
    # A missing person-only confirmation must leave the claim approval unused.
    state['done']=[];flow.save(progress,state)
    effect=work/'claim.json';approved=work/'claim-approval.json'
    assert command('prepare','--step','claim','--effect',effect)[0]==0
    value=json.loads(effect.read_text())
    approved.write_text(json.dumps(dict(effect_sha256=gate.effect_sha(value),effect=value['effect'],words='Synthetic fixture approval',
        approved_at='2026-11-17T12:00:00Z',method='foreground-terminal')))
    before=progress.read_bytes();receipts=list(journal.iterdir())
    with patch.object(flow,'reopen_claim') as restart,patch.object(flow,'API',API):
        assert command('run','--step','claim','--effect',effect,'--approval',approved)[0]!=0
    restart.assert_not_called()
    assert progress.read_bytes()==before and list(journal.iterdir())==receipts
    gate.match_effect(value,approved)
    # Retirement gets its file values, then refuses the typed name without a TTY.
    destroy=dict(resource_changes=[dict(type='hcloud_'+kind,change=dict(actions=['delete'],before=value)) for kind,value in resources(record).items()])
    from contextlib import contextmanager
    @contextmanager
    def saved(*args):yield ('synthetic-plan','0'*64)
    def identity(*args):gate.storage_credentials()
    with patch.object(retire,'approval_gate',return_value=gate),patch.object(retire,'API',API),patch.object(gate,'require_encryption'),patch.object(gate,'check_version'),patch.object(gate,'saved_plan',saved),patch.object(gate,'planned_identity',side_effect=identity),patch.object(gate,'tofu',return_value=subprocess.CompletedProcess([],0,json.dumps(destroy).encode(),b'')),patch.object(gate,'apply',side_effect=AssertionError('Retirement passed the terminal boundary')):
        assert invoke(retire,'--record',place,'--plan','synthetic.plan','--approval',work/'retire-approval.json','--config',settings)[0]!=0
    assert 'TF_VAR_host_state_passphrase' not in os.environ
    # Bootstrap's fixed node reads need no file value and no terminal.
    state['applied']=True
    state['outputs']=dict(server_id=101,firewall_id=102,ssh_key_id=103,ipv4_address='192.0.2.10')
    flow.save(progress,state)
    facts=dict(coolify_healthy=True,cloud_init_state='done',status=dict(BackendState='Running',MagicDNSSuffix='fixture.ts.net',Self=dict(HostName=record['place']['name'],TailscaleIPs=['100.64.0.10'],Tags=['tag:server'],KeyExpiry=None)),prefs=dict(RunSSH=True),key_file_gone=True,instance_id='101',cloud_init={'v1':{'errors':[]}})
    with patch.object(flow,'read_node',return_value=facts):
        assert command('bootstrap','--address','100.64.0.10')[0]==0
    state=json.loads(progress.read_text());state.pop('applied',None)
    # Approvals still require the real terminal even when every secret is present.
    for kind in ('approve','approve-effect'):
        source=work/('register-effect.json' if kind=='approve-effect' else 'unread.plan')
        status,text=invoke(gate,kind,source,work/(kind+'.json'),'--secrets',secrets)
        assert status!=0 and 'terminal' in text and not (work/(kind+'.json')).exists()
    # A local built-in OpenTofu root exercises plan and summary without a provider.
    shutil.rmtree(root);root.mkdir()
    shutil.copyfile(approval.FIXTURES/'main.tf',root/'main.tf')
    shutil.copyfile(ROOT/'tofu/encryption.tf',root/'encryption.tf')
    (root/'backend.json').write_text(json.dumps(config['backend']))
    approval.tofu(root,'init','-input=false')
    state['done']=[];state.pop('record',None);flow.save(progress,state)
    with patch.dict(os.environ,{'TF_VAR_fixture_secret':'synthetic-tofu-input'}):
        actual=gate.tofu
        def init_only(*args):
            if args[0]=='init':return subprocess.CompletedProcess(args,0,b'',b'')
            return actual(*args)
        with patch.object(gate,'tofu',side_effect=init_only):
            assert command('init')[0]==0
            storage_reference=protected(work/'storage-reference.env',dict(VALUES,STORAGE_SECRET_KEY='op://fixture/item/storage'))
            with patch.object(gate.shutil,'which',return_value=None):
                status,text=command('init','--secrets',storage_reference)
                assert status!=0 and 'Install the 1Password CLI' in text
        for kind in ('plan','plan-destroy'):
            plan=work/(kind+'.plan')
            from prerequisite_standins import ready
            with ready(flow):assert command(kind,'--plan',plan)[0]==0
            assert command('summary','--plan',plan)[0]==0
        status,text=command('approve','--plan',plan,'--approval',work/'plan-approval.json')
        assert status!=0 and 'terminal' in text
        with approval.directory(root),patch.dict(os.environ,{'TF_VAR_host_state_passphrase':VALUES['STATE_PASSPHRASE']}):
            with gate.saved_plan(plan) as (snapshot,sha):
                target=gate.planned_identity(plan,sha);summary=gate.read_plan(snapshot)
        target['project_sha256']='0'*64
        mismatched=work/'mismatched-approval.json'
        mismatched.write_text(json.dumps(dict(schema_version='1.0',plan_sha256=sha,approved_at='2026-11-17T12:00:00Z',
            words='Synthetic fixture approval',confirmation='approve '+gate.short_hash(sha),method='terminal-checksum',summary=summary,target=target)))
        before=progress.read_bytes()
        with patch.object(gate,'apply',side_effect=AssertionError('Mismatched approval reached apply')):
            assert command('apply','--plan',plan,'--approval',mismatched)[0]!=0
        assert progress.read_bytes()==before, 'Invalid approval marked the apply uncertain'
    # No OpenTofu version child receives values it does not use.
    gate.configure_secrets(secrets);gate.storage_credentials()
    def child(args,**kwargs):
        assert not any(v in kwargs['env'].values() for v in VALUES.values())
        return subprocess.CompletedProcess(args,0,b'{}',b'')
    with patch.dict(os.environ,{'TF_VAR_host_state_passphrase':VALUES['STATE_PASSPHRASE']}),patch.object(gate.subprocess,'run',side_effect=child):
        gate.tofu('version','-json')
    print('Protected file, command input boundaries and non-terminal reads passed.')


if __name__=='__main__':
    if '--stage-only' in sys.argv:
        with tempfile.TemporaryDirectory(prefix='ai-host-kit-stage-inputs-') as tmp:
            stage_input_boundaries(Path(tmp))
        sys.exit(0)
    if '--terminal-only' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='ai-host-kit-secret-checks-') as tmp:
            exercise(Path(tmp))
            stage_input_boundaries(Path(tmp))
    terminal_pastes()
    print('Safe terminal paste and empty-value retry passed.')
    shown_echo()
    print('Shown prompts echo as typed and refuse secret-shaped or unmatched text before display.')
