"""Fixed-route transports. Keys are supplied in memory; responses are never logged."""
import json
import urllib.request
from check import NoRedirect
from place import tailnet_address


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
    raise ValueError('The installed approval gate is missing.')


def hidden_value(gate, label):
    if 'type claimed' in label:
        with gate.terminal() as tty:
            return gate.typed(tty,label+' (shown): ')
    if label == 'State passphrase': key='STATE_PASSPHRASE'
    elif label == 'Hetzner project token': key='HETZNER_PROJECT_TOKEN'
    elif label.startswith('Single-use'): key='TAILSCALE_AUTH_KEY'
    elif label.startswith('Tailscale API'): key='TAILSCALE_API_TOKEN'
    elif label.startswith('Coolify'): key='COOLIFY_TEAM_TOKEN'
    elif label in ('TAILSCALE_OAUTH_CLIENT_ID','TAILSCALE_OAUTH_CLIENT_SECRET'): key=label
    else: raise ValueError('Unknown secret input label.')
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


class API:
    def __init__(self, record, hcloud_token, coolify_token=None):
        self.record=record
        self.hcloud_token=hcloud_token
        self.coolify_token=coolify_token
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def request(self, method, url, token, body=None):
        data=None if body is None else json.dumps(body).encode()
        request=urllib.request.Request(url,data=data,method=method,
                headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        with self.opener.open(request,timeout=20) as response:
            return json.loads(response.read(4*1024*1024))

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

    def service_env_state(self, uuid, key):
        # Reduce raw response values at the transport boundary. Callers receive
        # only presence and deployment flags, never a value or its last digits.
        from urllib.parse import quote
        address=tailnet_address(self.record['infrastructure']['tailnet_ipv4'])
        rows=self.request('GET','http://'+address+':8000/api/v1/services/'+quote(uuid,safe='')+'/envs',self.coolify_token)
        return [dict(is_set=isinstance(row.get('value'),str) and bool(row['value']),
                     is_runtime=row.get('is_runtime'),is_buildtime=row.get('is_buildtime'),is_preview=row.get('is_preview'))
                for row in rows if row.get('key')==key and row.get('is_preview') is False]

    def coolify_resources(self, kind):
        from place import require
        require(kind in ('projects','services'), 'Use a supported recovery inventory.')
        address=tailnet_address(self.record['infrastructure']['tailnet_ipv4'])
        return self.request('GET','http://'+address+':8000/api/v1/'+kind,self.coolify_token)

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
                if observed['status']=='error': raise ValueError('Firewall action failed; diagnostics withheld.')
                time.sleep(1)
            else: raise ValueError('Firewall action did not complete; read the place before retrying.')

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
    from place import OperationRefused
    if isinstance(error, OperationRefused) or (gate is not None and isinstance(error, (gate.InputRefused, getattr(gate, 'GateRefused', gate.InputRefused)))):
        print(str(error), file=sys.stderr)
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
