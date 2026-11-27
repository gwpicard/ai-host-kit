"""Strict loopback services through the setup command, with synthetic approvals."""
# The Coolify stand-in follows the v4.7.5 controllers for every route the kit
# calls: fixed field lists, base64 Compose, key-only variable lookup and the
# deployment flags that the service variable routes drop unread.
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import argparse
import base64
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
import urllib.error
import urllib.request

from checks import ROOT

RECIPE=Path(os.environ.get('PLACE_STAGE_RECIPE',ROOT/'.agents/skills/recipes/coolify-hetzner'))
sys.path.insert(0,str(RECIPE/'scripts'))
import setup as flow
import api as transport
import node
from place import fingerprint, journal_identity, place_lock

CLOUD='synthetic-project-only'
COOLIFY='synthetic-team-only'
TAILSCALE='synthetic-tailnet-only'
OAUTH='synthetic-oauth-only'


class Clock:
    now=0
    def monotonic(self):return self.now
    def sleep(self,seconds):self.now+=seconds


class Services:
    def __init__(self):
        self.clock=Clock();self.calls=[];self.writes=[];self.env=[];self.rules=[]
        self.server=dict(uuid='server-one',name='localhost',ip='host.docker.internal',
                         settings=dict(is_build_server=False,is_usable=True,is_reachable=True))
        self.closed=True;self.started=None;self.never=False;self.ports=['tcp:443']
        self.inventory=[];self.empty_readback=False;self.conflict=False;self.bad_env=False
        self.team_id=0;self.window_closed=False;self.expire_during_claim=False;self.restarts=0;self.claim_active=False;self.restart_failed=False;self.keep_window_closed=False
        self.version='4.7.5'

    def handle(self,method,path,token,body):
        self.calls.append((method,path))
        expected=CLOUD if path.startswith('/hetzner/') else TAILSCALE if path.startswith('/tailscale/') else COOLIFY
        if path not in ('/register','/canary') and token!='Bearer '+expected:
            return 401,dict(message='Unauthorised'),{}
        if path=='/hetzner/v1/firewalls/102':return 200,dict(firewall=dict(rules=self.rules)),{}
        if path=='/register':
            if self.window_closed:return 200,'Setup window closed. You can create the root account only in the first 10 minutes after Coolify starts. To open the window again, run this command on the server, then reload this page: docker restart coolify',{}
            return (302,{},dict(Location='/login')) if self.closed else (200,'<form>Register</form>', {})
        if path=='/api/v1/team':return 200,dict(id=self.team_id),{}
        if path=='/api/v1/version':return 200,self.version,{'Content-Type':'text/html; charset=UTF-8'}
        if path=='/api/v1/servers/server-one':return 200,self.server,{}
        if path=='/api/v1/servers/server-one/destinations':
            return 200,[dict(uuid='destination-one',name='coolify',server_id=0)],{}
        if path.startswith('/tailscale/'):
            if self.never or self.started is None or self.clock.now-self.started<30:return 404,{},{}
            return 200,dict(ports=self.ports),{}
        if path=='/canary':
            return (200,{}, {}) if not self.never and self.started is not None and self.clock.now-self.started>=50 else (503,{}, {})
        # Coolify 4.7.5 ignores page and per_page here and returns every row.
        if method=='GET' and path.split('?')[0] in ('/api/v1/services','/api/v1/projects'):
            return 200,self.inventory,{}
        if method=='POST' and path=='/api/v1/projects':
            # ProjectController::create_project refuses any field but these.
            if not isinstance(body,dict) or set(body)-{'name','description'} or not body.get('name'):
                return 422,dict(message='Validation failed.'),{}
            self.writes.append((method,path,copy.deepcopy(body)))
            return 201,dict(uuid='project-one'),{}
        if method=='POST' and path=='/api/v1/services':
            return self.create_service(method,path,body)
        if path.startswith('/api/v1/services/') and path.endswith('/envs'):
            return self.variables(method,path,body)
        if path.endswith('/start'):
            if method!='POST':return 400,dict(message='Use POST.'),{}
            self.started=self.clock.now;self.writes.append((method,path,body))
            return 200,dict(message='Service starting request queued.'),{}
        raise AssertionError('Unexpected stand-in route: '+method+' '+path)

    COMPOSE_FIELDS={'name','description','project_uuid','environment_name','environment_uuid','server_uuid','destination_uuid',
                    'instant_deploy','docker_compose_raw','connect_to_docker_network','urls','force_domain_override',
                    'is_container_label_escape_enabled','redact_all_env_values_in_logs','tags'}

    def create_service(self,method,path,body):
        # ServicesController::create_service, Compose branch.
        if not isinstance(body,dict) or set(body)-self.COMPOSE_FIELDS:return 422,dict(message='Validation failed.'),{}
        if not body.get('project_uuid') or not body.get('server_uuid') or not body.get('environment_name'):
            return 422,dict(message='Validation failed.'),{}
        raw=body.get('docker_compose_raw')
        try:
            compose=base64.b64decode(raw,validate=True).decode()
            assert base64.b64encode(base64.b64decode(raw)).decode()==raw
        except (ValueError,UnicodeError,TypeError,AssertionError):
            return 422,dict(message='Validation failed.',errors=dict(docker_compose_raw='The docker_compose_raw should be base64 encoded.')),{}
        self.writes.append((method,path,copy.deepcopy(body)))
        # Parsing Compose creates each referenced variable empty, with build
        # time and runtime on, in production.
        if 'TAILSCALE_OAUTH_CLIENT_ID' in compose:
            self.env=[dict(key='TAILSCALE_OAUTH_CLIENT_'+suffix,value='',is_runtime=True,is_buildtime=True,is_preview=False) for suffix in ('ID','SECRET')]
        identity='register-one' if body.get('name','').endswith('-register') else 'docktail-one'
        return 201,dict(uuid=identity,domains=[]),{}

    def variables(self,method,path,body):
        if path!='/api/v1/services/docktail-one/envs':return 404,dict(message='Service not found.'),{}
        if method=='GET':
            if self.bad_env:return 200,{'unexpected':'reply'},{}
            rows=copy.deepcopy(self.env)
            if self.empty_readback:
                for row in rows:row['value']=''
            return 200,rows,{}
        if not isinstance(body,dict) or not body.get('key'):return 422,dict(message='Validation failed.'),{}
        # create_env and update_env_by_uuid look a row up by key alone, apply
        # only these fields and drop every other field unread.
        existing=[row for row in self.env if row['key']==body['key']]
        if self.conflict or (method=='POST' and existing):return 409,dict(message='Environment variable already exists. Use PATCH request to update it.'),{}
        if method=='PATCH' and not existing:return 404,dict(message='Environment variable not found.'),{}
        self.writes.append((method,path,copy.deepcopy(body)))
        applied={key:body[key] for key in ('key','value','is_literal','is_multiline','is_shown_once','comment') if key in body}
        if not existing:
            row=dict(applied,is_runtime=True,is_buildtime=True,is_preview=False);self.env.append(row)
        else:
            row=existing[0];row.update(applied)
        # The reply echoes the stored value to a token that can read it.
        return 201,dict(row,uuid='env-one'),{}


@contextmanager
def standins(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def dispatch(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length']))) if self.headers.get('Content-Length') else None
            status,value,headers=service.handle(self.command,self.path,self.headers.get('Authorization',''),body)
            self.send_response(status)
            for key,val in headers.items():self.send_header(key,val)
            page=self.path=='/register' and isinstance(value,str)
            plain=self.path=='/api/v1/version'
            if not plain:self.send_header('Content-Type','text/html' if page else 'application/json')
            self.end_headers()
            self.wfile.write(('<html><body>'+value+'</body></html>').encode() if page else value.encode() if plain else json.dumps(value).encode())
        do_GET=do_POST=do_PATCH=dispatch
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    assert server.server_port!=3000
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),__import__('check').NoRedirect())
    class Rewrite:
        def open(self,request,**kwargs):
            url=request if isinstance(request,str) else request.full_url
            if url.startswith(base):target=url
            elif url.startswith('https://api.hetzner.cloud/'):target=base+'/hetzner/'+url.split('.cloud/',1)[1]
            elif url.startswith('http://100.64.0.10:8000/'):target=base+'/'+url.split(':8000/',1)[1]
            elif url.startswith('https://api.tailscale.com/'):target=base+'/tailscale/'+url.split('.com/',1)[1]
            elif url=='https://place-canary.fixture.ts.net':
                if service.never or service.started is None or service.clock.now-service.started<50:
                    service.calls.append(('GET','/canary'));raise TimeoutError('Synthetic certificate delay')
                target=base+'/canary'
            else:raise AssertionError('Network escape refused: '+url)
            headers={} if isinstance(request,str) else dict(request.headers)
            data=None if isinstance(request,str) else request.data
            method='GET' if isinstance(request,str) else request.method
            # Registration needs the redirect as an HTTPError for its own check.
            if target==base+'/register':
                if service.closed and not service.window_closed:
                    service.calls.append(('GET','/register'))
                    raise urllib.error.HTTPError(url,302,'Found',{'Location':'/login'},None)
            try:
                return opener.open(urllib.request.Request(target,data=data,headers=headers,method=method),**kwargs)
            except urllib.error.HTTPError as error:
                raise urllib.error.HTTPError(url,error.code,'Provider reply',error.headers,error) from None
    def inputs(gate,label):
        if 'type claimed' in label:
            if service.expire_during_claim:service.window_closed=True
            elif service.claim_active:service.closed=True
            return 'claimed test-place'
        if label.startswith('Hetzner'):return CLOUD
        if label.startswith('Coolify'):return COOLIFY
        if label.startswith('Tailscale API'):return TAILSCALE
        if label.startswith('TAILSCALE_OAUTH'):return OAUTH
        raise AssertionError(label)
    original_run=subprocess.run
    def ssh(command,**kwargs):
        if command[0]=='tailscale':
            assert command==['tailscale','ssh','root@100.64.0.10','sh','-s']
            assert kwargs['input']==node.REOPEN_CLAIM.encode()
            # A restart is a write: its effect must already be consumed.
            receipts=list(Path(service.progress).parent.joinpath('place-attempts').glob('*.json'))
            assert any(json.loads(p.read_text()).get('status')=='uncertain' for p in receipts)
            assert json.loads(Path(service.progress).read_text())['uncertain']=='claim'
            service.restarts+=1;service.claim_active=True;service.window_closed=service.keep_window_closed;service.closed=False
            # Execute the fixed remote shell locally with strict Docker stand-ins.
            # Health is initially starting, then healthy. No real sleep or Docker.
            tools=Path(service.progress).parent/'ssh-tools';tools.mkdir(exist_ok=True)
            log=tools/'calls';log.write_text('')
            docker=tools/'docker'
            docker.write_text("#!/bin/sh\necho \"$1\" >> \"$CLAIM_LOG\"\ncase $1 in\nrestart) exit "+('1' if service.restart_failed else '0')+";;\ninspect) if [ -f \"$CLAIM_READY\" ]; then echo healthy; else touch \"$CLAIM_READY\"; echo starting; fi;;\n*) exit 42;;\nesac\n")
            sleep=tools/'sleep';sleep.write_text('#!/bin/sh\nexit 0\n')
            docker.chmod(0o755);sleep.chmod(0o755)
            ready=tools/'ready';ready.unlink(missing_ok=True)
            result=original_run(['sh','-s'],input=kwargs['input'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                env=dict(os.environ,PATH=str(tools)+':'+os.environ['PATH'],CLAIM_LOG=str(log),CLAIM_READY=str(ready)))
            assert log.read_text().splitlines()==(['restart'] if service.restart_failed else ['restart','inspect','inspect'])
            return result
        return original_run(command,**kwargs)
    @contextmanager
    def terminal(): yield None
    gate=flow.approval_gate()
    try:
        with patch.object(flow,'approval_gate',return_value=gate),patch.object(gate,'terminal',terminal),patch.object(subprocess,'run',side_effect=ssh),patch.object(urllib.request,'build_opener',return_value=Rewrite()),patch.object(flow,'prompt',side_effect=inputs),patch.object(flow,'time',service.clock,create=True):
            yield
    finally:server.shutdown();server.server_close();thread.join()


class Scenario:
    def __init__(self,work,step):
        self.folder=work;work.mkdir(parents=True)
        self.progress=work/'progress.json';self.choice=work/'choice.json'
        choice=dict(schema_version='1.0',choice=dict(host='coolify-hetzner',proven=False,answers={},accepted_shortfalls=[]))
        self.choice.write_text(json.dumps(choice))
        record=json.loads((ROOT/'.agents/tests/fixtures/place/place-record.json').read_text())
        self.journal=work/'place-attempts'
        self.state=dict(root=str(work),record=record,done=flow.STEPS[:flow.STEPS.index(step)],uncertain=None,
            choice_path=str(self.choice),choice_sha256=fingerprint(choice),journal=journal_identity(self.journal),
            config=dict(place=record['place'],secrets=str(work/'absent.env'),canary_name='place-canary',scopes=sorted(flow.SCOPES)),
            project_uuid='project-one',docktail_uuid='docktail-one',register_uuid='register-one',server_uuid='server-one',destination_uuid='destination-one',tailnet_suffix='fixture.ts.net')
        flow.save(self.progress,self.state)
        self.step=step;self.gate=flow.approval_gate()
        self.effect=work/'effect.json';self.approval=work/'approval.json'
        assert self.command('prepare','--step',step,'--effect',self.effect)[0]==0
        self.approve(self.effect,self.approval)

    def command(self,*args):
        out=io.StringIO()
        with patch.object(sys,'argv',['setup',*map(str,args),'--progress',str(self.progress)]),redirect_stdout(out),redirect_stderr(out):
            status=flow.main()
        text=out.getvalue()
        assert all(secret not in text for secret in (CLOUD,COOLIFY,TAILSCALE,OAUTH)), 'A value reached command output'
        return status,text

    def approve(self,effect,path):
        value=json.loads(effect.read_text())
        path.write_text(json.dumps(dict(effect_sha256=self.gate.effect_sha(value),effect=value['effect'],words='Synthetic fixture approval',approved_at='2026-11-17T12:00:00Z',method='foreground-terminal')))

    def run(self):return self.command('run','--step',self.step,'--effect',self.effect,'--approval',self.approval)
    def read(self):return json.loads(self.progress.read_text())
    def receipt(self):return self.journal/(fingerprint(json.loads(self.effect.read_text()))+'.json')
    def recovery(self,abandon=False):
        self.reffect=self.folder/'recovery.json';self.reapproval=self.folder/'recovery-approval.json'
        self.rargs=['--step',self.step,'--attempt-effect',self.effect,'--effect',self.reffect]+(['--abandon'] if abandon else [])
        assert self.command('prepare-recovery',*self.rargs)[0]==0
        self.approve(self.reffect,self.reapproval)
    def recover(self):return self.command('recover',*self.rargs,'--approval',self.reapproval)


def claim(work):
    svc=Services();case=Scenario(work,'claim');svc.progress=case.progress;svc.closed=False
    with standins(svc):
        # Exercise the actual transport: the service refuses both missing and wrong tokens.
        for token in ('','wrong'):
            try:transport.API(case.state['record'],token).firewall_rules(102)
            except urllib.error.HTTPError as error:assert error.code==401
            else:raise AssertionError('Hetzner accepted an invalid bearer')
        svc.window_closed=True # The first container start was hours ago.
        status,text=case.run();assert status==0,text
        assert svc.restarts==1 and 'ten minutes' in text and 'Skip setup' in text
        assert 'Configure 2FA' in text and 'API and MCP > API access' in text
        assert 'Read sensitive data, never Root or Delete' in text
    assert case.read()['done']==['claim'] and json.loads(case.receipt().read_text())['status']=='completed'



def closed_window(work):
    svc=Services();case=Scenario(work,'claim');svc.progress=case.progress;svc.closed=False
    assert 'Restart the coolify container over Tailscale SSH' in json.loads(case.effect.read_text())['effect']
    with standins(svc):
        svc.expire_during_claim=True
        status,text=case.run()
        assert status!=0 and 'Coolify setup window closed.' in text,text
        assert case.read()['uncertain'] is None and case.read()['done']==[]
        assert json.loads(case.receipt().read_text())['status']=='not-claimed'
        assert svc.restarts==1
        assert case.run()[0]!=0 and svc.restarts==1 # Consumed approval cannot restart.
        fresh=work/'fresh.json'
        assert case.command('prepare','--step','claim','--effect',fresh)[0]==0
        case.effect=fresh
        assert case.run()[0]!=0 and svc.restarts==1 # Old approval mismatches.
        case.approve(fresh,case.approval);svc.expire_during_claim=False
        assert case.run()[0]==0 and svc.restarts==2
        assert case.read()['done']==['claim']



def restart_boundaries(work):
    for mode in ('closed','failed','approval'):
        svc=Services();case=Scenario(work/mode,'claim');svc.progress=case.progress;svc.closed=False
        svc.restart_failed=mode=='failed';svc.keep_window_closed=mode=='closed'
        if mode=='approval':case.approval.write_text('{}')
        with standins(svc):
            status,text=case.run()
            assert status!=0 and ':8000/register now' not in text,text
            if mode=='approval':
                assert svc.restarts==0 and not case.receipt().exists() and case.read()['uncertain'] is None
            elif mode=='closed':
                assert 'Coolify setup window closed.' in text
                assert case.read()['uncertain'] is None and json.loads(case.receipt().read_text())['status']=='not-claimed'
            else:
                assert 'Coolify did not become healthy' in text
                assert case.read()['uncertain']=='claim' and json.loads(case.receipt().read_text())['status']=='uncertain'



def http_status(work):
    svc=Services();case=Scenario(work,'claim');svc.progress=case.progress;svc.closed=False
    with standins(svc),patch.object(flow,'prompt',return_value='synthetic-private-marker'):
        status,text=case.run()
    assert status!=0 and 'Hetzner answered 401.' in text,text
    assert 'synthetic-private-marker' not in text
    assert not case.receipt().exists() and svc.restarts==0 and case.read()['uncertain'] is None


def discover(work):
    svc=Services();case=Scenario(work,'project')
    with standins(svc):
        for ip,name in [('192.0.2.20','localhost'),('host.docker.internal','remote')]:
            svc.server.update(ip=ip,name=name)
            before=case.progress.read_bytes()
            status,text=case.command('discover','--server-uuid','server-one','--destination-uuid','destination-one')
            assert status!=0 and case.progress.read_bytes()==before
        for ip in ('host.docker.internal','127.0.0.1','localhost'):
            svc.server.update(ip=ip,name='localhost')
            status,text=case.command('discover','--server-uuid','server-one','--destination-uuid','destination-one')
            assert status==0,text


def oauth(work,step):
    svc=Services();case=Scenario(work,step)
    with standins(svc):
        # Compose parsing creates both empty production keys with build time on.
        client=transport.API(case.state['record'],'',COOLIFY)
        assert client.create_service(flow.effect_for(dict(case.state,done=flow.STEPS[:2]),'docktail')['arguments'])=='docktail-one'
        assert len(svc.env)==2 and all(row['value']=='' and row['is_buildtime'] for row in svc.env)
        status,text=case.run();assert status==0,text
        writes=[(method,body) for method,path,body in svc.writes if path.endswith('/envs')]
        assert len(writes)==1 and writes[0][0]=='PATCH'
        # Only the fields the route reads reach Coolify; no ignored flag is sent.
        body=writes[0][1];assert set(body)=={'key','value'} and body['value']==OAUTH
        assert case.read()['uncertain'] is None
        # Coolify kept build time on; the image-only definition makes that acceptable.
        assert client.service_env_state('docktail-one',body['key'])==[dict(is_set=True,is_buildtime=True,is_runtime=True,is_preview=False)]
        # A second create must conflict, exactly as Coolify does.
        before=len(svc.calls)
        try:client.set_service_variable('POST','docktail-one',body['key'],'synthetic-other')
        except urllib.error.HTTPError as error:assert error.code==409
        else:raise AssertionError('The duplicate-create stand-in was permissive')
        assert ('POST','/api/v1/services/docktail-one/envs') in svc.calls[before:]


def record(work):
    svc=Services();case=Scenario(work,'start-register')
    with standins(svc):
        assert case.run()[0]==0 and svc.clock.now==0
        case.step='record';case.effect=work/'record.json';case.approval=work/'record-approval.json'
        assert case.command('prepare','--step','record','--effect',case.effect)[0]==0
        case.approve(case.effect,case.approval)
        status,text=case.run();assert status==0,text
        assert svc.clock.now>=50 and 'Waiting' in text
        assert case.read()['done']==flow.STEPS
        assert json.loads(case.choice.read_text())['infrastructure']['plumbing']['canary_uuid']=='register-one'


def failed_record(work):
    for mode in ('never','registration','ports','invalid-record','changed-choice'):
        svc=Services();svc.started=0;svc.clock.now=60
        case=Scenario(work/mode,'record')
        if mode=='never':svc.never=True
        if mode=='registration':svc.closed=False
        if mode=='ports':svc.ports=['tcp:80']
        if mode=='invalid-record':
            state=case.read();state['project_uuid']=123;flow.save(case.progress,state)
            case.effect.unlink();assert case.command('prepare','--step','record','--effect',case.effect)[0]==0
            case.approve(case.effect,case.approval)
        if mode=='changed-choice':case.choice.write_text('{}')
        before=case.progress.read_bytes();choice=case.choice.read_bytes()
        with standins(svc):
            status,text=case.run();assert status!=0
        assert case.progress.read_bytes()==before and case.choice.read_bytes()==choice and not case.receipt().exists(),mode
        if mode=='never':assert 'timed out' in text and svc.clock.now<=360


def recover_claim(work):
    svc=Services();case=Scenario(work,'claim');svc.progress=case.progress;svc.closed=False
    with standins(svc):
        with patch.object(flow,'reopen_claim',side_effect=OSError('Synthetic restart interruption')):
            assert case.run()[0]!=0 and case.read()['uncertain']=='claim'
        svc.rules=[dict(direction='in',protocol='tcp',port='22',source_ips=['0.0.0.0/0'])]
        case.recovery()
        before=case.progress.read_bytes();receipt=case.receipt().read_bytes()
        assert case.recover()[0]!=0 and case.progress.read_bytes()==before and case.receipt().read_bytes()==receipt
        svc.rules=[];svc.closed=False
        assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        svc.closed=True
        with patch.object(flow,'prompt',side_effect=lambda g,label: 'wrong' if 'type claimed' in label else CLOUD if label.startswith('Hetzner') else COOLIFY):
            assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        with patch.object(flow,'prompt',side_effect=lambda g,label: 'claimed test-place' if 'type claimed' in label else CLOUD if label.startswith('Hetzner') else 'wrong'):
            assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        # Recovery approval, lock and journal checks must all precede local writes.
        approved=case.reapproval.read_bytes();case.reapproval.write_text('{}')
        assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        case.reapproval.write_bytes(approved)
        # Every excluded digest is still constrained to a complete SHA-256.
        recovery=json.loads(case.reffect.read_text())
        for key in ('receipt_sha256','attempt_sha256'):
            bad=dict(recovery);bad[key]='synthetic-private-value'
            try:case.gate.effect_sha(bad)
            except ValueError:pass
            else:raise AssertionError('Recovery admitted a non-digest in '+key)
        changed=dict(recovery,receipt_sha256='a'*64);case.reffect.write_text(json.dumps(changed))
        assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        case.reffect.write_text(json.dumps(recovery))
        saved_receipt=json.loads(receipt);saved_receipt['extra']='changed'
        flow.save(case.receipt(),saved_receipt)
        assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        case.receipt().write_bytes(receipt)
        with place_lock(case.state['record']):assert case.recover()[0]!=0
        parked=work/'parked';case.journal.rename(parked);case.journal.mkdir()
        assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        case.journal.rmdir();parked.rename(case.journal)
        assert case.recover()[0]==0
        assert case.read()['done']==['claim'] and case.read()['uncertain'] is None
        assert json.loads(case.receipt().read_text())['status']=='completed' and not svc.writes
        assert case.recover()[0]!=0


def abandon(work):
    svc=Services();case=Scenario(work,'project')
    with standins(svc):
        svc.closed=False
        status,text=case.run();assert status!=0
        assert case.receipt().exists(),text
        assert json.loads(case.receipt().read_text())['write_state']=='not-sent'
        case.recovery(True);before=case.progress.read_bytes()
        with place_lock(case.state['record']):assert case.recover()[0]!=0
        assert case.progress.read_bytes()==before
        assert case.recover()[0]==0
        saved=case.read();assert saved['uncertain'] is None and len(saved['abandoned_attempts'])==1
        assert json.loads(case.receipt().read_text())['status']=='not-written'
        # Restoring progress alone cannot revive a spent approval.
        case.progress.write_bytes(before);svc.closed=True
        assert case.run()[0]!=0 and not svc.writes
        flow.save(case.progress,saved)
        svc.closed=True;assert case.run()[0]!=0 and not svc.writes
        fresh=work/'fresh.json';assert case.command('prepare','--step','project','--effect',fresh)[0]==0
        assert fingerprint(json.loads(fresh.read_text()))!=fingerprint(json.loads(case.effect.read_text()))
        case.effect=fresh
        assert case.run()[0]!=0 and not svc.writes # Old approval cannot match the new checksum.
        case.approve(fresh,case.approval)
        assert case.run()[0]==0 and len(svc.writes)==1
        assert case.run()[0]!=0 and len(svc.writes)==1
    # Without dispatch evidence, only an absence read in the original team
    # can justify abandoning a named creation.
    svc=Services();case=Scenario(work/'historical','register')
    with standins(svc):
        svc.closed=False;assert case.run()[0]!=0
        receipt=json.loads(case.receipt().read_text());receipt.pop('write_state',None);flow.save(case.receipt(),receipt)
        case.recovery(True)
        svc.team_id=1
        before=case.progress.read_bytes()
        assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        svc.team_id=0
        svc.inventory=[dict(uuid='existing',name='test-place-register')]
        assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        svc.inventory={'data':[]}
        assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        # Coolify 4.7.5 ignores page and per_page, so any listed row repeats on
        # the next page. The inventory cannot prove completeness and the
        # attempt stays uncertain, even when the named service is absent.
        svc.inventory=[dict(uuid='other',name='test-place-docktail')]
        assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        svc.inventory=[];assert case.recover()[0]==0
    # A crash before the uncertainty save still consumes the original effect.
    svc=Services();case=Scenario(work/'crash','project')
    original_save=flow.save
    def crash(path,value):
        if Path(path).resolve()==case.progress.resolve() and value.get('uncertain')=='project':raise OSError('Synthetic progress crash')
        return original_save(path,value)
    with standins(svc),patch.object(flow,'save',side_effect=crash):
        assert case.run()[0]!=0 and case.read()['uncertain'] is None and not svc.writes
    with standins(svc):
        assert case.run()[0]!=0 and not svc.writes
        case.recovery(True);assert case.recover()[0]==0


def oauth_edges(work):
    for mode in ('absent','preview','empty','conflict','bad-list'):
        svc=Services();case=Scenario(work/mode,'oauth-id')
        if mode=='preview':svc.env=[dict(key='TAILSCALE_OAUTH_CLIENT_ID',value='preview',is_preview=True,is_runtime=True,is_buildtime=True)]
        if mode=='empty':svc.empty_readback=True
        if mode=='conflict':svc.conflict=True
        if mode=='bad-list':svc.bad_env=True
        with standins(svc):
            status,text=case.run()
            if mode=='absent':
                assert status==0,text
                assert [method for method,path,body in svc.writes]==['POST']
            else:
                assert status!=0 and case.read()['uncertain']=='oauth-id'
                assert json.loads(case.receipt().read_text())['status']=='uncertain'
                # Coolify 4.7.5 finds a service variable by key alone, so a
                # preview row with the key would take the write. Nothing is sent.
                if mode=='preview':assert 'scope is ambiguous' in text and not svc.writes and svc.env[0]['value']=='preview',text
                case.recovery(True)
                if mode in ('bad-list','preview'):assert case.recover()[0]==0 and not svc.writes
                else:assert case.recover()[0]!=0


ENV_ROWS=json.loads((ROOT/'.agents/tests/fixtures/place/coolify-service-envs.json').read_text())['rows']


def oauth_readback(work):
    # The recorded 4.7.5 row shape passes only for the kit's image-only definition.
    svc=Services();svc.env=copy.deepcopy(ENV_ROWS)
    build=flow.DOCKTAIL.replace('    image: ghcr.io/marvinvr/docktail:1.8.6\n','    image: ghcr.io/marvinvr/docktail:1.8.6\n    build: .\n')
    assert build!=flow.DOCKTAIL
    with standins(svc):
        api=transport.API(json.loads((ROOT/'.agents/tests/fixtures/place/place-record.json').read_text()),'',COOLIFY)
        def shortfall(key,compose=flow.DOCKTAIL):
            rows=api.service_env_state('docktail-one',key)
            assert all(set(row)=={'is_set','is_runtime','is_buildtime','is_preview'} for row in rows)
            reason=flow.oauth_shortfall(rows,key,compose)
            assert reason is None or OAUTH not in reason
            return reason
        assert shortfall('TAILSCALE_OAUTH_CLIENT_ID') is None
        assert 'build time on' in shortfall('TAILSCALE_OAUTH_CLIENT_ID',build)
        assert 'unset' in shortfall('TAILSCALE_OAUTH_CLIENT_SECRET')
        svc.env[0]['is_runtime']=False
        assert 'runtime off' in shortfall('TAILSCALE_OAUTH_CLIENT_ID')
        svc.env[0].update(is_runtime=True,is_preview=True)
        assert 'production rows' in shortfall('TAILSCALE_OAUTH_CLIENT_ID')
        svc.env.append(dict(ENV_ROWS[0]));svc.env.append(dict(ENV_ROWS[0]))
        assert 'production rows' in shortfall('TAILSCALE_OAUTH_CLIENT_ID')
        svc.env=[dict(ENV_ROWS[0],is_buildtime=False)]
        assert shortfall('TAILSCALE_OAUTH_CLIENT_ID',build) is None
    # A definition the parser cannot read keeps the stricter rule.
    for compose in ('',flow.DOCKTAIL.replace('services:','version: "3"\nservices:'),flow.DOCKTAIL.replace('  docktail:','  docktail: &base'),
                    flow.DOCKTAIL+'  builder:\n    build: .\n',flow.DOCKTAIL.replace('    image:','    <<: *base\n    image:')):
        assert flow.build_time_applies(compose),compose
    assert not flow.build_time_applies(flow.DOCKTAIL)


def recover_oauth(work):
    # A reviewed recovery only reads, and completes only on a passing read.
    for step in ('oauth-id','oauth-secret'):
        svc=Services();case=Scenario(work/step,step)
        with standins(svc):
            svc.env=[dict(row,value='') for row in ENV_ROWS];svc.empty_readback=True
            status,text=case.run();assert status!=0 and 'unset' in text,text
            assert case.read()['uncertain']==step and json.loads(case.receipt().read_text())['status']=='uncertain'
            # Only abandonment existed before; abandonment still needs proof of no write.
            case.recovery(True);assert case.recover()[0]!=0
            case.reffect.unlink();case.reapproval.unlink();case.recovery()
            recovery=json.loads(case.reffect.read_text())
            assert recovery['action']=='place-recover-oauth' and recovery['step']==step and 'changes nothing' in recovery['effect']
            path=case.receipt();before=case.progress.read_bytes();receipt=path.read_bytes();writes=len(svc.writes);calls=len(svc.calls)
            def unchanged():return case.progress.read_bytes()==before and path.read_bytes()==receipt and len(svc.writes)==writes
            status,text=case.recover();assert status!=0 and 'unset' in text and 'stays uncertain' in text and unchanged(),text
            svc.empty_readback=False;svc.env[0 if step=='oauth-id' else 1]['is_runtime']=False
            status,text=case.recover();assert status!=0 and 'runtime off' in text and unchanged(),text
            svc.env[0 if step=='oauth-id' else 1]['is_runtime']=True
            # The same check applies: a definition with a build step needs build time off.
            with patch.object(flow.oauth_shortfall,'__defaults__',(flow.DOCKTAIL+'  builder:\n    build: .\n',)):
                status,text=case.recover();assert status!=0 and 'build time on' in text and unchanged(),text
            svc.team_id=1
            status,text=case.recover();assert status!=0 and 'same Coolify team' in text and unchanged(),text
            svc.team_id=0
            approved=case.reapproval.read_bytes();case.reapproval.write_text('{}')
            assert case.recover()[0]!=0 and unchanged()
            case.reapproval.write_bytes(approved)
            original=case.effect.read_bytes();changed=json.loads(original);changed['arguments']['key']='OTHER'
            case.effect.write_text(json.dumps(changed));assert case.recover()[0]!=0 and unchanged()
            case.effect.write_bytes(original)
            with place_lock(case.state['record']):assert case.recover()[0]!=0 and unchanged()
            status,text=case.recover();assert status==0,text
            assert case.read()['done']==flow.STEPS[:flow.STEPS.index(step)+1] and case.read()['uncertain'] is None
            assert json.loads(path.read_text())['status']=='completed'
            assert len(svc.writes)==writes and all(method=='GET' for method,path in svc.calls[calls:])
            assert case.recover()[0]!=0 and len(svc.writes)==writes
    # Other stages keep abandonment as their only recovery.
    svc=Services();case=Scenario(work/'project','project')
    with standins(svc):
        svc.closed=False;assert case.run()[0]!=0
        status,text=case.command('prepare-recovery','--step','project','--attempt-effect',case.effect,'--effect',work/'project-recovery.json')
        assert status!=0 and not (work/'project-recovery.json').exists()


def rest_boundaries(work):
    # The transport sends only fields the 4.7.5 route reads, encodes Compose
    # and returns an identity or nothing, never a stored value.
    svc=Services();case=Scenario(work,'oauth-id')
    key='TAILSCALE_OAUTH_CLIENT_ID'
    with standins(svc):
        client=transport.API(case.state['record'],'',COOLIFY)
        assert client.coolify_version()=='4.7.5'
        assert client.create_project('test-place-infrastructure')=='project-one'
        arguments=flow.effect_for(dict(case.state,done=flow.STEPS[:2]),'docktail')['arguments']
        assert client.create_service(arguments)=='docktail-one'
        posted=svc.writes[-1][2]
        assert set(posted)==set(arguments) and posted['instant_deploy'] is False
        assert base64.b64decode(posted['docker_compose_raw']).decode()==flow.DOCKTAIL
        # Raw Compose is refused by the route, so the encoding is required.
        try:client.request('POST',client.coolify_url('services'),COOLIFY,arguments)
        except urllib.error.HTTPError as error:assert error.code==422
        else:raise AssertionError('The stand-in accepted raw Compose')
        assert client.set_service_variable('PATCH','docktail-one',key,OAUTH) is None
        assert svc.env[0]['value']==OAUTH
        calls=len(svc.calls)
        for method,route,body,uuid in [('PATCH','services/{uuid}/envs',dict(key=key,value='x',is_buildtime=False),'docktail-one'),
                                       ('POST','services/{uuid}/envs',dict(key=key,value='x',is_runtime=True),'docktail-one'),
                                       ('PATCH','services/{uuid}/envs',dict(key=key,value='x',is_preview=False),'docktail-one'),
                                       ('POST','projects',dict(name='x',environment_name='production'),None),
                                       ('DELETE','services/{uuid}',None,'docktail-one'),
                                       ('POST','services/{uuid}/start',None,None)]:
            try:client.coolify_write(method,route,body,uuid)
            except ValueError:pass
            else:raise AssertionError('The transport sent a refused request: '+method+' '+route)
        assert len(svc.calls)==calls
        # Removing the field check lets an ignored flag reach Coolify, which
        # accepts the request and keeps build time on.
        source=(RECIPE/'scripts/api.py').read_text();old='set(body) <= fields'
        assert old in source
        mutated=work/'mutated-api.py';mutated.write_text(source.replace(old,'True',1))
        import importlib.util
        spec=importlib.util.spec_from_file_location('mutated_api',mutated);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.API(case.state['record'],'',COOLIFY).coolify_write('PATCH','services/{uuid}/envs',dict(key=key,value=OAUTH,is_buildtime=False),'docktail-one')
        assert svc.writes[-1][2].get('is_buildtime') is False and svc.env[0]['is_buildtime'] is True
        print('Protection removal detected: ignored deployment flag refusal')


def older_effects(work):
    # Effects an older kit prepared for the MCP package never run, but their
    # uncertain attempts still reach the same recovery reads and proofs.
    for step in ('project','oauth-id'):
        svc=Services();case=Scenario(work/step,step)
        legacy=flow.effect_for(case.read(),step,legacy=True)
        assert 'tool' in legacy and 'request' not in legacy and legacy['effect']==json.loads(case.effect.read_text())['effect']
        case.effect.write_text(json.dumps(legacy));case.approve(case.effect,case.approval)
        with standins(svc):
            status,text=case.run()
            assert status!=0 and 'older kit' in text and not svc.writes,text
            assert not case.receipt().exists() and case.read()['uncertain'] is None
            # The older kit recorded its attempt, then stopped without a result.
            from place import start_attempt
            start_attempt(legacy,case.approval,case.journal,coolify_team_id=0)
            state=case.read();state['uncertain']=step;flow.save(case.progress,state)
            if step=='project':
                case.recovery(True)
                svc.inventory=[dict(uuid='existing',name='test-place-infrastructure')]
                assert case.recover()[0]!=0 and case.read()['uncertain']==step
                svc.inventory=[]
            else:
                svc.env=copy.deepcopy(ENV_ROWS);svc.env[0]['is_runtime']=False
                case.recovery()
                status,text=case.recover();assert status!=0 and 'runtime off' in text,text
                svc.env[0]['is_runtime']=True
            status,text=case.recover();assert status==0,text
            assert case.read()['uncertain'] is None and not svc.writes
            assert json.loads(case.receipt().read_text())['status']==('not-written' if step=='project' else 'completed')


def version(work):
    # Writes follow the pinned version's routes; any other version is refused
    # before an attempt is recorded.
    svc=Services();svc.version='4.7.6';case=Scenario(work,'project')
    with standins(svc):
        status,text=case.run()
        assert status!=0 and 'pinned' in text and not svc.writes,text
        assert not case.receipt().exists() and case.read()['uncertain'] is None
        svc.version='4.7.5'
        assert case.run()[0]==0 and len(svc.writes)==1


def main():
    cases={'rest-boundaries':rest_boundaries,'older-effects':older_effects,'version':version,'http-status':http_status,'restart-boundaries':restart_boundaries,'closed-window':closed_window,'claim':claim,'discover':discover,'oauth-id':lambda w:oauth(w,'oauth-id'),
           'oauth-secret':lambda w:oauth(w,'oauth-secret'),'record':record,'record-failures':failed_record,
           'recover-claim':recover_claim,'abandon':abandon,'oauth-edges':oauth_edges,'oauth-readback':oauth_readback,'recover-oauth':recover_oauth}
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=list(cases)+['all'],default='all');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='place-stage-checks-') as tmp:
        for name,run in cases.items():
            if args.case not in ('all',name):continue
            run(Path(tmp)/name);print('Passed: '+name)
    return 0


if __name__=='__main__':sys.exit(main())
