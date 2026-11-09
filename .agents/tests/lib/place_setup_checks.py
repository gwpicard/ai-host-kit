"""Local setup outcomes and independent protection removals."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch


def exercise(work, checks):
    from place_checks import RECIPE, FIXTURE, load, refused, StandIn
    sys.path.insert(0,str(RECIPE/'scripts'))
    try:
        import setup as flow
        import node
        import mcp
        gate=checks.load(); reader=flow.load_reader()
        record=json.loads((FIXTURE/'place-record.json').read_text())
        facts=dict(status=dict(BackendState='Running',Self=dict(HostName='test-place',TailscaleIPs=['100.64.0.10'],Tags=['tag:server'],KeyExpiry=None)),prefs=dict(RunSSH=True),key_file_gone=True,instance_id='101',cloud_init={'v1':{'errors':[]}})
        assert all(status=='passed' for _,status in node.bootstrap(record,lambda address:facts))
        bads=[('key_file_gone',False),('instance_id','999'),('prefs',{'RunSSH':False}),('cloud_init',{'v1':{'errors':['failed']}})]
        for field,value in bads:
            bad=copy.deepcopy(facts);bad[field]=value
            refused(lambda:node.bootstrap(record,lambda address:bad))
        for field,value in [('Tags',[]),('KeyExpiry','2026-12-01'),('HostName','stale'),('TailscaleIPs',['100.64.0.99'])]:
            bad=copy.deepcopy(facts);bad['status']['Self'][field]=value
            refused(lambda:node.bootstrap(record,lambda address:bad))
        source=(RECIPE/'scripts/node.py').read_text()
        for old in ["facts.get('key_file_gone') is True", "str(facts.get('instance_id')) == str(record['infrastructure']['server_id'])", "prefs.get('RunSSH') is True", "facts.get('cloud_init', {}).get('v1', {}).get('errors') == []", "'tag:server' in node.get('Tags', [])", "'Self' in status and node.get('KeyExpiry') is None"]:
            path=work/'mutated-node.py';path.write_text(source.replace(old,'True',1)); mutated=load(path)
            # Each removed check must allow its matching bad fixture, unlike the original.
            detected=False
            for field,value in bads:
                bad=copy.deepcopy(facts);bad[field]=value
                if all(status=='passed' for _,status in mutated.node_rows(record,bad)): detected=True
            for field,value in [('Tags',[]),('KeyExpiry','2026-12-01')]:
                bad=copy.deepcopy(facts);bad['status']['Self'][field]=value
                if all(status=='passed' for _,status in mutated.node_rows(record,bad)): detected=True
            assert detected,old
            print('Protection removal detected: node '+old.split('(')[0])
        config=dict(place=record['place'],encrypted_state=record['encrypted_state'],
                    backend=json.loads((RECIPE/'tofu/backend.example.json').read_text()),
                    inputs=dict(place_name='test-place',location='fsn1',server_type='cx23',ssh_public_key='ssh-ed25519 c3ludGhldGlj test',
                                tailnet_key_settings=dict(reusable=False,ephemeral=False,preauthorised=True,tags=['tag:server'],expiry_seconds=3600,shortest_available=True)),
                    scopes=sorted(flow.SCOPES),canary_name='place-canary')
        choice=dict(schema_version='1.0',choice=dict(host='coolify-hetzner',proven=False,answers={},accepted_shortfalls=[]))
        path=work/'choice.json';path.write_text(json.dumps(choice))
        folder=work/'setup-root';progress=work/'setup-progress.json'
        flow.prepare_root(config,path,folder,progress,reader,gate)
        root=json.loads((folder/'main.tf.json').read_text())
        assert root['variable']['hcloud_token']['ephemeral'] and root['module']['place']['source']=='./module'
        assert 'tskey-auth' not in (folder/'main.tf.json').read_text()
        for key,value in [('reusable',True),('ephemeral',True),('preauthorised',False),('tags',[]),('shortest_available',False)]:
            bad=copy.deepcopy(config);bad['inputs']['tailnet_key_settings'][key]=value
            refused(lambda:flow.prepare_root(bad,path,work/'bad-root',work/'bad-progress',reader,gate))
        state=json.loads(progress.read_text());state.update(record=record,server_uuid='server-one',destination_uuid='network-one')
        api=StandIn();api.firewall_rules=lambda identity:[]
        fake=SimpleNamespace(call=lambda tool,args:dict(uuid='created-'+tool))
        confirm=lambda name:'claimed '+name
        definition=lambda name:dict(ports=['tcp:443'])
        def approve(effect):
            value=dict(effect_sha256=gate.effect_sha(effect),effect=effect['effect'],words='Synthetic fixture approval',approved_at='2026-11-09T12:00:00Z',method='foreground-terminal')
            p=work/'stage-approval.json';p.write_text(json.dumps(value));return p
        stage_source=(RECIPE/'scripts/setup.py').read_text()
        # Complete the stages with injected transports and synthetic approvals only.
        for step in flow.STEPS:
            effect=flow.effect_for(state,step);approval=approve(effect)
            refused(lambda:flow.run_stage(state,step,work/'missing-approval',gate,api,fake,confirm,definition,lambda:True))
            if step=='claim':
                refused(lambda:flow.run_stage(state,step,approval,gate,api,fake,lambda name:'other',definition,lambda:True))
                api.registration_closed=lambda:False
                refused(lambda:flow.run_stage(state,step,approval,gate,api,fake,confirm,definition,lambda:True))
                api.registration_closed=lambda:True
                api.firewall_rules=lambda identity:[{'port':'80'}]
                refused(lambda:flow.run_stage(state,step,approval,gate,api,fake,confirm,definition,lambda:True))
                api.firewall_rules=lambda identity:[]
            else:
                api.registration_closed=lambda:False
                refused(lambda:flow.run_stage(state,step,approval,gate,api,fake,confirm,definition,lambda:True))
                api.registration_closed=lambda:True
            if step in ('register','start-register'):
                refused(lambda:flow.run_stage(state,step,approval,gate,api,fake,confirm,lambda name:dict(ports=['tcp:80']),lambda:True))
            if step=='record':
                refused(lambda:flow.run_stage(state,step,approval,gate,api,fake,confirm,definition,lambda:False))
            with patch.object(flow,'prompt',return_value='synthetic-only'):
                update=flow.run_stage(state,step,approval,gate,api,fake,confirm,definition,lambda:True)
            state.update(update);state['done'].append(step)
        assert state['done']==flow.STEPS
        # Removal tests rerun the same protected outcome and require it to escape.
        state['done']=[];approval=approve(flow.effect_for(state,'claim'))
        removals=[
            ('destination discovery',"step=='claim' or all(key in state for key in ('server_uuid','destination_uuid'))",'True','discovery'),
            ('stage order',"state.get('done',[])==STEPS[:STEPS.index(step)]",'True','order'),
            ('uncertain write',"state.get('uncertain') is None",'True','uncertain'),
            ('claim approval','    gate.match_effect(effect,approval)','    pass','approval'),
            ('claim ownership confirmation',"confirm(record['place']['name'])=='claimed '+record['place']['name']",'True','confirm'),
            ('closed registration',"api.registration_closed() and api.coolify_team() is not None",'True','registration'),
            ('claim firewall',"api.firewall_rules(record['infrastructure']['firewall_id'])==[]",'True','firewall'),
            ('canary read-back',"isinstance(definition,dict) and definition.get('ports')==['tcp:443'] and reachable()",'True','canary'),
            ('registration port',"before is None or before.get('ports')==['tcp:443']",'True','ports'),
        ]
        for name,old,new,kind in removals:
            assert old in stage_source,name
            p=work/'mutated-setup.py';p.write_text(stage_source.replace(old,new,1));mod=load(p)
            test=copy.deepcopy(state);test['uncertain']=None
            if kind=='discovery':
                test['done']=['claim'];test.pop('server_uuid');test.pop('destination_uuid');mod.effect_for(test,'project')
            elif kind=='order':
                test['done']=['claim'];mod.effect_for(test,'claim')
            elif kind=='uncertain':
                test['uncertain']='claim';mod.effect_for(test,'claim')
            else:
                step='claim'
                if kind=='canary':step='record'
                if kind=='ports':step='register'
                test['done']=flow.STEPS[:flow.STEPS.index(step)];approval=approve(mod.effect_for(test,step))
                if kind=='approval':approval=work/'missing-approval'
                api.registration_closed=lambda:kind!='registration'
                api.firewall_rules=lambda identity:[{'port':'80'}] if kind=='firewall' else []
                result=mod.run_stage(test,step,approval,gate,api,fake,lambda name:'other' if kind=='confirm' else 'claimed '+name,
                    lambda name:dict(ports=['tcp:80'] if kind=='ports' else ['tcp:443']),lambda:kind!='canary')
            print('Protection removal detected: '+name)
        # Scope declarations and returned abilities are independently refused.
        for scopes,observed in [(['root'],None),(sorted(flow.SCOPES),['root'])]:
            refused(lambda:mcp.MCP('/missing/package.json','100.64.0.10','synthetic',scopes,observed))
        record_state=copy.deepcopy(state)
        record_state['choice_path']=str(path)
        changed=copy.deepcopy(choice);changed['choice']['answers']['cloud']='none'
        path.write_text(json.dumps(changed))
        refused(lambda:flow.record_created(record_state,reader))
        assert json.loads(path.read_text())==changed
        old="fingerprint(reader.read_json(state['choice_path']))==state['choice_sha256']"
        assert old in stage_source
        mutated_source=stage_source.replace(old,'True')
        p=work/'record-mutated.py';p.write_text(mutated_source)
        load(p).record_created(record_state,reader)
        assert json.loads(path.read_text())!=changed
        path.write_text(json.dumps(choice))
        print('Protection removal detected: changed choice is never overwritten')
        cli(work,flow,gate,reader,config,choice,facts)
        # Remove only receipt consumption and rerun every named-effect reuse probe.
        mutated_work=work/'setup-receipt-removal';mutated_work.mkdir()
        receipt=mutated_work/'receipt.json';receipt.write_text('{}')
        with patch.object(flow,'start_attempt',return_value=receipt):
            try: cli(mutated_work,flow,gate,reader,config,choice,facts)
            except AssertionError as error:
                assert 'Reused named effects' in str(error),str(error)
                print('Protection removal detected: '+str(error))
            else: raise AssertionError('Setup receipt removal escaped')
        saved=work/'provider.plan';saved.write_bytes(b'synthetic encrypted-plan stand-in')
        binding={};flow.bind_provider(binding,saved,'synthetic-project-one',gate,remember=True)
        flow.bind_provider(binding,saved,'synthetic-project-one',gate)
        refused(lambda:flow.bind_provider(binding,saved,'synthetic-project-two',gate))
        old="state.get('provider_plans',{}).get(checksum)==expected"
        assert old in stage_source
        path=work/'provider-mutated.py';path.write_text(stage_source.replace(old,'True',1));mutated=load(path)
        mutated.bind_provider(binding,saved,'synthetic-project-two',gate)
        saved.write_bytes(b'different synthetic plan')
        refused(lambda:flow.bind_provider(binding,saved,'synthetic-project-one',gate))
        print('Protection removal detected: project token bound to saved plan')
        cloud_init(work,RECIPE)
        protocol(work,mcp,flow)
        protocol_guards(work,mcp,flow)
        print('Offline staged setup, claim, node and MCP checks passed.')
    finally: sys.path.pop(0)


def cli(work,flow,gate,reader,config,choice,facts):
    from contextlib import contextmanager
    folder=work/'cli';folder.mkdir()
    choice_path=folder/'hosting/place-record.json';choice_path.parent.mkdir();choice_path.write_text(json.dumps(choice))
    config_path=folder/'setup.json';config_path.write_text(json.dumps(config))
    progress=folder/'hosting/place-progress.json';root=folder/'hosting/tofu'
    def command(*args):
        with patch.object(sys,'argv',['setup',*args,'--progress',str(progress)]), patch.object(flow,'approval_gate',return_value=gate):
            return flow.main()
    assert command('root','--config',str(config_path),'--choice',str(choice_path),'--directory',str(root))==0
    with patch.object(flow,'prompt',return_value='synthetic-only'), patch.dict(os.environ,{'AWS_PROFILE':'synthetic-refusal'}), patch.object(gate,'tofu',side_effect=AssertionError('Initialisation reached the command stand-in with an inherited override.')):
        assert command('init')!=0
    state=json.loads(progress.read_text());state.update(applied=True,outputs=dict(server_id=101,firewall_id=102,ssh_key_id=103,ipv4_address='192.0.2.10'))
    flow.save(progress,state)
    facts=copy.deepcopy(facts);facts['status']['MagicDNSSuffix']='fixture.ts.net'
    with patch.object(flow,'read_node',return_value=facts): assert command('bootstrap','--address','100.64.0.10')==0
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
    class API:
        opener=SimpleNamespace(open=lambda *args,**kwargs:Response())
        def __init__(self,*args): pass
        def registration_closed(self):return True
        def coolify_team(self):return {'id':1}
        def token_abilities(self):return sorted(flow.SCOPES)
        def firewall_rules(self,*args):return []
        def request(self,method,url,*args):
            if url.endswith('/destinations'):return [{'uuid':'destination-one'}]
            if '/servers/' in url:return {'ip':'127.0.0.1'}
            return {'ports':['tcp:443']}
    writes=[]
    class MCP:
        def __init__(self,*args):pass
        def call(self,tool,args):writes.append((tool,args));return {'uuid':'created-'+tool}
        def close(self):pass
    def prompt(g,label):return 'claimed test-place' if 'type claimed' in label else 'synthetic-only'
    reuse_results=[]
    with patch.object(flow,'API',API),patch.object(flow,'MCP',MCP),patch.object(flow,'prompt',side_effect=prompt):
        for step in flow.STEPS:
            effect=folder/(step+'.json');approval=folder/(step+'-approval.json')
            assert command('prepare','--step',step,'--effect',str(effect))==0
            value=json.loads(effect.read_text())
            approval.write_text(json.dumps(dict(effect_sha256=gate.effect_sha(value),effect=value['effect'],words='Synthetic fixture approval',approved_at='2026-11-09T12:00:00Z',method='foreground-terminal')))
            before=json.loads(progress.read_text());choice_before=choice_path.read_text()
            assert command('run','--step',step,'--effect',str(effect),'--approval',str(approval),'--mcp-package',str(folder/'package.json'))==0
            after=json.loads(progress.read_text());choice_after=choice_path.read_text();count=len(writes)
            flow.save(progress,before);choice_path.write_text(choice_before)
            status=command('run','--step',step,'--effect',str(effect),'--approval',str(approval),'--mcp-package',str(folder/'package.json'))
            reuse_results.append((step,status!=0 and len(writes)==count))
            # Restore fixture progress and observed write count for the next stage.
            del writes[count:];flow.save(progress,after);choice_path.write_text(choice_after)
            if step=='claim':assert command('discover','--server-uuid','server-one','--destination-uuid','destination-one')==0
        assert all(passed for step,passed in reuse_results),'Reused named effects: '+', '.join(step for step,passed in reuse_results if not passed)
        final=json.loads(choice_path.read_text());flow.validate_record(reader,final)
        assert final['choice']==choice['choice'] and final['infrastructure']['plumbing']['docktail_uuid']=='created-service'
        assert len(writes)==7
        state=json.loads(progress.read_text());state['done']=[];flow.save(progress,state)
        effect=folder/'bad-effect.json';assert command('prepare','--step','claim','--effect',str(effect))==0
        assert command('run','--step','claim','--effect',str(effect),'--approval',str(folder/'missing'))!=0
        assert len(writes)==7
    # Validate the generated root with the actual pinned provider offline.
    from place_checks import RECIPE
    cache=RECIPE/'tofu/hetzner-server/.terraform/providers'
    if cache.is_dir():shutil.copytree(cache,root/'.terraform/providers')
    for args in [('init','-backend=false','-input=false','-lockfile=readonly'),('validate',)]:
        result=subprocess.run(['tofu',*args],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        assert result.returncode==0,result.stderr.decode()
    print('Generated root validates and the setup CLI completes all stages against stand-ins.')


def cloud_init(work,recipe):
    import base64
    source=(recipe/'tofu/hetzner-server/cloud-init.sh').read_text()
    marker='tskey-auth-synthetic-only'
    encoded=base64.b64encode(marker.encode()).decode()
    script=source.replace('{{TAILSCALE_KEY_B64}}',encoded).replace('{{PLACE_NAME}}','test-place')
    assert marker not in script and script.count(encoded)==1
    assert script.index('apt-get')<script.index('tailscale up')<script.index('bash -s 4.3.23')
    section=script[script.index('install -d'):]
    def outcome(text,fail):
        root=work/'boot-run';shutil.rmtree(root,ignore_errors=True);root.mkdir()
        key=root/'tailscale-auth-key';mode=root/'mode';installed=root/'installed'
        # Functions are local command stand-ins; the shell still executes traps,
        # umask, file write and deletion for real in this throwaway folder.
        prefix='''#!/bin/bash
set -euo pipefail
tailscale() {
 if [ "$1" = up ]; then
   stat -f '%Lp' "$BOOT_KEY" > "$BOOT_MODE"
   test "$(cat "$BOOT_KEY")" = 'tskey-auth-synthetic-only' || exit 42
   test "$2" = "--auth-key=file:$BOOT_KEY" || exit 43
   return "$BOOT_FAIL"
 fi
 return 0
}
curl() { test ! -e "$BOOT_KEY" || exit 44; touch "$BOOT_INSTALLED"; }
'''
        # Linux stat has a different format option.
        if sys.platform!='darwin':prefix=prefix.replace("stat -f '%Lp'","stat -c '%a'")
        target=root/'run.sh';target.write_text(prefix+text.replace('/run/ai-host-kit',str(root)))
        env=dict(os.environ,BOOT_KEY=str(key),BOOT_MODE=str(mode),BOOT_INSTALLED=str(installed),BOOT_FAIL=str(fail))
        result=subprocess.run(['bash',str(target)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        assert marker.encode() not in result.stdout+result.stderr and encoded.encode() not in result.stdout+result.stderr
        return result.returncode,key.exists(),installed.exists(),mode.read_text().strip()
    assert outcome(section,0)==(0,False,True,'600')
    code,exists,installed,mode=outcome(section,1)
    assert code!=0 and not exists and not installed and mode=='600'
    assert outcome(section.replace('trap \'rm -f "$TAILSCALE_KEY_FILE"\' EXIT','true'),1)[1]
    assert outcome(section.replace('    exit 1','    true'),1)[0]==0
    assert outcome(section.replace('rm -f "$TAILSCALE_KEY_FILE"\ntailscale ip','true\ntailscale ip'),0)[0]!=0
    print('Protection removals detected: failed-join cleanup, hard failure and cleanup before Coolify.')


def protocol(work,mcp,flow,package=None):
    # Exercise the actual stdio framing using a local child process, no model.
    child=work/'stdio.py'
    child.write_text('''import sys,json
for line in sys.stdin:
 r=json.loads(line)
 if 'id' not in r: continue
 if r['method']=='initialize': result={'serverInfo':{'version':'3.9.0'}}
 else: result={'content':[{'type':'text','text':json.dumps({'version':'3.9.0','uuid':'synthetic-service'})}]}
 print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)
''')
    folder=work/'package';folder.mkdir(exist_ok=True)
    (folder/'package.json').write_text(json.dumps(dict(name='@masonator/coolify-mcp',version='3.9.0')))
    original=subprocess.Popen;calls=[]
    def spawn(command,**kwargs):
        assert command[0]=='node' and kwargs['env']['COOLIFY_BASE_URL']=='http://100.64.0.10:8000'
        assert not set(kwargs['env'])-{'PATH','COOLIFY_BASE_URL','COOLIFY_ACCESS_TOKEN'}
        calls.append(command)
        return original([sys.executable,'-u',str(child)],**kwargs)
    with patch.object(mcp.subprocess,'Popen',side_effect=spawn):
        client=mcp.MCP(folder/'package.json','100.64.0.10','synthetic-only',sorted(flow.SCOPES))
        try: assert client.call('service',dict(action='create'))['uuid']=='synthetic-service'
        finally:client.close()
    assert calls
    if package:
        actual_package(work,mcp,flow,package)


def protocol_guards(work,mcp,flow):
    from place_checks import load, refused, RECIPE
    folder=work/'guard-package';folder.mkdir()
    package=folder/'package.json'
    child=work/'guard-stdio.py'
    original=subprocess.Popen
    def attempt(module,kind):
        version='9.0.0' if kind=='package' else '3.9.0'
        package.write_text(json.dumps(dict(name='@masonator/coolify-mcp',version=version)))
        hello='9.0.0' if kind=='hello' else '3.9.0'
        tool='9.0.0' if kind=='tool' else '3.9.0'
        child.write_text("import sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n if 'id' not in r: continue\n result={'serverInfo':{'version':"+repr(hello)+"}} if r['method']=='initialize' else {'content':[{'type':'text','text':json.dumps({'version':"+repr(tool)+"})}]}\n print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)\n")
        def spawn(command,**kwargs):return original([sys.executable,'-u',str(child)],**kwargs)
        with patch.object(module.subprocess,'Popen',side_effect=spawn):
            client=module.MCP(package,'100.64.0.10','synthetic-only',
                ['root'] if kind=='declared' else sorted(flow.SCOPES),['root'] if kind=='observed' else None)
            client.close()
    source=(RECIPE/'scripts/mcp.py').read_text()
    cases=[
        ('declared',"        scoped_mcp(scopes, PINS['mcp'])","        pass"),
        ('observed',"            scoped_mcp(observed_abilities, PINS['mcp'])","            pass"),
        ('package',"metadata.get('name') == '@masonator/coolify-mcp' and metadata.get('version') == PINS['mcp']",'True'),
        ('hello',"hello.get('serverInfo', {}).get('version') == PINS['mcp']",'True'),
        ('tool',"version.get('version') == PINS['mcp']",'True'),
    ]
    for kind,old,new in cases:
        refused(lambda:attempt(mcp,kind))
        assert old in source
        path=work/'mutated-mcp.py';path.write_text(source.replace(old,new,1))
        attempt(load(path),kind)
        print('Protection removal detected: MCP '+kind)


def actual_package(work,mcp,flow,package):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            calls.append(('GET',self.path,None))
            self.send_response(200);self.end_headers();self.wfile.write(b'"4.3.23"')
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))) if int(self.headers.get('Content-Length','0')) else None if int(self.headers.get('Content-Length','0')) else None
            calls.append(('POST',self.path,body))
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(b'{"uuid":"synthetic-service"}')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    assert server.server_port!=3000
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    original=subprocess.Popen
    def spawn(command,**kwargs):
        kwargs['env']['COOLIFY_BASE_URL']='http://127.0.0.1:'+str(server.server_port)
        return original(command,**kwargs)
    try:
        with patch.object(mcp.subprocess,'Popen',side_effect=spawn):
            client=mcp.MCP(package,'100.64.0.10','synthetic-only',sorted(flow.SCOPES))
            try:
                result=client.call('service',dict(action='create',server_uuid='localhost',project_uuid='project',
                                   environment_name='production',name='docktail',instant_deploy=False,docker_compose_raw=flow.DOCKTAIL))
                assert result['uuid']=='synthetic-service'
                client.call('control',dict(resource='service',action='start',uuid='synthetic-service'))
            finally: client.close()
        import base64
        posted=next(body for method,path,body in calls if path=='/api/v1/services' and method=='POST')
        assert base64.b64decode(posted['docker_compose_raw']).decode()==flow.DOCKTAIL and posted['instant_deploy'] is False
        assert any(path=='/api/v1/services/synthetic-service/start' for method,path,body in calls)
        print('Unmodified MCP 3.9.0 created and started a synthetic service against a loopback API stand-in.')
    finally:server.shutdown();server.server_close();thread.join()
