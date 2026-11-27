"""Read prerequisites before saving a plan. Never change policy or storage."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from api import API
from check import NoRedirect
from console_pages import show, entry
from place import OperationRefused, Refused
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


STORAGE_UNREACHABLE = ('Hetzner Object Storage did not answer within 20 seconds or could not be reached. '
                       'This points to a provider or network problem, not to wrong keys or bucket settings. '
                       'Check https://status.hetzner.com and retry later.')
TAILSCALE_UNREACHABLE = ('Tailscale did not answer within 20 seconds or could not be reached. '
                         'This points to a provider or network problem, not to the read credential. '
                         'Check https://status.tailscale.com and retry later.')


def storage_failure(error):
    """Return a reason and console pages for a failed signed bucket read."""
    code = int(error.code)
    if code == 403:
        return ('The state bucket refused the signed read (HTTP 403). Check that the storage key pair is current '
                'and may read the selected bucket.', ['hetzner.storage-keys'])
    if code == 404:
        return ('The state bucket was not found (HTTP 404). Check the bucket name and region in the setup settings.',
                ['hetzner.bucket'])
    if code >= 500:
        return ('Hetzner Object Storage answered HTTP '+str(code)+', an error on the provider side. '
                'This does not point to wrong keys or bucket settings. Check https://status.hetzner.com and retry later.', [])
    return ('The state bucket answered HTTP '+str(code)+' to the signed read. Check the selected bucket, region and storage pair.',
            ['hetzner.storage-keys', 'hetzner.bucket'])


def run(config, gate):
    from toolchain import verify_tools
    gate_refused = getattr(gate, 'GateRefused', gate.InputRefused)
    failures = []
    def failure(reason, *pages):
        failures.append(reason)
        print('Preflight failed: '+reason)
        for page in pages: show(page)
    try:
        verify_tools(gate)
        print('Preflight: pinned tools and Python requirements verified.')
    except (OSError, ValueError, KeyError, TypeError):
        failures.append('Pinned tools are missing or differ. Run setup.py install-tools, then put its opentofu and venv/bin folders on PATH. Tailscale must also be installed.')
        print('Preflight failed: '+failures[-1])
    # A timeout, an outage and a refusal need different actions. Only a
    # refusal that names keys or the bucket points to the console pages.
    try:
        bucket_read(gate, config['backend'])
        print('Preflight: state bucket reachable with the supplied storage pair. Versioning and retention still need console review.')
    except urllib.error.HTTPError as error:
        reason, pages = storage_failure(error)
        failure(reason, *pages)
    except (Refused, gate_refused) as error:
        failure(str(error))
        for line in getattr(error, 'details', ()): print(line)
    except OSError:
        failure(STORAGE_UNREACHABLE)
    except (ValueError, KeyError, TypeError):
        failure('The storage settings could not be read. Check the backend bucket, region and key in the setup settings.', 'hetzner.bucket')
    token = None
    try:
        token = read_token(gate, preflight=True)
    except gate_refused as error:
        # A missing value with no terminal to ask for it: nothing was sent.
        if getattr(error, 'details', None):
            failure('No Tailscale read was sent, because a Tailscale read value is missing and no terminal could ask for it. '
                    'Set TAILSCALE_READ_CLIENT_ID and TAILSCALE_READ_CLIENT_SECRET in the protected secrets file.')
            for line in error.details: print(line)
        else:
            failure('No Tailscale read was sent. '+str(error))
    except Refused as error:
        failure(str(error), 'tailscale.read-credential')
    except urllib.error.HTTPError as error:
        failure('The Tailscale token exchange answered HTTP '+str(int(error.code))+'. Check the read credential and its read scopes.', 'tailscale.read-credential')
    except OSError:
        failure(TAILSCALE_UNREACHABLE)
    except (ValueError, KeyError, TypeError):
        failure('The Tailscale token exchange returned a reply the kit could not read. Retry, then check the read credential if it repeats.', 'tailscale.read-credential')
    if token is not None:
        tailscale_reads(config, token, failure)
    if failures:
        raise OperationRefused('Preflight refused planning. No plan was saved and no policy or bucket was changed.')
    print('Preflight passed. Policy and console changes remain yours and need their own approval.')


def tailscale_reads(config, token, failure):
    try:
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
        missing = [name for passed, name in zip(checks, ('tagOwners','autoApprovers','ssh')) if not passed]
        for name in missing:
            failure('Tailnet '+name+' prerequisite is missing.')
        if missing:
            # Print merge lines only for the prerequisites that failed.
            show('tailscale.policy', required=missing)
        if any('*' in row.get('src', []) and '*' in row.get('dst', []) and '*' in row.get('ip', [])
               for row in policy.get('grants', [])) or any(row.get('action') == 'accept' and '*' in row.get('src', [])
               and '*:*' in row.get('dst', []) for row in policy.get('acls', [])):
            print('Notice, not a failed prerequisite: default allow all grant detected. Every device may reach the server and canary. Adding a narrow grant alone does not remove that access.')
            proposal=json.dumps(entry('tailscale.policy')['canary_proposal']).replace('{canary}',config['canary_name'])
            print('Guidance for narrowing access, for your review: proposed replacement for the canary, subject to your review of other access: '+proposal)
            print('Console page for that review: '+entry('tailscale.policy')['url'])
        dns = api.request('GET', base+'dns/preferences', token)
        settings = api.request('GET', base+'settings', token)
        if dns.get('magicDNS') is not True: failure('MagicDNS is off or unreadable.', 'tailscale.dns')
        if settings.get('httpsEnabled') is not True: failure('HTTPS certificates are off or unreadable.', 'tailscale.dns')
    except urllib.error.HTTPError as error:
        failure('Tailscale answered HTTP '+str(int(error.code))+' to a prerequisite read. Check that the read credential has every required read scope. Policy and DNS were not judged.', 'tailscale.read-credential')
    except OSError:
        failure(TAILSCALE_UNREACHABLE+' Policy and DNS were not judged.')
    except (ValueError, KeyError, TypeError, AttributeError):
        failure('Tailscale returned a prerequisite reply the kit could not read. Policy and DNS were not judged.')
