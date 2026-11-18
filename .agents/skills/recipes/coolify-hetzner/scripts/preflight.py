"""Read prerequisites before saving a plan. Never change policy or storage."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
from api import API
from check import NoRedirect
from console_pages import show, entry
from place import OperationRefused
from tailscale_reads import read_token

def bucket_read(gate, settings):
    # Fixed Hetzner endpoint and explicit pair only. No profile, redirect,
    # proxy, SDK credential chain, object write or backend initialisation.
    if any(k in gate.S3_REDIRECT_ENV or k.startswith(('AWS_', 'TOFU_')) for k in os.environ):
        raise OperationRefused('Unset inherited storage overrides before preflight. No bucket read was sent.')
    backend = gate.s3_settings(settings)
    access, private = gate.storage_credentials()
    now = datetime.now(timezone.utc)
    stamp, day = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
    host = urllib.parse.urlsplit(backend['endpoint']).netloc
    path = '/' + urllib.parse.quote(backend['bucket'], safe='')
    payload = hashlib.sha256(b'').hexdigest()
    headers = 'host:'+host+'\nx-amz-content-sha256:'+payload+'\nx-amz-date:'+stamp+'\n'
    signed = 'host;x-amz-content-sha256;x-amz-date'
    canonical = 'HEAD\n'+path+'\n\n'+headers+'\n'+signed+'\n'+payload
    scope = day+'/'+backend['region']+'/s3/aws4_request'
    message = 'AWS4-HMAC-SHA256\n'+stamp+'\n'+scope+'\n'+hashlib.sha256(canonical.encode()).hexdigest()
    key = ('AWS4'+private).encode()
    for value in (day, backend['region'], 's3', 'aws4_request'):
        key = hmac.new(key, value.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    request = urllib.request.Request(backend['endpoint']+path, method='HEAD', headers={
        'x-amz-content-sha256':payload, 'x-amz-date':stamp,
        'Authorization':'AWS4-HMAC-SHA256 Credential='+access+'/'+scope+', SignedHeaders='+signed+', Signature='+signature})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=20) as response:
        if response.status != 200: raise OperationRefused('The state bucket did not answer the signed reachability read.')


def run(config, gate, package=None):
    from toolchain import verify_tools
    failures = []
    def failure(reason, page):
        failures.append(reason)
        print('Preflight failed: '+reason)
        show(page)
    try:
        verify_tools(gate, package)
        print('Preflight: pinned tools and Python requirements verified.')
    except (OSError, ValueError, KeyError, TypeError):
        failures.append('Pinned tools are missing or differ. Run setup.py install-tools, then put its opentofu and venv/bin folders on PATH. Node, npm and Tailscale must also be installed.')
        print('Preflight failed: '+failures[-1])
    try:
        bucket_read(gate, config['backend'])
        print('Preflight: state bucket reachable with the supplied storage pair. Versioning and retention still need console review.')
    except (OSError, ValueError, KeyError, TypeError):
        failure('State bucket reachability failed. Check the selected bucket, region and storage pair.', 'hetzner.storage-keys')
        show('hetzner.bucket')
    try:
        token = read_token(gate, preflight=True)
        api = API({}, '')
        base = 'https://api.tailscale.com/api/v2/tailnet/-/'
        policy = api.request('GET', base+'acl', token)
        tags = policy.get('tagOwners', {})
        checks = [isinstance(tags.get('tag:server'), list) and bool(tags['tag:server'])
                  and 'tag:server' in tags.get('tag:container', []),
                  'tag:server' in policy.get('autoApprovers', {}).get('services', {}).get('tag:container', []),
                  any(rule.get('action') in ('accept','check') and 'autogroup:admin' in rule.get('src', [])
                      and 'tag:server' in rule.get('dst', []) and 'root' in rule.get('users', [])
                      for rule in policy.get('ssh', []))]
        for passed, name in zip(checks, ('tagOwners','autoApprovers','ssh')):
            if not passed:
                failure('Tailnet '+name+' prerequisite is missing.', 'tailscale.policy')
        if any('*' in row.get('src', []) and '*' in row.get('dst', []) and '*' in row.get('ip', [])
               for row in policy.get('grants', [])) or any(row.get('action') == 'accept' and '*' in row.get('src', [])
               and '*:*' in row.get('dst', []) for row in policy.get('acls', [])):
            print('Default allow all grant detected. Every device may reach the server and canary. Adding a narrow grant alone does not remove that access.')
            show('tailscale.policy')
            proposal=json.dumps(entry('tailscale.policy')['canary_proposal']).replace('{canary}',config['canary_name'])
            print('Proposed replacement for the canary, subject to your review of other access: '+proposal)
        dns = api.request('GET', base+'dns/preferences', token)
        settings = api.request('GET', base+'settings', token)
        if dns.get('magicDNS') is not True: failure('MagicDNS is off or unreadable.', 'tailscale.dns')
        if settings.get('httpsEnabled') is not True: failure('HTTPS certificates are off or unreadable.', 'tailscale.dns')
    except (OSError, ValueError, KeyError, TypeError):
        failure('Tailscale prerequisite reads failed. Check the separate read credential and all required read scopes.', 'tailscale.read-credential')
        show('tailscale.policy'); show('tailscale.dns')
    if failures:
        raise OperationRefused('Preflight refused planning. No plan was saved and no policy or bucket was changed.')
    print('Preflight passed. Policy and console changes remain yours and need their own approval.')
