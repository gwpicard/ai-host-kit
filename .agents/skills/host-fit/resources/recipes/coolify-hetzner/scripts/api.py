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
    with gate.terminal() as tty:
        value=gate.typed(tty,label+' (hidden): ')
    if not value: raise ValueError('A required hidden value was empty.')
    return value


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

    def registration_closed(self):
        import urllib.error
        from urllib.parse import urljoin
        address=tailnet_address(self.record['infrastructure']['tailnet_ipv4'])
        class Stop(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args): return None
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),Stop())
        base='http://'+address+':8000'
        try:
            with opener.open(base+'/register',timeout=10): return False
        except urllib.error.HTTPError as error:
            return error.code in (301,302,303) and urljoin(base+'/',error.headers.get('Location','')) == base+'/login'

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
