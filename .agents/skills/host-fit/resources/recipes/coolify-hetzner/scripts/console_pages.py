"""Versioned console guidance, without a browser automation dependency."""
import json
import os
from pathlib import Path
import subprocess
import sys
from place import tailnet_address


MAP = Path(__file__).resolve().parent.parent/'console-pages.json'
SECRET_PAGES = {
    'HETZNER_PROJECT_TOKEN': 'hetzner.project-token',
    'STORAGE_ACCESS_KEY': 'hetzner.storage-keys',
    'STORAGE_SECRET_KEY': 'hetzner.storage-keys',
    'TAILSCALE_AUTH_KEY': 'tailscale.auth-key',
    'TAILSCALE_API_TOKEN': 'tailscale.access-token',
    'TAILSCALE_READ_CLIENT_ID': 'tailscale.read-credential',
    'TAILSCALE_READ_CLIENT_SECRET': 'tailscale.read-credential',
    'TAILSCALE_OAUTH_CLIENT_ID': 'tailscale.docktail-credential',
    'TAILSCALE_OAUTH_CLIENT_SECRET': 'tailscale.docktail-credential',
    'COOLIFY_TEAM_TOKEN': 'coolify.team-token',
}


def entry(key):
    provider, name = key.split('.')
    return json.loads(MAP.read_text())['providers'][provider]['entries'][name]


def open_url(url):
    command = ['open', url] if sys.platform == 'darwin' else ['xdg-open', url]
    try:
        result = subprocess.run(command, env={'PATH': os.environ.get('PATH', '')},
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if result.returncode: print('The system opener could not open the page. Use the printed URL.')
    except (OSError, subprocess.TimeoutExpired):
        print('The system opener is unavailable. Use the printed URL.')


def show(key, context=None, launch=False):
    provider, name = key.split('.')
    source = json.loads(MAP.read_text())['providers'][provider]
    item = source['entries'][name]
    context = dict(dict(place='<place>', canary='<canary>', address='<tailnet-ip>'), **(context or {}))
    if context['address'] != '<tailnet-ip>': tailnet_address(context['address'])
    url = item['url'].format_map(context)
    label = {'hetzner':'Hetzner','tailscale':'Tailscale','coolify':'Coolify'}[provider]
    print(label+' console ('+source['version']+'): '+url, flush=True)
    for field, label in [('menu_path','Menu'), ('button','Button'), ('field','Field'), ('note','Guidance')]:
        print(label+': '+item[field].format_map(context), flush=True)
    print('Value shown only once: '+('yes' if item['shown_once'] else 'no')+'.', flush=True)
    for lines in item.get('required_lines',{}).values():
        print('Policy lines to merge after approval: '+json.dumps(lines),flush=True)
    if launch:
        if '<tailnet-ip>' in url: print('Supply the checked tailnet address to open this page.')
        else: open_url(url)


def configure(gate, record=None, config=None):
    context = {}
    if config: context.update(place=config['place']['name'], canary=config.get('canary_name','<canary>'))
    if record:
        context.update(place=record['place']['name'])
        if record['infrastructure'].get('tailnet_ipv4'):
            context['address'] = record['infrastructure']['tailnet_ipv4']
        context.setdefault('canary', record['infrastructure'].get('plumbing',{}).get('tailnet_service_name','<canary>'))
    def guide(key):
        if key == 'CLAIM':
            for page in ('claim','two-factor','api-access','team-token'):
                show('coolify.'+page,context,launch=True)
        if key in SECRET_PAGES: show(SECRET_PAGES[key], context, launch=True)
    gate.CONSOLE_GUIDANCE = guide
    return context
