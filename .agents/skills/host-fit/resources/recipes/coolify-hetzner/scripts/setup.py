"""Create an empty place in explicit, separately approved stages."""
# Launch order and the person-led admin claim adapted from coolify-launchpad.
import argparse
import copy
import json
import importlib.util
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from api import API, approval_gate, hidden_value as prompt
from check import load_reader
from mcp import MCP
from node import bootstrap, read_node
from place import PINS, SCOPES, fingerprint, require, scoped_mcp, tailnet_address, write_record

STEPS = ['claim', 'project', 'docktail', 'oauth-id', 'oauth-secret', 'start-docktail',
         'register', 'start-register', 'record']
DOCKTAIL = '''services:
  docktail:
    image: ghcr.io/marvinvr/docktail:1.8.6
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /var/run/tailscale:/var/run/tailscale
    environment:
      - TAILSCALE_OAUTH_CLIENT_ID=${TAILSCALE_OAUTH_CLIENT_ID}
      - TAILSCALE_OAUTH_CLIENT_SECRET=${TAILSCALE_OAUTH_CLIENT_SECRET}
      - LOG_LEVEL=info
'''


def canary(name):
    require(name.isascii() and name.replace('-', '').isalnum(), 'Use a plain service name.')
    return '''services:
  canary:
    image: traefik/whoami:v1.11.0
    restart: unless-stopped
    labels:
      docktail.service.enable: "true"
      docktail.service.name: "'''+name+'''"
      docktail.service.port: "80"
      docktail.service.service-port: "443"
      docktail.service.protocol: "http"
'''


def save(path, value):
    path=Path(path)
    require(not path.is_symlink(), 'A progress path must not be a symlink.')
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as out:
            json.dump(value,out,indent=2); out.write('\n')
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)


def validate_record(reader, record):
    loaded=reader.dependencies()
    require(loaded is not None, 'Install the schema requirements.')
    validator, formats=loaded
    errors=list(validator(reader.read_json(reader.ROOT/'contracts/place-record.schema.json'),
                          format_checker=formats).iter_errors(record))
    require(not errors and not list(reader.secret_fields(record)), 'The place record failed validation; values withheld.')


def initialise_s3(gate, settings):
    # Reuse the storage wrapper, including its inherited-override refusals.
    source=Path(gate.__file__).resolve().parent/'init-s3.py'
    spec=importlib.util.spec_from_file_location('place_init_s3',source)
    module=importlib.util.module_from_spec(spec)
    previous=sys.modules.get('approval_gate')
    arguments=sys.argv
    try:
        sys.modules['approval_gate']=gate
        spec.loader.exec_module(module)
        sys.argv=['init-s3',str(settings)]
        require(module.main()==0, 'Storage initialisation refused; no later stage ran.')
    finally:
        sys.argv=arguments
        if previous is None: sys.modules.pop('approval_gate',None)
        else: sys.modules['approval_gate']=previous


def prepare_root(config, choice_path, directory, progress_path, reader, gate):
    choice=reader.read_json(choice_path)
    validate_record(reader,choice)
    require(choice.get('choice',{}).get('host')=='coolify-hetzner' and 'infrastructure' not in choice,
            'Record the Coolify on Hetzner choice before creating a fresh place.')
    require(set(config)=={'place','encrypted_state','backend','inputs','scopes','canary_name'},
            'Use the recipe setup template; extra fields are refused.')
    scoped_mcp(config['scopes'],PINS['mcp'])
    backend=gate.s3_settings(config['backend'])
    require(config['encrypted_state']['location']=='s3://'+backend['bucket']+'/'+backend['key'],
            'The recorded state location must match the backend bucket and key.')
    require(config['place']['provider']=='Hetzner' and config['place']['kind']=='server' and
            config['place']['region']==config['inputs']['location'] and
            config['place']['name']==config['inputs']['place_name'], 'Place details differ from module inputs.')
    inputs=config['inputs']
    require(set(inputs)=={'place_name','location','server_type','ssh_public_key','tailnet_key_settings'},
            'Only non-secret module inputs belong in setup settings.')
    settings=inputs['tailnet_key_settings']
    require(set(settings)=={'reusable','ephemeral','preauthorised','tags','expiry_seconds','shortest_available'} and
            settings['reusable'] is False and settings['ephemeral'] is False and settings['preauthorised'] is True
            and settings['tags']==['tag:server'] and type(settings['expiry_seconds']) is int
            and settings['expiry_seconds']>0 and settings['shortest_available'] is True,
            'Use a one-off, pre-approved, non-ephemeral server key with the shortest available expiry.')
    canary(config['canary_name'])
    require(not Path(directory).exists() and not Path(progress_path).exists(), 'Choose new root and progress paths.')
    # Validate the assembled non-secret declaration before making a root.
    candidate=dict(schema_version='1.0',phase='place',place=config['place'],choice=choice['choice'],
                   network=dict(cidrs=['100.64.0.0/10'],private_access='Tailscale'),
                   firewall=dict(default_inbound='deny',rules=[]),tools=[],encrypted_state=config['encrypted_state'],
                   infrastructure=dict(server_id=1,firewall_id=1,ssh_key_id=1,public_ipv4='192.0.2.1',
                                       tailnet_ipv4='100.64.0.1',versions=PINS))
    validate_record(reader,candidate)
    directory=Path(directory).resolve(); directory.mkdir(parents=True)
    recipe=Path(__file__).resolve().parent.parent
    shutil.copytree(recipe/'tofu/hetzner-server',directory/'module',
                    ignore=shutil.ignore_patterns('.terraform','*.tfstate*'))
    # Root provider lock, plus the shared encryption fragment, are kept verbatim.
    shutil.copyfile(recipe/'tofu/hetzner-server/.terraform.lock.hcl',directory/'.terraform.lock.hcl')
    fragment=Path(gate.__file__).resolve().parent.parent/'resources/encryption.tf'
    shutil.copyfile(fragment,directory/'encryption.tf')
    root=dict(terraform={'required_version':'= 1.13.2','required_providers':{'hcloud':{
        'source':'hetznercloud/hcloud','version':'= 1.70.2'}},'backend':{'s3':{}}},
        variable={'hcloud_token':{'type':'string','sensitive':True,'ephemeral':True},
                  'tailnet_auth_key':{'type':'string','sensitive':True}},
        provider={'hcloud':{'token':'${var.hcloud_token}'}},
        module={'place':dict(source='./module',tailnet_auth_key='${var.tailnet_auth_key}',**inputs)},
        output={name:{'value':'${module.place.'+name+'}'} for name in ('server_id','firewall_id','ssh_key_id','ipv4_address')})
    save(directory/'main.tf.json',root); save(directory/'backend.json',config['backend'])
    save(progress_path,dict(config=config,choice_path=str(Path(choice_path).resolve()),
        choice_sha256=fingerprint(choice),root=str(directory),done=[],uncertain=None))
    print('Prepared the local root. No provider was contacted. Review it before initialising or planning.')


def effect_for(state, step):
    require(state.get('uncertain') is None, 'A previous write has an uncertain result. Inspect it before any retry; use the retained state to retire.')
    require(step in STEPS and state.get('done',[])==STEPS[:STEPS.index(step)], 'Complete the preceding setup stage first.')
    require('record' in state, 'Apply and pass the bootstrap reads before preparing a write.')
    require(step=='claim' or all(key in state for key in ('server_uuid','destination_uuid')),
            'Read and select the localhost server and destination before preparing a Coolify write.')
    record=state['record']; config=state['config']; name=record['place']['name']
    common=dict(action='place-'+step,progress_sha256=fingerprint(state),place_sha256=fingerprint(record))
    args={}; tool=None
    if step=='claim':
        description='Let the person create the first Coolify administrator for '+name+' over the tailnet. That account owns this Coolify instance. No public ports open. The person supplies their password in Coolify and confirms the claim here.'
    elif step=='project':
        tool='projects'; args=dict(action='create',name=name+'-infrastructure')
        description='Create the private Coolify infrastructure project for '+name+'. No tool or public address is created.'
    elif step in ('docktail','register'):
        tool='service'
        compose=DOCKTAIL if step=='docktail' else canary(config['canary_name'])
        args=dict(action='create',name=name+'-'+step,server_uuid=state['server_uuid'],project_uuid=state['project_uuid'],
                  environment_name='production',destination_uuid=state['destination_uuid'],
                  instant_deploy=False,docker_compose_raw=compose)
        description=('Create the unmodified docktail 1.8.6 container definition with access to the Docker and Tailscale sockets. '
                     'It can register labelled services using the supplied OAuth identity. No published ports.' if step=='docktail' else
                     'Create the pinned whoami canary with docktail labels for '+config['canary_name']+
                     ', tailnet TCP 443 to container port 80. It becomes reachable by the people allowed by the existing tailnet policy when started. No public ports.')
    elif step in ('oauth-id','oauth-secret'):
        tool='env_vars'; key='TAILSCALE_OAUTH_CLIENT_'+('ID' if step=='oauth-id' else 'SECRET')
        args=dict(resource='service',action='create',uuid=state['docktail_uuid'],key=key,
                  is_buildtime=False,is_runtime=True,is_preview=False)
        description='Store the person-supplied '+key+' in the docktail Coolify runtime environment. The approved value is entered through the hidden prompt, never saved locally. Docktail will gain the abilities of that OAuth client.'
    elif step in ('start-docktail','start-register'):
        tool='control'; args=dict(resource='service',action='start',uuid=state['docktail_uuid' if step=='start-docktail' else 'register_uuid'])
        description=('Start docktail 1.8.6. It watches Docker labels and can change Tailscale service registrations using its OAuth client.' if step=='start-docktail' else
                     'Start the canary and let docktail register '+config['canary_name']+' for tailnet TCP 443. Existing tailnet policy decides who gains access. No public ports open.')
    else:
        description='Replace the unchanged local hosting/place-record.json choice draft with the created empty place record. This records infrastructure and versions, with no backup, alert or tool claim.'
    return dict(**common,effect=description,tool=tool,arguments=args)


def run_stage(state, step, approval, gate, api, mcp, confirm, service_definition, reachable):
    effect=effect_for(state,step)
    gate.match_effect(effect,approval)
    record=state['record']
    if step=='claim':
        require(api.firewall_rules(record['infrastructure']['firewall_id'])==[], 'Keep all inbound rules closed until the claim is confirmed.')
        require(confirm(record['place']['name'])=='claimed '+record['place']['name'], 'The person must confirm their own administrator claim.')
        require(api.registration_closed() and api.coolify_team() is not None, 'Registration must redirect to login and the person\'s team token must work.')
        return {}
    require(api.registration_closed(), 'Coolify registration is open or unreadable; no write is allowed.')
    if step=='record':
        definition=service_definition(state['config']['canary_name'])
        require(isinstance(definition,dict) and definition.get('ports')==['tcp:443'] and reachable(),
                'The registered canary must declare TCP 443 and answer over HTTPS before recording.')
        return {}
    if step in ('register','start-register'):
        before=service_definition(state['config']['canary_name'])
        require(before is None or before.get('ports')==['tcp:443'], 'Refused different write-once service ports; repair needs separate approval.')
    args=copy.deepcopy(effect['arguments'])
    if step in ('oauth-id','oauth-secret'):
        args['value']=prompt(gate,args['key'])
    result=mcp.call(effect['tool'],args)
    require(isinstance(result,dict), 'The MCP write returned an unexpected result; inspect the place before retrying.')
    if step in ('project','docktail','register'):
        require(isinstance(result.get('uuid'),str) and bool(result['uuid']), 'The MCP write returned no identity; inspect the place before retrying.')
        return {step+'_uuid':result['uuid']}
    return {}


def record_created(state, reader):
    require(fingerprint(reader.read_json(state['choice_path']))==state['choice_sha256'],
            'The choice changed during the reads; do not overwrite it.')
    record=copy.deepcopy(state['record'])
    record['infrastructure']['plumbing']=dict(project_uuid=state['project_uuid'],docktail_uuid=state['docktail_uuid'],
        canary_uuid=state['register_uuid'],tailnet_service_name=state['config']['canary_name'])
    validate_record(reader,record)
    save(state['choice_path'],record)
    return record


def bind_provider(state, plan, token, gate, remember=False):
    checksum=gate.digest(Path(plan).read_bytes())
    expected=fingerprint(token)
    if remember:
        state.setdefault('provider_plans',{})[checksum]=expected
    else:
        require(state.get('provider_plans',{}).get(checksum)==expected,
                'The project token differs from the one used for this saved plan. Save and approve a new plan.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['root','init','plan','summary','approve','apply','bootstrap','prepare','run','candidate','discover','plan-destroy','retire'])
    parser.add_argument('--config'); parser.add_argument('--choice',default='hosting/place-record.json')
    parser.add_argument('--directory',default='hosting/tofu'); parser.add_argument('--progress',default='hosting/place-progress.json')
    parser.add_argument('--plan'); parser.add_argument('--approval'); parser.add_argument('--effect')
    parser.add_argument('--step',choices=STEPS); parser.add_argument('--address'); parser.add_argument('--mcp-package')
    parser.add_argument('--server-uuid'); parser.add_argument('--destination-uuid'); parser.add_argument('--canary-url')
    args=parser.parse_args(); client=None; state=None; previous_directory=Path.cwd()
    for field in ('plan','approval','effect','choice','mcp_package'):
        value=getattr(args,field)
        if value: setattr(args,field,str(Path(value).resolve()))
    try:
        reader=load_reader(); gate=approval_gate()
        if args.command=='root':
            require(args.config is not None, 'Supply the non-secret setup settings.')
            prepare_root(reader.read_json(args.config),args.choice,args.directory,args.progress,reader,gate); return 0
        progress=Path(args.progress).resolve(); state=reader.read_json(progress)
        root=Path(state['root']); record=state.get('record')
        if args.command=='prepare':
            require(args.step and args.effect, 'Name the stage and new effect path.')
            effect=effect_for(state,args.step)
            write_record(effect,args.effect,lambda value:None); print(effect['effect'])
            if args.step=='claim': print('After this effect is approved, open http://'+state['record']['infrastructure']['tailnet_ipv4']+':8000/register yourself, create the first administrator, enable two-factor authentication, then create the scoped team token for the run command.')
            return 0
        if args.command=='retire':
            require(args.plan and args.approval, 'Supply the saved destroy plan and its approval.')
            os.chdir(root)
            os.environ['TF_VAR_host_state_passphrase']=prompt(gate,'State passphrase')
            os.environ['TF_VAR_hcloud_token']=prompt(gate,'Hetzner project token')
            bind_provider(state,args.plan,os.environ['TF_VAR_hcloud_token'],gate)
            import retire
            previous=sys.argv
            try:
                sys.argv=['retire','--record',str(Path(args.choice).resolve()),'--plan',args.plan,'--approval',args.approval]
                return retire.main()
            finally: sys.argv=previous
        if args.command in ('init','plan','plan-destroy','summary','approve','apply'):

            if args.command in ('init','plan','apply'):
                require(not state['done'] and not state.get('uncertain'), 'Provisioning has already progressed or has an uncertain write.')
            os.chdir(root)
            os.environ['TF_VAR_host_state_passphrase']=prompt(gate,'State passphrase')
            if args.command=='init':
                initialise_s3(gate,root/'backend.json')
            elif args.command=='plan':
                require(args.plan, 'Supply a new saved-plan path.')
                os.environ['TF_VAR_hcloud_token']=prompt(gate,'Hetzner project token')
                os.environ['TF_VAR_tailnet_auth_key']=prompt(gate,'Single-use pre-approved non-ephemeral tag:server Tailscale key, shortest available expiry, aim one hour')
                gate.plan(args.plan)
                bind_provider(state,args.plan,os.environ['TF_VAR_hcloud_token'],gate,remember=True); save(progress,state)
            elif args.command=='plan-destroy':
                require(args.plan, 'Supply a new destroy-plan path.')
                os.environ['TF_VAR_hcloud_token']=prompt(gate,'Hetzner project token')
                # Destroy does not enrol a node. Satisfy the required input with
                # an inert synthetic marker rather than request the spent key.
                os.environ['TF_VAR_tailnet_auth_key']='tskey-auth-unused-destroy-only'
                gate.plan(args.plan,destroy=True)
                bind_provider(state,args.plan,os.environ['TF_VAR_hcloud_token'],gate,remember=True); save(progress,state)
            elif args.command=='summary':
                require(args.plan, 'Supply the saved-plan path.')
                with gate.saved_plan(args.plan) as (snapshot,sha):
                    target=gate.planned_identity(args.plan,sha)
                    print(gate.render(sha,gate.read_plan(snapshot),target))
            elif args.command=='approve':
                require(args.plan and args.approval, 'Supply plan and new approval paths.')
                gate.approve(args.plan,args.approval)
            else:
                require(args.plan and args.approval and not state.get('applied'), 'Supply the approved plan; do not apply a place twice.')
                os.environ['TF_VAR_hcloud_token']=prompt(gate,'Hetzner project token')
                bind_provider(state,args.plan,os.environ['TF_VAR_hcloud_token'],gate)
                # Check approval before recording uncertainty, and let apply check again.
                with gate.saved_plan(args.plan) as (snapshot,sha):
                    gate.match_record(gate.validate_record(args.approval),sha,gate.read_plan(snapshot))
                    gate.planned_identity(args.plan,sha)
                state['uncertain']='apply'; save(progress,state)
                gate.apply(args.plan,args.approval)
                result=gate.tofu('output','-json')
                require(result.returncode==0,'Read the created resource identities before continuing.')
                outputs=json.loads(result.stdout)
                state['outputs']={key:outputs[key]['value'] for key in ('server_id','firewall_id','ssh_key_id','ipv4_address')}
                state['applied']=True; state['uncertain']=None; save(progress,state)
                print('Applied the approved plan. Three resources exist; bootstrap and the administrator claim are next. Keep the encrypted state for retirement.')
            return 0
        if args.command=='bootstrap':
            require(state.get('applied') and not state['done'] and args.address,
                    'Apply first, then provide the tailnet address of the new server.')
            outputs=state['outputs']; config=state['config']; choice=reader.read_json(state['choice_path'])
            require(fingerprint(choice)==state['choice_sha256'],'The saved choice changed; inspect it before continuing.')
            record=dict(schema_version='1.0',phase='place',place=config['place'],choice=choice['choice'],
                network=dict(cidrs=['100.64.0.0/10'],private_access='Tailscale'),firewall=dict(default_inbound='deny',rules=[]),
                tools=[],encrypted_state=config['encrypted_state'],infrastructure=dict(
                    server_id=int(outputs['server_id']),firewall_id=int(outputs['firewall_id']),ssh_key_id=int(outputs['ssh_key_id']),
                    public_ipv4=outputs['ipv4_address'],tailnet_ipv4=tailnet_address(args.address),versions=PINS))
            validate_record(reader,record)
            facts=read_node(record['infrastructure']['tailnet_ipv4'])
            bootstrap(record,lambda address:facts)
            suffix=facts.get('status',{}).get('MagicDNSSuffix','')
            require(re.fullmatch(r'[a-z0-9-]+\.ts\.net',suffix), 'Read a supported MagicDNS suffix from the joined server.')
            state['tailnet_suffix']=suffix
            state.update(record=record)
            save(progress,state); print('Bootstrap reads passed. No public ports open. Prepare the administrator claim next.'); return 0
        require(record is not None, 'Bootstrap must pass before this stage.')
        validate_record(reader,record)
        if args.command=='candidate':
            require(args.config, 'Use --config for a new candidate record path.')
            write_record(record,args.config,lambda value:validate_record(reader,value)); return 0
        if args.command=='discover':
            require(state['done']==['claim'] and args.server_uuid and args.destination_uuid,
                    'Claim first, then select the localhost server and its Docker destination in Coolify.')
            token=prompt(gate,'Coolify scoped token')
            api=API(record,'',token)
            address=record['infrastructure']['tailnet_ipv4']
            server=api.request('GET','http://'+address+':8000/api/v1/servers/'+args.server_uuid,token)
            require(server.get('ip') in ('127.0.0.1','localhost'), "Select this Coolify instance's localhost server.")
            destinations=api.request('GET','http://'+address+':8000/api/v1/servers/'+args.server_uuid+'/destinations',token)
            require(any(item.get('uuid')==args.destination_uuid for item in destinations), 'The destination does not belong to the selected server.')
            state.update(server_uuid=args.server_uuid,destination_uuid=args.destination_uuid); save(progress,state)
            print('Recorded the read-back localhost server and Docker destination.'); return 0
        require(args.step and args.approval and args.effect,'Name the stage, prepared effect and approval.')
        effect=effect_for(state,args.step)
        require(reader.read_json(args.effect)==effect,'The prepared effect differs from the current stage.')
        gate.match_effect(effect,args.approval)
        token=prompt(gate,'Coolify token with read, read:sensitive, write and deploy, never root')
        api=API(record,'',token)
        observed=api.token_abilities()
        if observed is not None: scoped_mcp(observed,PINS['mcp'])
        else: print('Coolify does not expose current-token abilities here. The scope setting remains a declaration; check it in Coolify before proceeding.')
        if args.step not in ('claim','record'):
            require(args.mcp_package,'Supply the installed pinned MCP package.json path.')
            client=MCP(args.mcp_package,record['infrastructure']['tailnet_ipv4'],token,state['config']['scopes'],observed)
        def confirm(name):
            address=record['infrastructure']['tailnet_ipv4']
            print('Open http://'+address+':8000/register yourself, create the first administrator and enable two-factor authentication. Nothing is public. Then create the scoped team token. A failed form can return HTTP 429; wait ten minutes before one careful retry.')
            return prompt(gate,'After creating your own account, type claimed '+name)
        def definition(name):
            import urllib.error
            key=prompt(gate,'Tailscale API read token for service definitions')
            try: return api.request('GET','https://api.tailscale.com/api/v2/tailnet/-/services/svc:'+name,key)
            except urllib.error.HTTPError as error:
                if error.code==404: return None
                raise
        def reachable():
            import urllib.request
            from urllib.parse import urlparse
            expected='https://'+state['config']['canary_name']+'.'+state['tailnet_suffix']
            url=urlparse(args.canary_url or expected)
            require(url.geturl().rstrip('/')==expected, 'The canary address must match this joined tailnet.')
            require(url.scheme=='https' and url.hostname and url.hostname.startswith(state['config']['canary_name']+'.') and url.hostname.endswith('.ts.net')
                    and not url.username and not url.password and not url.query and not url.fragment and url.port is None and url.path in ('','/'),
                    'Supply the canary HTTPS address in this tailnet.')
            with api.opener.open(url.geturl(),timeout=45) as response: return response.status==200
        if args.step=='record':
            require(fingerprint(reader.read_json(state['choice_path']))==state['choice_sha256'],'The choice changed; do not overwrite it.')
        state_before=copy.deepcopy(state)
        # Writes are not retried automatically if the process or read-back fails.
        state['uncertain']=args.step; save(progress,state)
        update=run_stage(state_before,args.step,args.approval,gate,api,client,confirm,definition,reachable)
        if args.step=='record': state['record']=record_created(state,reader)
        state.update(update); state['done'].append(args.step); state['uncertain']=None; save(progress,state)
        print('Completed '+args.step+'. The place remains empty; use /check-live to read it.')
        return 0
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired):
        if isinstance(state,dict):
            infra=state.get('record',{}).get('infrastructure',{})
            if all(type(infra.get(key)) is int and infra[key]>0 for key in ('server_id','firewall_id','ssh_key_id')):
                print('Recorded resources: server '+str(infra['server_id'])+', firewall '+str(infra['firewall_id'])+', SSH key '+str(infra['ssh_key_id'])+'. This failed setup command has not retired them.',file=sys.stderr)
            done=[step for step in state.get('done',[]) if step in STEPS]
            if done: print('Completed setup stages: '+', '.join(done)+'.',file=sys.stderr)
            uncertain=state.get('uncertain')
            if uncertain in STEPS+['apply']:
                print('Uncertain result: '+uncertain+'. Its change may exist. Inspect it before any retry.',file=sys.stderr)
            if any(step in done for step in ('project','docktail','register')) or uncertain in ('project','docktail','register','start-register'):
                print('Coolify plumbing may exist on the server. Retirement removes its disk and containers; a Tailscale service definition can remain for separate review.',file=sys.stderr)
        print('Stopped: setup inputs, approval or transport failed; values withheld. Before apply, no provider resources are expected. After an attempted apply, the server, firewall and SSH key may exist. Keep the progress file and encrypted state. Export a candidate record if bootstrap passed, then use retire.py with an approved destroy plan. For a partial apply, review and approve the saved destroy plan through the gate. Do not retry an uncertain write or remove console leftovers without separate approval.',file=sys.stderr)
        return 1
    finally:
        os.chdir(previous_directory)
        if client is not None: client.close()
        for key in ('TF_VAR_host_state_passphrase','TF_VAR_hcloud_token','TF_VAR_tailnet_auth_key'):
            os.environ.pop(key,None)


if __name__=='__main__': sys.exit(main())
