"""Strict loopback services through the setup command, with synthetic approvals."""
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
import mcp as protocol
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
        if path=='/api/v1/version':return 200,'4.7.5',{}
        if path=='/api/v1/servers/server-one':return 200,self.server,{}
        if path=='/api/v1/servers/server-one/destinations':
            return 200,[dict(uuid='destination-one',name='coolify',server_id=0)],{}
        if path.startswith('/tailscale/'):
            if self.never or self.started is None or self.clock.now-self.started<30:return 404,{},{}
            return 200,dict(ports=self.ports),{}
        if path=='/canary':
            return (200,{}, {}) if not self.never and self.started is not None and self.clock.now-self.started>=50 else (503,{}, {})
        if path in ('/api/v1/services','/api/v1/projects'):
            if method=='GET':return 200,self.inventory,{}
            self.writes.append((method,path,copy.deepcopy(body)))
            compose=body.get('docker_compose_raw','')
            if 'TAILSCALE_OAUTH_CLIENT_ID' not in compose:
                try:compose=base64.b64decode(compose).decode()
                except (ValueError,UnicodeError):pass
            if path.endswith('/services') and 'TAILSCALE_OAUTH_CLIENT_ID' in compose:
                self.env=[dict(key='TAILSCALE_OAUTH_CLIENT_'+suffix,value='',is_runtime=True,is_buildtime=True,is_preview=False) for suffix in ('ID','SECRET')]
            return 200,dict(uuid='docktail-one' if path.endswith('/services') else 'project-one'),{}
        if path=='/api/v1/services/docktail-one/envs':
            if method=='GET':
                rows=copy.deepcopy(self.env)
                if self.empty_readback:
                    for row in rows:row['value']=''
                return 200,rows,{}
            existing=[row for row in self.env if row['key']==body['key'] and row['is_preview']==body['is_preview']]
            if self.conflict or (method=='POST' and existing):return 409,dict(message='Environment variable already exists. Use PATCH request to update it.'),{}
            if method=='PATCH' and not existing:return 404,{},{}
            self.writes.append((method,path,copy.deepcopy(body)))
            if not existing:self.env.append(copy.deepcopy(body))
            else:existing[0].update(body)
            return 200,dict(uuid='env-one'),{}
        if path.endswith('/start'):
            self.started=self.clock.now;self.writes.append((method,path,body))
            return 200,dict(message='Service starting request queued.'),{}
        raise AssertionError('Unexpected stand-in route: '+method+' '+path)


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
            self.send_header('Content-Type','text/html' if page else 'application/json')
            self.end_headers()
            self.wfile.write(('<html><body>'+value+'</body></html>').encode() if page else json.dumps(value).encode())
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
    class MCP:
        def __init__(self,*args):self.api=transport.API({},'',COOLIFY)
        def close(self):pass
        def call(self,tool,args):
            if tool=='env_vars':
                path='/api/v1/services/'+args['uuid']+'/envs'
                if args['action']=='list':
                    assert args.get('reveal') is not True
                    rows=self.api.request('GET',base+path,COOLIFY)
                    if service.bad_env:return {'unexpected':'reply'}
                    return [dict(row,value='***') for row in rows if row['key']==args['key']]
                assert args['action'] in ('create','update')
                body={key:args[key] for key in ('key','value','is_buildtime','is_runtime','is_preview')}
                return self.api.request('POST' if args['action']=='create' else 'PATCH',base+path,COOLIFY,body)
            if tool in ('service','projects'):
                return self.api.request('POST',base+'/api/v1/'+('services' if tool=='service' else tool),COOLIFY,args)
            if tool=='control':return self.api.request('GET',base+'/api/v1/services/'+args['uuid']+'/start',COOLIFY)
            raise AssertionError(tool)
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
    original_spawn=subprocess.Popen
    def spawn(command,**kwargs):
        if command[0]=='node':
            kwargs['env']['COOLIFY_BASE_URL']=base
        return original_spawn(command,**kwargs)
    try:
        with patch.object(subprocess,'run',side_effect=ssh),patch.object(urllib.request,'build_opener',return_value=Rewrite()),patch.object(flow,'MCP',protocol.MCP if os.environ.get('PLACE_STAGE_MCP_PACKAGE') else MCP),patch.object(subprocess,'Popen',side_effect=spawn),patch.object(flow,'prompt',side_effect=inputs),patch.object(flow,'time',service.clock,create=True):
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

    def run(self):return self.command('run','--step',self.step,'--effect',self.effect,'--approval',self.approval,'--mcp-package',os.environ.get('PLACE_STAGE_MCP_PACKAGE',self.folder/'package.json'))
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
        client=flow.MCP(os.environ.get('PLACE_STAGE_MCP_PACKAGE'),'100.64.0.10',COOLIFY,sorted(flow.SCOPES))
        client.call('service',dict(action='create',name='test-place-docktail',server_uuid='server-one',project_uuid='project-one',destination_uuid='destination-one',environment_name='production',instant_deploy=False,docker_compose_raw=flow.DOCKTAIL))
        assert len(svc.env)==2 and all(row['value']=='' and row['is_buildtime'] for row in svc.env)
        status,text=case.run();assert status==0,text
        writes=[(method,body) for method,path,body in svc.writes if path.endswith('/envs')]
        assert len(writes)==1 and writes[0][0]=='PATCH'
        body=writes[0][1];assert body['is_buildtime'] is False and body['is_runtime'] is True and body['is_preview'] is False
        assert case.read()['uncertain'] is None
        assert transport.API(case.state['record'],'',COOLIFY).service_env_state('docktail-one',body['key'])==[dict(is_set=True,is_buildtime=False,is_runtime=True,is_preview=False)]
        # A second create must conflict, exactly as Coolify does.
        before=len(svc.calls)
        try:client.call('env_vars',dict(body,resource='service',action='create',uuid='docktail-one'))
        except urllib.error.HTTPError as error:assert error.code==409
        except ValueError:
            assert os.environ.get('PLACE_STAGE_MCP_PACKAGE') # The real MCP withholds HTTP diagnostics.
        else:raise AssertionError('The duplicate-create stand-in was permissive')
        finally:client.close()
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
        svc.inventory=[dict(name='test-place-register')]
        assert case.recover()[0]!=0 and case.progress.read_bytes()==before
        svc.inventory={'data':[]}
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
            if mode in ('absent','preview'):
                assert status==0,text
                assert [method for method,path,body in svc.writes]==['POST']
                if mode=='preview':assert svc.env[0]['value']=='preview' and svc.env[0]['is_buildtime']
            else:
                assert status!=0 and case.read()['uncertain']=='oauth-id'
                assert json.loads(case.receipt().read_text())['status']=='uncertain'
                case.recovery(True)
                if mode=='bad-list':assert case.recover()[0]==0 and not svc.writes
                else:assert case.recover()[0]!=0


def main():
    cases={'http-status':http_status,'restart-boundaries':restart_boundaries,'closed-window':closed_window,'claim':claim,'discover':discover,'oauth-id':lambda w:oauth(w,'oauth-id'),
           'oauth-secret':lambda w:oauth(w,'oauth-secret'),'record':record,'record-failures':failed_record,
           'recover-claim':recover_claim,'abandon':abandon,'oauth-edges':oauth_edges}
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=list(cases)+['all'],default='all');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='place-stage-checks-') as tmp:
        for name,run in cases.items():
            if args.case not in ('all',name):continue
            run(Path(tmp)/name);print('Passed: '+name)
    return 0


if __name__=='__main__':sys.exit(main())
