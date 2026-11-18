"""Create an empty place in explicit, separately approved stages."""
# Launch order and the person-led admin claim adapted from coolify-launchpad.
import argparse
from contextlib import ExitStack, contextmanager
import copy
import fcntl
import json
import importlib.util
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
from api import API, approval_gate, hidden_value as prompt
from check import load_reader
from mcp import MCP
from node import bootstrap_address, bootstrap, read_node, wait_bootstrap, BootstrapFailed, reopen_claim
from place import OperationRefused, PINS, SCOPES, fingerprint, require, scoped_mcp, tailnet_address, write_record, start_attempt, finish_attempt, mark_dispatch, partial_record, journal_identity, place_lock
from place import JOURNAL_MESSAGE

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
    require(set(config)-{'secrets'}=={'place','encrypted_state','backend','inputs','scopes','canary_name'},
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
    config=copy.deepcopy(config)
    config.setdefault('secrets',str(Path.home()/'.config/ai-host-kit/places'/(config['place']['name']+'.env')))
    require(isinstance(config['secrets'],str) and bool(config['secrets']), 'Supply a non-secret secrets file path.')
    config['secrets']=str(Path(config['secrets']).expanduser().absolute())
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
        choice_sha256=fingerprint(choice),root=str(directory),done=[],uncertain=None, journal=journal_identity(Path(choice_path).resolve().parent/'place-attempts')))
    print('Prepared the local root. No provider was contacted. Review it before initialising or planning.')


def effect_for(state, step):
    require(state.get('uncertain') is None, 'A previous write has an uncertain result. Inspect it before any retry; use the retained state to retire.')
    require(step in STEPS and state.get('done',[])==STEPS[:STEPS.index(step)], 'Complete the preceding setup stage first.')
    require('record' in state, 'Apply and pass the bootstrap reads before preparing a write.')
    require(step=='claim' or all(key in state for key in ('server_uuid','destination_uuid')),
            'Read and select the localhost server and destination before preparing a Coolify write.')
    record=state['record']; config=state['config']; name=record['place']['name']
    common=dict(journal=state['journal'],action='place-'+step,progress_sha256=fingerprint(state),place_sha256=fingerprint(record))
    args={}; tool=None
    if step=='claim':
        description='Restart the coolify container over Tailscale SSH and wait for health to reopen its ten-minute setup window. Let the person create the first Coolify administrator for '+name+' over the tailnet. That account owns this Coolify instance. No public ports open. The person supplies their password in Coolify and confirms the claim here.'
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
        args=dict(resource='service',action='set',uuid=state['docktail_uuid'],key=key,
                  is_buildtime=False,is_runtime=True,is_preview=False)
        description='Store the person-supplied '+key+' in the docktail Coolify runtime environment. The approved value comes from the protected file or prompt; the kit saves no local copy. Docktail will gain the abilities of that OAuth client.'
    elif step in ('start-docktail','start-register'):
        tool='control'; args=dict(resource='service',action='start',uuid=state['docktail_uuid' if step=='start-docktail' else 'register_uuid'])
        description=('Start docktail 1.8.6. It watches Docker labels and can change Tailscale service registrations using its OAuth client.' if step=='start-docktail' else
                     'Start the canary and let docktail register '+config['canary_name']+' for tailnet TCP 443. Existing tailnet policy decides who gains access. No public ports open.')
    else:
        description='Replace the unchanged local hosting/place-record.json choice draft with the created empty place record. This records infrastructure and versions, with no backup, alert or tool claim.'
    return dict(**common,effect=description,tool=tool,arguments=args)


def read_require(condition, message):
    if not condition: raise OperationRefused(message)


def check_claim(record, api, confirm):
    read_require(api.firewall_rules(record['infrastructure']['firewall_id'])==[], 'Keep all inbound rules closed until the claim is confirmed.')
    read_require(confirm(record['place']['name'])=='claimed '+record['place']['name'], 'The person must confirm their own administrator claim.')
    read_require(api.registration_closed() and api.coolify_team() is not None, 'Registration must redirect to login and the person\'s team token must work.')


def run_stage(state, step, approval, gate, api, mcp, confirm, service_definition, reachable, oauth_value=None, dispatch=lambda:None):
    effect=effect_for(state,step)
    gate.match_effect(effect,approval)
    record=state['record']
    if step=='claim':
        check_claim(record,api,confirm)
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
        rows=mcp.call('env_vars',dict(resource='service',action='list',uuid=args['uuid'],key=args['key'],reveal=False))
        read_require(isinstance(rows,list), 'Coolify environment read returned no list; no value was sent.')
        existing=[row for row in rows if row.get('key')==args['key'] and row.get('is_preview') is False]
        read_require(len(existing)<=1 and all(row.get('is_preview') in (True,False) for row in rows),
                'Coolify environment scope is ambiguous; no value was sent.')
        args['action']='update' if existing else 'create'
        args['value']=oauth_value if oauth_value is not None else prompt(gate,args['key'])
    dispatch()
    try:
        result=mcp.call(effect['tool'],args)
    except ValueError:
        if step in ('oauth-id','oauth-secret'):
            raise OperationRefused('Coolify refused the environment write. Inspect the key and scope for a conflict; no fallback write was sent.') from None
        raise
    require(isinstance(result,dict), 'The MCP write returned an unexpected result; inspect the place before retrying.')
    if step in ('oauth-id','oauth-secret'):
        rows=api.service_env_state(args['uuid'],args['key'])
        read_require(len(rows)==1 and rows[0]==dict(is_set=True,is_runtime=True,is_buildtime=False,is_preview=False),
                'Coolify did not confirm a set production runtime value; inspect the uncertain stage.')
    if step in ('project','docktail','register'):
        require(isinstance(result.get('uuid'),str) and bool(result['uuid']), 'The MCP write returned no identity; inspect the place before retrying.')
        return {step+'_uuid':result['uuid']}
    return {}


def record_candidate(state, reader):
    require(fingerprint(reader.read_json(state['choice_path']))==state['choice_sha256'],
            'The choice changed during the reads; do not overwrite it.')
    record=copy.deepcopy(state['record'])
    record['infrastructure']['plumbing']=dict(project_uuid=state['project_uuid'],docktail_uuid=state['docktail_uuid'],
        canary_uuid=state['register_uuid'],tailnet_service_name=state['config']['canary_name'])
    validate_record(reader,record)
    return record


def record_created(state, reader):
    record=record_candidate(state,reader)
    save(state['choice_path'],record)
    return record


def wait_canary(definition, reachable, name, limit=300, interval=5):
    deadline=time.monotonic()+limit
    reason='The canary definition is absent.'
    while True:
        try:
            observed=definition(name)
        except urllib.error.HTTPError as error:
            raise OperationRefused('Canary definition read failed with HTTP '+str(error.code)+'.') from None
        if observed is not None:
            if not isinstance(observed,dict) or observed.get('ports')!=['tcp:443']:
                raise OperationRefused('The canary declares different ports; separate repair approval is required.')
            try:
                if reachable(): return
                reason='The canary HTTPS response is not 200.'
            except (OSError,TimeoutError):
                reason='The canary HTTPS connection or certificate is not ready.'
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise OperationRefused('Canary readiness timed out. '+reason+' No record attempt was made.')
        print('Waiting for the canary definition and HTTPS certificate. '+reason,flush=True)
        time.sleep(min(interval,remaining))


def recovery_context(state, step, original, reader):
    read_require(step in STEPS and state.get('uncertain') in (None,step),
            'Recovery must name the current uncertain stage.')
    effect=effect_for(dict(state,uncertain=None),step)
    read_require(reader.read_json(original)==effect, 'The original attempt effect differs from this progress.')
    journal=Path(state['choice_path']).parent/'place-attempts'
    require(state['journal']==journal_identity(journal,create=False), JOURNAL_MESSAGE)
    receipt=journal/(fingerprint(effect)+'.json')
    require(not receipt.is_symlink(), 'The attempt receipt must not be a symlink.')
    saved=reader.read_json(receipt)
    read_require(saved.get('effect_sha256')==fingerprint(effect) and saved.get('status')=='uncertain',
            'Recovery needs the matching uncertain receipt; a closed receipt cannot be reused.')
    return effect,receipt,saved


def recovery_effect(state, step, original, reader, abandon):
    effect,receipt,saved=recovery_context(state,step,original,reader)
    require(abandon or step=='claim', 'Only the administrator claim can be completed by this recovery.')
    return dict(action='place-abandon' if abandon else 'place-recover-claim',journal=state['journal'],
        progress_sha256=fingerprint(state),place_sha256=fingerprint(state['record']),
        receipt_sha256=fingerprint(saved),attempt_sha256=fingerprint(effect),step=step,
        effect=('Record the '+step+' attempt as abandoned only with proof that no write occurred. Keep its spent receipt marked not-written. A new attempt needs a new effect and approval. No host or access changes.' if abandon else
                'Repeat the administrator claim checks and typed confirmation. Complete only this uncertain claim and its receipt if every check passes. No host or access changes.'))


def abandon_reason(state, step, effect, receipt, api):
    if step!='claim' and receipt.get('write_state')=='not-sent':
        return 'The runner recorded that no write was dispatched.'
    if step in ('project','docktail','register'):
        team=api.coolify_team()
        read_require(receipt.get('coolify_team_id') is not None and isinstance(team,dict)
                     and team.get('id')==receipt['coolify_team_id'],
                     'An absence read needs the same Coolify team recorded at the attempt; the stage stays uncertain.')
        kind='projects' if step=='project' else 'services'
        rows=api.coolify_resources(kind)
        read_require(isinstance(rows,list) and all(isinstance(row,dict) and isinstance(row.get('name'),str) for row in rows),
                'The resource inventory could not prove absence; the attempt stays uncertain.')
        read_require(not any(row['name']==effect['arguments']['name'] for row in rows),
                'The named resource exists; the attempt stays uncertain.')
        return 'A complete Coolify inventory contains no resource with the approved name.'
    raise OperationRefused('No retained evidence proves that this write was not sent. The attempt stays uncertain.')


def bind_provider(state, plan, token, gate, remember=False):
    checksum=gate.digest(Path(plan).read_bytes())
    expected=fingerprint(token)
    if remember:
        state.setdefault('provider_plans',{})[checksum]=expected
    else:
        require(state.get('provider_plans',{}).get(checksum)==expected,
                'The project token differs from the one used for this saved plan. Save and approve a new plan.')


@contextmanager
def progress_lock(progress):
    """Keep setup reads and writes of one progress file in the same order."""
    try:
        descriptor=os.open(str(progress)+'.lock',os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,0o600)
    except OSError:
        raise OperationRefused('The progress lock could not be opened. Check its path before retrying.') from None
    try:
        info=os.fstat(descriptor)
        read_require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid(),
                     'The progress lock must be a regular file owned by you.')
        try: fcntl.flock(descriptor,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise OperationRefused('Another setup command is using this progress file. Wait for it to finish.') from None
        yield
    finally: os.close(descriptor)


@contextmanager
def plan_folder(gate, name):
    """Serialise numbered paths in an owner-only folder outside repositories."""
    read_require(isinstance(name,str) and re.fullmatch(r'[a-z][a-z0-9-]{0,61}[a-z0-9]',name),
            'Use a plain approved place name for saved plans.')
    folder=Path.home()/'.local/share/ai-host-kit/plans'/name
    for part in reversed([folder,*folder.parents]):
        read_require(not part.is_symlink(), 'The saved-plan folder must not use symlinks.')
    folder.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    folder.mkdir(exist_ok=True,mode=0o700)
    for part in (folder,folder.parent):
        info=part.stat()
        read_require(info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o700,
                'The kit plans folder and place folder must belong to you with mode 700.')
    descriptor=os.open(folder,os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    reason='Keep the kit plans folder outside every Git repository.'
    try:
        gate.secrets_directory_safe(descriptor,folder/'unused',reason=reason)
        lock=os.open('.lock',os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,0o600,dir_fd=descriptor)
        try:
            read_require(stat.S_ISREG(os.fstat(lock).st_mode) and os.fstat(lock).st_uid==os.getuid(),
                    'The plan lock must be a regular file owned by you.')
            try: fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise OperationRefused('Another plan command is running for this place. Wait for it to finish.') from None
            gate.secrets_directory_safe(descriptor,folder/'unused',reason=reason)
            yield folder
        finally: os.close(lock)
    finally: os.close(descriptor)


def numbered_path(folder, stem, suffix):
    numbers=[]
    pattern=re.compile(re.escape(stem)+r'-([1-9][0-9]*)'+re.escape(suffix)+r'(?:\.identity\.json)?')
    for path in folder.iterdir():
        match=pattern.fullmatch(path.name)
        if match: numbers.append(int(match[1]))
    return str(folder/(stem+'-'+str(max(numbers,default=0)+1)+suffix))


def superseded_plans(folder, current):
    current=Path(current)
    match=re.fullmatch(r'(create|destroy)-([1-9][0-9]*)\.plan',current.name)
    if current.parent!=folder or not match: return []
    candidates=[]
    for path in folder.iterdir():
        old=re.fullmatch(match[1]+r'-([1-9][0-9]*)\.plan',path.name)
        if old and int(old[1])<int(match[2]) and path.is_file() and not path.is_symlink():
            candidates.append(path)
    return sorted(candidates,key=lambda path:int(path.stem.rsplit('-',1)[1]))


def prune_plans(gate, folder, current):
    read_require(Path(current).is_file() and not Path(current).is_symlink(),
                 'The newer saved plan is missing or is a symlink. Keep the older plans until a newer plan can be reviewed.')
    paths=superseded_plans(folder,current)
    if not paths:
        print('No superseded plans for this place and operation.'); return
    with gate.terminal() as tty:
        tty.write('Superseded plans for this place and operation:\n'+''.join(str(path)+'\n' for path in paths))
        tty.write('A plan can hold a spent key. Deleting these plans and their identity sidecars cannot be undone. Approval records and receipts are kept.\n')
        answer=gate.typed(tty,'Type delete to remove these plans, or Enter to keep them (shown): ',optional=True)
        read_require(answer in ('','delete'), 'Use delete or Enter. No plans were removed.')
        if not answer:
            print('Kept the superseded plans.'); return
        for path in paths:
            identity=gate.identity_path(path)
            read_require(not path.is_symlink() and not identity.is_symlink(), 'A plan path changed. No further plans were removed.')
            path.unlink()
            identity.unlink(missing_ok=True)
        print('Deleted the listed superseded plans and identity sidecars. Approval records and receipts were kept.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['root','init','plan','summary','approve','apply','bootstrap','prepare','run','candidate','discover','plan-destroy','retire','prepare-recovery','recover','prune-plans'])
    parser.add_argument('--partial',action='store_true')
    parser.add_argument('--abandon',action='store_true')
    parser.add_argument('--attempt-effect')
    parser.add_argument('--config'); parser.add_argument('--choice',default='hosting/place-record.json')
    parser.add_argument('--secrets')
    parser.add_argument('--directory',default='hosting/tofu'); parser.add_argument('--progress',default='hosting/place-progress.json')
    parser.add_argument('--plan'); parser.add_argument('--approval'); parser.add_argument('--effect')
    parser.add_argument('--step',choices=STEPS); parser.add_argument('--address'); parser.add_argument('--mcp-package')
    parser.add_argument('--server-uuid'); parser.add_argument('--destination-uuid'); parser.add_argument('--canary-url')
    args=parser.parse_args(); locks=ExitStack(); client=None; state=None; gate=None; previous_directory=Path.cwd()
    if args.secrets: args.secrets=str(Path(args.secrets).expanduser().absolute())
    for field in ('plan','approval','effect','choice','mcp_package','attempt_effect'):
        value=getattr(args,field)
        if value: setattr(args,field,str(Path(value).resolve()))
    try:
        reader=load_reader(); gate=approval_gate()
        if args.command=='root':
            require(args.config is not None, 'Supply the non-secret setup settings.')
            config=reader.read_json(args.config)
            if args.secrets: config['secrets']=args.secrets
            prepare_root(config,args.choice,args.directory,args.progress,reader,gate); return 0
        progress=Path(args.progress).resolve()
        locks.enter_context(progress_lock(progress))
        state=reader.read_json(progress)
        planning=args.command in ('plan','plan-destroy')
        plan_command=args.command in ('summary','approve','apply','retire','prune-plans')
        folder=None
        if ((planning or plan_command) and not args.plan) or (args.command=='approve' and not args.approval) or args.command=='prune-plans':
            folder=locks.enter_context(plan_folder(gate,state['config']['place']['name']))
            state=reader.read_json(progress)
            read_require(state['config']['place']['name']==folder.name, 'The place name changed while taking the plan lock. Inspect the progress file before retrying.')
        gate.configure_secrets(args.secrets or state['config'].get('secrets'),state['config']['place']['name'])
        root=Path(state['root']); record=state.get('record')
        if planning and not args.plan:
            args.plan=numbered_path(folder,'destroy' if args.command=='plan-destroy' else 'create','.plan')
        if plan_command and not args.plan:
            args.plan=state.get('saved_plan')
            require(args.plan, 'Save a plan for this place before reviewing, approving or applying it.')
        if args.command=='approve' and not args.approval:
            args.approval=numbered_path(folder,'approval','.json')
        elif args.command in ('apply','retire') and not args.approval:
            args.approval=state.get('saved_approval')
        if args.command=='prune-plans':
            prune_plans(gate,folder,args.plan); return 0

        if args.command in ('run','prepare-recovery','recover','discover'):
            locks.enter_context(place_lock(record))
            state=reader.read_json(progress); record=state.get('record')
            require(state['journal']==journal_identity(Path(state['choice_path']).parent/'place-attempts',create=False),
                    'Receipt journal is missing or replaced. Inspect the live state and approve afresh.')
        if args.command in ('prepare-recovery','recover'):
            validate_record(reader,record)
            require(args.step and args.attempt_effect and args.effect, 'Name the stage, original attempt effect and recovery effect path.')
            recovery=recovery_effect(state,args.step,args.attempt_effect,reader,args.abandon)
            if args.command=='prepare-recovery':
                write_record(recovery,args.effect,lambda value:None); print('Prepared recovery. Run approve-effect to review it and decide.'); return 0
            require(args.approval and reader.read_json(args.effect)==recovery, 'The recovery effect differs from current progress or receipt.')
            gate.match_effect(recovery,args.approval)
            original,receipt,saved=recovery_context(state,args.step,args.attempt_effect,reader)
            if args.abandon:
                token=prompt(gate,'Coolify scoped token')
                api=API(record,'',token)
                reason=abandon_reason(state,args.step,original,saved,api)
                saved['status']='not-written'; saved['reason']=reason
                # Close first. A crash here blocks another recovery rather than
                # allowing the consumed approval to become usable again.
                save(receipt,saved)
                state.setdefault('abandoned_attempts',[]).append(dict(step=args.step,receipt=receipt.name,reason=reason))
                state['uncertain']=None; save(progress,state)
                print('Recorded the abandoned attempt. Prepare a new effect and obtain fresh approval.'); return 0
            print('The Hetzner project token reads the firewall to confirm that inbound access is closed.')
            hcloud=prompt(gate,'Hetzner project token')
            token=prompt(gate,'Coolify scoped token')
            api=API(record,hcloud,token)
            observed=api.token_abilities()
            if observed is not None:
                try: scoped_mcp(observed,PINS['mcp'])
                except ValueError: raise OperationRefused('Coolify reports token abilities outside the required team scopes; the claim stays uncertain.') from None
            else: print('Coolify reports no current-token abilities; check the declared scopes in Coolify.')
            answer=prompt(gate,'After creating your own account, type claimed '+record['place']['name'])
            check_claim(record,api,lambda name:answer)
            state['done'].append('claim'); state['uncertain']=None; save(progress,state)
            finish_attempt(receipt)
            print('Completed the checked administrator claim and its receipt.'); return 0
        if args.command=='prepare':
            require(args.step and args.effect, 'Name the stage and new effect path.')
            effect=effect_for(state,args.step)
            write_record(effect,args.effect,lambda value:None); print('Prepared the effect. Run approve-effect to review it and decide.')
            if args.step=='claim': print('After approval, run this stage. It records the attempt before restarting Coolify, then guides you through the claim.')
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
                if args.partial: sys.argv += ['--partial-progress',str(progress)]
                return retire.main(gate=gate, token=os.environ['TF_VAR_hcloud_token'])
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
                os.environ['TF_VAR_tailnet_auth_key']=prompt(gate,'Single-use pre-approved non-ephemeral tag:server Tailscale key, shortest available expiry (one day, Tailscale\'s shortest option)')
                gate.plan(args.plan)
                bind_provider(state,args.plan,os.environ['TF_VAR_hcloud_token'],gate,remember=True)
                state['saved_plan']=args.plan; state.pop('saved_approval',None); save(progress,state)
                print('Saved plan: '+args.plan)
                if folder and superseded_plans(folder,args.plan):
                    print('Older plans remain and can hold a spent key. Run prune-plans with this progress file to review them and choose whether to delete them.')
            elif args.command=='plan-destroy':
                require(args.plan, 'Supply a new destroy-plan path.')
                os.environ['TF_VAR_hcloud_token']=prompt(gate,'Hetzner project token')
                # Destroy does not enrol a node. Satisfy the required input with
                # an inert synthetic marker rather than request the spent key.
                os.environ['TF_VAR_tailnet_auth_key']='tskey-auth-unused-destroy-only'
                if args.partial:
                    shown=gate.tofu('show','-json')
                    require(shown.returncode==0, 'Read the encrypted partial state before recovery.')
                    state['recovery_record']=partial_record(state,json.loads(shown.stdout)['values'])
                gate.plan(args.plan,destroy=True)
                bind_provider(state,args.plan,os.environ['TF_VAR_hcloud_token'],gate,remember=True)
                state['saved_plan']=args.plan; state.pop('saved_approval',None); save(progress,state)
                print('Saved plan: '+args.plan)
                if folder and superseded_plans(folder,args.plan):
                    print('Older plans remain and can hold a spent key. Run prune-plans with this progress file to review them and choose whether to delete them.')
            elif args.command=='summary':
                require(args.plan, 'Supply the saved-plan path.')
                with gate.saved_plan(args.plan) as (snapshot,sha):
                    target=gate.planned_identity(args.plan,sha)
                    print(gate.render(sha,gate.read_plan(snapshot),target))
            elif args.command=='approve':
                require(args.plan and args.approval, 'Supply plan and new approval paths.')
                gate.approve(args.plan,args.approval)
                state['saved_plan']=args.plan; state['saved_approval']=args.approval; save(progress,state)
                print('Saved approval: '+args.approval)
            else:
                require(args.plan and args.approval and not state.get('applied'), 'Supply the approved plan; do not apply a place twice.')
                os.environ['TF_VAR_hcloud_token']=prompt(gate,'Hetzner project token')
                bind_provider(state,args.plan,os.environ['TF_VAR_hcloud_token'],gate)
                # Check approval before recording uncertainty, and let apply check again.
                with gate.saved_plan(args.plan) as (snapshot,sha):
                    approved=gate.validate_record(args.approval)
                    gate.match_record(approved,sha,gate.read_plan(snapshot))
                    gate.match_target(approved,gate.planned_identity(args.plan,sha))
                state['uncertain']='apply'; save(progress,state)
                gate.apply(args.plan,args.approval)
                result=gate.tofu('output','-json')
                require(result.returncode==0,'Read the created resource identities before continuing.')
                outputs=json.loads(result.stdout)
                state['outputs']={key:outputs[key]['value'] for key in ('server_id','firewall_id','ssh_key_id','ipv4_address')}
                state['applied']=True; state['uncertain']=None; save(progress,state)
                print('Applied the approved plan. Three resources exist. Cloud-init takes several minutes; bootstrap waits for it to finish. Run bootstrap with this progress file next, then prepare the administrator claim. Keep the encrypted state for retirement.')
            return 0
        if args.command=='bootstrap':
            require(state.get('applied') and not state['done'],
                    'Apply first, then run bootstrap before the administrator claim.')
            if not args.address:
                args.address=bootstrap_address(state['config']['place']['name'])
            outputs=state['outputs']; config=state['config']; choice=reader.read_json(state['choice_path'])
            require(fingerprint(choice)==state['choice_sha256'],'The saved choice changed; inspect it before continuing.')
            record=dict(schema_version='1.0',phase='place',place=config['place'],choice=choice['choice'],
                network=dict(cidrs=['100.64.0.0/10'],private_access='Tailscale'),firewall=dict(default_inbound='deny',rules=[]),
                tools=[],encrypted_state=config['encrypted_state'],infrastructure=dict(
                    server_id=int(outputs['server_id']),firewall_id=int(outputs['firewall_id']),ssh_key_id=int(outputs['ssh_key_id']),
                    journal=state['journal'],public_ipv4=outputs['ipv4_address'],tailnet_ipv4=tailnet_address(args.address),versions=PINS))
            validate_record(reader,record)
            try:
                facts=wait_bootstrap(record,read_node)
            except BootstrapFailed as error:
                print(str(error),file=sys.stderr)
                return 1
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
            read_require(server.get('ip') in ('127.0.0.1','localhost','host.docker.internal') and server.get('name')=='localhost',
                    "Coolify's built-in server must be named localhost and use a loopback address or host.docker.internal; remote servers are refused.")
            destinations=api.request('GET','http://'+address+':8000/api/v1/servers/'+args.server_uuid+'/destinations',token)
            require(any(item.get('uuid')==args.destination_uuid for item in destinations), 'The destination does not belong to the selected server.')
            state.update(server_uuid=args.server_uuid,destination_uuid=args.destination_uuid); save(progress,state)
            print('Recorded the read-back localhost server and Docker destination.'); return 0
        require(args.step and args.approval and args.effect,'Name the stage, prepared effect and approval.')
        effect=effect_for(state,args.step)
        require(reader.read_json(args.effect)==effect,'The prepared effect differs from the current stage.')
        gate.match_effect(effect,args.approval)
        state_before=copy.deepcopy(state)
        claim_answer=None; claim_token=None; hcloud=''; receipt=None
        if args.step=='claim':
            print('The Hetzner project token reads the firewall to confirm that inbound access is closed.')
            hcloud=prompt(gate,'Hetzner project token')
            if getattr(gate,'SECRET_VALUES',{}).get('COOLIFY_TEAM_TOKEN'):
                claim_token=prompt(gate,'Coolify token with read, read:sensitive, write and deploy, never root or delete')
            api=API(record,hcloud)
            read_require(api.firewall_rules(record['infrastructure']['firewall_id'])==[], 'Keep all inbound rules closed until the claim is confirmed.')
            read_require(api.registration_state() != 'claimed', 'Coolify already has an administrator. Inspect the existing claim; no restart was sent.')
            # The person must be able to confirm the claim before its effect is spent.
            with gate.terminal(): pass
            receipt=start_attempt(effect,args.approval,Path(state['choice_path']).parent/'place-attempts')
            state['uncertain']='claim'; save(progress,state)
            reopen_claim(record['infrastructure']['tailnet_ipv4'])
            def check_window():
                if api.registration_state() == 'window-closed':
                    # The page proves that first-account registration is closed,
                    # not that an administrator exists. Retain the spent effect.
                    reason='Coolify setup window closed. The restart completed, but no administrator was claimed. Prepare a new claim effect and obtain fresh approval to reopen the ten-minute window.'
                    saved=json.loads(receipt.read_text()); saved.update(status='not-claimed',reason=reason)
                    save(receipt,saved)
                    state.setdefault('unclaimed_attempts',[]).append(dict(receipt=receipt.name,reason=reason))
                    state['uncertain']=None; save(progress,state)
                    raise OperationRefused(reason)
            check_window()
            print('Coolify is healthy. Open http://'+record['infrastructure']['tailnet_ipv4']+':8000/register now. You have ten minutes from the container restart to create the first administrator. The password goes only into Coolify.')
            print('On Welcome to Coolify, choose Skip setup. Enable two-factor authentication: avatar > Profile > Configure 2FA. Switch on Settings > Advanced > API and MCP > API access. At Keys & Tokens > API Tokens > New token, select Read, Write, Deploy and Read sensitive data, never Root or Delete.')
            claim_answer=prompt(gate,'After creating your own account, type claimed '+record['place']['name'])
            check_window()
            read_require(claim_answer=='claimed '+record['place']['name'], 'The person must confirm their own administrator claim.')
        token=claim_token or prompt(gate,'Coolify token with read, read:sensitive, write and deploy, never root or delete')
        service_key=prompt(gate,'Tailscale API read token for service definitions') if args.step in ('register','start-register','record') else None
        oauth_value=prompt(gate,'TAILSCALE_OAUTH_CLIENT_'+('ID' if args.step=='oauth-id' else 'SECRET')) if args.step in ('oauth-id','oauth-secret') else None
        api=API(record,hcloud,token)
        observed=api.token_abilities()
        if observed is not None: scoped_mcp(observed,PINS['mcp'])
        else: print('Coolify does not expose current-token abilities here. The scope setting remains a declaration; check it in Coolify before proceeding.')
        team=api.coolify_team()
        read_require(isinstance(team,dict) and type(team.get('id')) is int and team['id']>=0,
                     'Coolify must return a team identity before completing the claim or recording a later write attempt.')
        if args.step not in ('claim','record'):
            require(args.mcp_package,'Supply the installed pinned MCP package.json path.')
            client=MCP(args.mcp_package,record['infrastructure']['tailnet_ipv4'],token,state['config']['scopes'],observed)
        def confirm(name):
            return claim_answer
        def definition(name):
            import urllib.error
            try: return api.request('GET','https://api.tailscale.com/api/v2/tailnet/-/services/svc:'+name,service_key)
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
            wait_canary(definition,reachable,state['config']['canary_name'])
            run_stage(state,args.step,args.approval,gate,api,None,confirm,definition,reachable)
            candidate=record_candidate(state,reader)
        # Writes are not retried automatically if the process or read-back fails.
        if receipt is None: receipt=start_attempt(effect,args.approval,Path(state['choice_path']).parent/'place-attempts',not_sent=args.step!='claim',coolify_team_id=team['id'])
        state['uncertain']=args.step; save(progress,state)
        if args.step=='record':
            mark_dispatch(receipt)
            save(state['choice_path'],candidate); state['record']=candidate; update={}
        else:
            update=run_stage(state_before,args.step,args.approval,gate,api,client,confirm,definition,reachable,oauth_value,lambda:mark_dispatch(receipt))
        state.update(update); state['done'].append(args.step); state['uncertain']=None; save(progress,state)
        finish_attempt(receipt)
        print('Completed '+args.step+'. The place remains empty; use /check-live to read it.')
        return 0
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as error:
        if args.command in ('recover','prepare-recovery','discover') and type(error) is ValueError: print('Recovery or discovery checks failed; the stage and receipt were not completed.',file=sys.stderr)
        from api import report_refusal
        report_refusal(error, locals().get('gate'))
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
        print('Stopped: setup inputs, approval or transport failed; values withheld. Before apply, no provider resources are expected. After an attempted apply, the server, firewall and SSH key may exist. Keep the progress file and encrypted state. Export a candidate record if bootstrap passed, then use retire.py with an approved destroy plan. For a partial apply, use plan-destroy --partial and retire --partial with a fresh saved-plan approval. Do not retry an uncertain write or remove console leftovers without separate approval.',file=sys.stderr)
        return 1
    finally:
        locks.close()
        os.chdir(previous_directory)
        if client is not None: client.close()
        for key in ('TF_VAR_host_state_passphrase','TF_VAR_hcloud_token','TF_VAR_tailnet_auth_key'):
            os.environ.pop(key,None)


if __name__=='__main__': sys.exit(main())
