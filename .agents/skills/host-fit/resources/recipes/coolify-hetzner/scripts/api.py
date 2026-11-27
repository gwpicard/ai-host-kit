"""Fixed-route transports. Keys are supplied in memory; responses are never logged."""
import base64
import json
import re
import urllib.request
from urllib.parse import quote
from check import NoRedirect
from place import Refused, require, tailnet_address

# The kit version, stamped when a release is prepared.
KIT_VERSION = '0.0.1'

# The Coolify 4.7.5 write routes the kit calls, with the request fields each
# route reads. The project and service routes answer 422 to any other field.
# The service variable routes accept any other field and drop it unread, which
# includes is_buildtime, is_runtime and is_preview. The kit refuses such a
# field instead of sending it. Sources: ProjectController::create_project and
# ServicesController::create_service, create_env, update_env_by_uuid and
# action_deploy at v4.7.5.
SERVICE_VARIABLE_FIELDS = frozenset({'key', 'value', 'is_literal', 'is_multiline', 'is_shown_once', 'comment'})
COOLIFY_WRITES = {
    ('POST', 'projects'): frozenset({'name', 'description'}),
    ('POST', 'services'): frozenset({'name', 'description', 'project_uuid', 'environment_name', 'environment_uuid',
                                     'server_uuid', 'destination_uuid', 'instant_deploy', 'docker_compose_raw',
                                     'connect_to_docker_network', 'urls', 'force_domain_override',
                                     'is_container_label_escape_enabled', 'redact_all_env_values_in_logs', 'tags'}),
    ('POST', 'services/{uuid}/envs'): SERVICE_VARIABLE_FIELDS,
    ('PATCH', 'services/{uuid}/envs'): SERVICE_VARIABLE_FIELDS,
    ('POST', 'services/{uuid}/start'): frozenset(),
}


def approval_gate():
    import importlib.util
    from pathlib import Path
    for parent in Path(__file__).resolve().parents:
        path = parent/'setup-hosting/scripts/approval_gate.py'
        if path.is_file():
            spec=importlib.util.spec_from_file_location('gate',path)
            gate=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gate)
            return gate
    raise Refused('The installed approval gate is missing.')


def hidden_value(gate, label):
    if 'type claimed' in label:
        with gate.terminal() as tty:
            if getattr(gate,'CONSOLE_GUIDANCE',None): gate.CONSOLE_GUIDANCE('CLAIM')
            return gate.typed(tty,label+' (shown): ',expected=label.rsplit('type ',1)[1])
    if label == 'State passphrase': key='STATE_PASSPHRASE'
    elif label == 'Hetzner project token': key='HETZNER_PROJECT_TOKEN'
    elif label.startswith('Single-use'): key='TAILSCALE_AUTH_KEY'
    elif label.startswith('Tailscale API'): key='TAILSCALE_API_TOKEN'
    elif label.startswith('Coolify'): key='COOLIFY_TEAM_TOKEN'
    elif label in ('TAILSCALE_OAUTH_CLIENT_ID','TAILSCALE_OAUTH_CLIENT_SECRET'): key=label
    else: raise Refused('Unknown secret input label.')
    value=gate.secret(key,label,shown=key=='TAILSCALE_OAUTH_CLIENT_ID')
    if not value: raise gate.InputRefused('A required input was empty.')
    if key=='STATE_PASSPHRASE' and len(value)<16:
        raise gate.InputRefused('Use a state passphrase of at least 16 characters.')
    return value


def secrets_options(parser):
    parser.add_argument('--secrets')
    parser.add_argument('--config',default='setup.json')


def configure_place_secrets(gate, args, record):
    from pathlib import Path
    config=Path(args.config)
    settings=json.loads(config.read_text()) if config.is_file() else {}
    gate.configure_secrets(args.secrets or settings.get('secrets'),record['place']['name'])
    from console_pages import configure
    return configure(gate, record, settings if 'place' in settings and 'canary_name' in settings else None)


class API:
    def __init__(self, record, hcloud_token, coolify_token=None):
        self.record=record
        self.hcloud_token=hcloud_token
        self.coolify_token=coolify_token
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def request(self, method, url, token, body=None):
        data=None if body is None else json.dumps(body).encode()
        request=urllib.request.Request(url,data=data,method=method,
                headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json',
                         'User-Agent':'ai-host-kit/'+KIT_VERSION})
        with self.opener.open(request,timeout=20) as response:
            return json.loads(response.read(4*1024*1024))

    def coolify_url(self, path):
        return 'http://'+tailnet_address(self.record['infrastructure']['tailnet_ipv4'])+':8000/api/v1/'+path

    def coolify_version(self):
        """Read the running Coolify version. 4.7.5 answers with plain text."""
        request=urllib.request.Request(self.coolify_url('version'),method='GET',
                headers={'Authorization':'Bearer '+self.coolify_token,'User-Agent':'ai-host-kit/'+KIT_VERSION})
        with self.opener.open(request,timeout=20) as response:
            text=response.read(4096).decode('utf-8',errors='replace').strip()
        try: value=json.loads(text)
        except ValueError: value=text
        return value if isinstance(value,str) and re.fullmatch(r'[0-9A-Za-z.-]{1,40}',value) else None

    def coolify_write(self, method, route, body=None, uuid=None):
        """Send one fixed Coolify write. Return only a created identity, never a value."""
        fields=COOLIFY_WRITES.get((method,route))
        require(fields is not None, 'The kit has no fixed Coolify write route for this request; nothing was sent.')
        body=dict(body or {})
        require(set(body) <= fields,
                'The request names a field that Coolify 4.7.5 ignores or refuses on this route; nothing was sent.')
        require(('{uuid}' in route) == (uuid is not None) and (uuid is None or (isinstance(uuid,str) and bool(uuid))),
                'A Coolify write needs exactly the resource identity its route names; nothing was sent.')
        if 'docker_compose_raw' in body:
            # The 4.7.5 service route accepts Compose only as base64 text.
            body['docker_compose_raw']=base64.b64encode(body['docker_compose_raw'].encode()).decode()
        path=route.replace('{uuid}',quote(uuid,safe='')) if uuid is not None else route
        request=urllib.request.Request(self.coolify_url(path),data=json.dumps(body).encode(),method=method,
                headers={'Authorization':'Bearer '+self.coolify_token,'Content-Type':'application/json',
                         'Accept':'application/json','User-Agent':'ai-host-kit/'+KIT_VERSION})
        with self.opener.open(request,timeout=30) as response:
            status=response.status
            raw=response.read(64*1024)
        require(200 <= status < 300, 'Coolify answered the write without success; inspect the place before retrying.')
        if (method,route) not in (('POST','projects'),('POST','services')):
            # Variable writes echo the stored value. Discard the reply unread.
            return None
        # Reduce the reply at the boundary: only the new identity leaves here.
        try: identity=json.loads(raw).get('uuid')
        except (ValueError, AttributeError): identity=None
        require(isinstance(identity,str) and re.fullmatch(r'[A-Za-z0-9-]{1,64}',identity) is not None,
                'The Coolify write returned no identity; inspect the place before retrying.')
        return identity

    def create_project(self, name):
        return self.coolify_write('POST','projects',dict(name=name))

    def create_service(self, fields):
        return self.coolify_write('POST','services',fields)

    def set_service_variable(self, method, uuid, key, value):
        # Only key and value are sent. Coolify keeps the deployment flags it
        # set when it parsed the Compose definition.
        self.coolify_write(method,'services/{uuid}/envs',dict(key=key,value=value),uuid)

    def start_service(self, uuid):
        self.coolify_write('POST','services/{uuid}/start',None,uuid)

    def cloud(self, method, path, body=None):
        return self.request(method,'https://api.hetzner.cloud/v1/'+path,self.hcloud_token,body)

    def owned_resources(self, partial=False):
        infra=self.record['infrastructure']
        return {kind:self.cloud('GET',plural+'/'+str(infra[kind+'_id']))[kind]
                for kind,plural in [('server','servers'),('firewall','firewalls'),('ssh_key','ssh_keys')]
                if not partial or kind+'_id' in infra}

    def coolify_team(self):
        address=tailnet_address(self.record['infrastructure']['tailnet_ipv4'])
        return self.request('GET','http://'+address+':8000/api/v1/team',self.coolify_token)

    def service_env_rows(self, uuid, key):
        # Reduce raw response values at the transport boundary. Callers receive
        # only presence and deployment flags, never a value or its last digits.
        rows=self.request('GET',self.coolify_url('services/'+quote(uuid,safe='')+'/envs'),self.coolify_token)
        if not isinstance(rows,list): return None
        return [dict(is_set=isinstance(row.get('value'),str) and bool(row['value']),
                     is_runtime=row.get('is_runtime'),is_buildtime=row.get('is_buildtime'),is_preview=row.get('is_preview'))
                for row in rows if isinstance(row,dict) and row.get('key')==key]

    def service_env_state(self, uuid, key):
        rows=self.service_env_rows(uuid,key)
        return None if rows is None else [row for row in rows if row['is_preview'] is False]

    def coolify_resources(self, kind):
        from place import require
        require(kind in ('projects','services'), 'Use a supported recovery inventory.')
        address=tailnet_address(self.record['infrastructure']['tailnet_ipv4'])
        rows=[]; seen=set()
        reason='The resource inventory could not prove completeness; the attempt stays uncertain.'
        # Request page/per_page and read through an empty terminal page, even
        # after a short page. Reject ignored pagination, duplicate identities
        # and unbounded inventories.
        for page in range(1,1001):
            batch=self.request('GET','http://'+address+':8000/api/v1/'+kind+
                               '?page='+str(page)+'&per_page=50',self.coolify_token)
            require(isinstance(batch,list) and len(batch)<=50 and all(
                isinstance(row,dict) and isinstance(row.get('name'),str) and
                isinstance(row.get('uuid'),str) and row['uuid'] for row in batch),reason)
            if not batch: return rows
            identities=[row['uuid'] for row in batch]
            require(len(set(identities))==len(identities) and not seen.intersection(identities),reason)
            seen.update(identities); rows.extend(batch)
        require(False,reason)

    def registration_state(self):
        import urllib.error
        from urllib.parse import urljoin
        address=tailnet_address(self.record['infrastructure']['tailnet_ipv4'])
        class Stop(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args): return None
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),Stop())
        base='http://'+address+':8000'
        try:
            with opener.open(base+'/register',timeout=10) as response:
                page=response.read(256*1024).decode('utf-8',errors='replace')
                return 'window-closed' if 'setup window closed' in page.lower() else 'open'
        except urllib.error.HTTPError as error:
            if error.code in (301,302,303) and urljoin(base+'/',error.headers.get('Location','')) == base+'/login':
                return 'claimed'
            raise

    def registration_closed(self):
        return self.registration_state() == 'claimed'

    def token_abilities(self):
        # The pinned Coolify routes have no current-token introspection route.
        # Do not invent one or mistake a successful team read for scope proof.
        team=self.coolify_team()
        if isinstance(team, dict) and 'token_abilities' in team:
            return team['token_abilities']
        return None

    def set_firewall(self, identity, rules):
        # The cloud action is asynchronous. Poll its action, then read the rules.
        import time
        action=self.cloud('POST','firewalls/'+str(identity)+'/actions/set_rules',{'rules':rules})['actions']
        for item in action:
            for _ in range(30):
                observed=self.cloud('GET','actions/'+str(item['id']))['action']
                if observed['status']=='success': break
                if observed['status']=='error': raise Refused('Firewall action failed; diagnostics withheld.')
                time.sleep(1)
            else: raise Refused('Firewall action did not complete; read the place before retrying.')

    def firewall_rules(self, identity):
        rules=self.cloud('GET','firewalls/'+str(identity))['firewall']['rules']
        return [{k:rule[k] for k in ('direction','protocol','port','source_ips')} for rule in rules]

    def inventory(self, kind):
        rows=[]
        page=1
        while True:
            query='&type=snapshot&type=backup' if kind=='images' else ''
            response=self.cloud('GET',kind+'?page='+str(page)+'&per_page=50'+query)
            rows.extend({'id':item['id']} for item in response[kind])
            page=response.get('meta',{}).get('pagination',{}).get('next_page')
            if page is None: return rows


def report_refusal(error, gate=None):
    """Report only known safe text; never include HTTP bodies or addresses."""
    import sys
    import urllib.error
    from urllib.parse import urlsplit
    from place import Refused
    if isinstance(error, Refused) or (gate is not None and isinstance(error, (gate.InputRefused, getattr(gate, 'GateRefused', gate.InputRefused)))):
        print(str(error), file=sys.stderr)
        # Details name inputs or local paths the kit chose, never a value.
        for line in getattr(error, 'details', ()):
            print(line, file=sys.stderr)
        return True
    if isinstance(error, urllib.error.HTTPError):
        host=urlsplit(error.url).hostname
        provider='Hetzner' if host == 'api.hetzner.cloud' else 'Tailscale' if host == 'api.tailscale.com' else 'Provider'
        # Any tailnet IP is the fixed Coolify transport, not a supplied label.
        try:
            tailnet_address(host)
            provider='Coolify'
        except (ValueError, TypeError): pass
        print(provider+' answered '+str(int(error.code))+'.', file=sys.stderr)
        return True
    return False
