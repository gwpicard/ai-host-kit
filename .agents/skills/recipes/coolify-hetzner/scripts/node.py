"""Read node facts and reopen the claim over Tailscale SSH with fixed commands."""
# Node checks adapted from coolify-launchpad; see docs/SOURCES.md.
import json
import os
import subprocess
import time
from place import OperationRefused, require, tailnet_address

KEY_PATH = '/run/ai-host-kit/tailscale-auth-key'
PROBE = r"""python3 - <<'HOST_KIT_NODE'
import json, os, subprocess, re
read = lambda *a: json.loads(subprocess.check_output(a, stderr=subprocess.DEVNULL))
cloud = subprocess.run(['cloud-init', 'status', '--format', 'json'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
try:
    state = json.loads(cloud.stdout).get('status', 'unknown')
except (ValueError, TypeError):
    state = 'unknown'
try:
    errors = json.load(open('/var/lib/cloud/data/result.json')).get('v1', {}).get('errors')
except (OSError, ValueError):
    errors = None
# Never return an error string: it may contain user data or credentials.
modules = [name for name in ('scripts_user', 'scripts_per_boot', 'scripts_per_instance', 'scripts_per_once', 'package_update_upgrade_install', 'final_message', 'ssh', 'users_groups', 'write_files', 'runcmd')
           if re.search(r'\b' + name + r'\b', str(errors))]
try:
    health = subprocess.run(['docker', 'inspect', 'coolify'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    healthy = json.loads(health.stdout)[0]['State']['Health']['Status'] == 'healthy'
except (OSError, ValueError, KeyError, IndexError, TypeError):
    healthy = False
result = dict(status=read('tailscale','status','--json'), prefs=read('tailscale','debug','prefs'),
              key_file_gone=not os.path.lexists('/run/ai-host-kit/tailscale-auth-key'),
              instance_id=subprocess.check_output(['curl','-fsS','--max-time','5','http://169.254.169.254/hetzner/v1/metadata/instance-id'], stderr=subprocess.DEVNULL).decode().strip(),
              cloud_init={'v1': {'errors': [] if errors == [] and state == 'done' else ['failed']}},
              cloud_init_state=state if state in ('running', 'done', 'error') else 'unknown',
              cloud_init_modules=modules, coolify_healthy=healthy)
print(json.dumps(result))
HOST_KIT_NODE
"""


def read_node(address):
    result = subprocess.run(['tailscale','ssh','root@'+tailnet_address(address),'sh','-s'],
                            input=PROBE.encode(), stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=45, env={'PATH': os.environ.get('PATH', '')})
    require(result.returncode == 0, 'The node read failed.')
    return json.loads(result.stdout)


def node_rows(record, facts):
    status = facts.get('status', {})
    node = status.get('Self', {})
    prefs = facts.get('prefs', {})
    expected = record['infrastructure']['tailnet_ipv4']
    checks = [
        ('Node identity', status.get('BackendState') == 'Running' and
         node.get('HostName') == record['place']['name'] and expected in node.get('TailscaleIPs', [])),
        ('Hetzner server identity', str(facts.get('instance_id')) == str(record['infrastructure']['server_id'])),
        ('Temporary auth key removed', facts.get('key_file_gone') is True),
        ('Server tag', 'tag:server' in node.get('Tags', [])),
        ('Node key expiry disabled', 'Self' in status and node.get('KeyExpiry') is None),
        ('Tailscale SSH', prefs.get('RunSSH') is True),
        ('Coolify healthy', facts.get('coolify_healthy') is True),
        ('Cloud-init completed', facts.get('cloud_init', {}).get('v1', {}).get('errors') == []),
    ]
    return [(name, 'passed' if ok else 'failed') for name, ok in checks]


class BootstrapFailed(ValueError):
    """Only fixed row names and safe reasons may cross this boundary."""


def bootstrap(record, read=read_node):
    facts = read(record['infrastructure']['tailnet_ipv4'])
    rows = node_rows(record, facts)
    reasons = {
        'Node identity': 'The tailnet node name, address or running state differs.',
        'Hetzner server identity': 'The server identity differs from the approved server.',
        'Temporary auth key removed': 'The temporary key file is still present.',
        'Server tag': 'The server tag is missing.',
        'Node key expiry disabled': 'Node key expiry is on or could not be read.',
        'Tailscale SSH': 'Tailscale SSH is off or could not be read.',
        'Coolify healthy': 'Coolify is not healthy.',
        'Cloud-init completed': 'Cloud-init failed or its completion could not be read.',
    }
    if facts.get('cloud_init_state') == 'running':
        reasons['Cloud-init completed'] = 'Cloud-init is still running.'
    elif facts.get('cloud_init_state') == 'error':
        # Only known module names are reported, even for an injected transport.
        modules = [name for name in ('scripts_user', 'scripts_per_boot', 'scripts_per_instance', 'scripts_per_once', 'package_update_upgrade_install', 'final_message', 'ssh', 'users_groups', 'write_files', 'runcmd')
                   if name in facts.get('cloud_init_modules', [])]
        reasons['Cloud-init completed'] = 'Cloud-init failed in ' + (', '.join(modules) if modules else 'an unidentified module') + '.'
    failed = [name + ': ' + reasons[name] for name, status in rows if status != 'passed']
    if failed:
        raise BootstrapFailed('\n'.join(failed))
    return rows


def wait_bootstrap(record, read=read_node, timeout=1200, sleep=time.sleep, clock=time.monotonic, report=print):
    deadline = clock() + timeout
    while True:
        try:
            facts = read(record['infrastructure']['tailnet_ipv4'])
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            raise BootstrapFailed('Tailnet node read: Could not read the bootstrap facts over Tailscale SSH.') from None
        if facts.get('cloud_init_state') != 'running' or clock() >= deadline:
            bootstrap(record, lambda address: facts)
            return facts
        report('Cloud-init completed: Cloud-init is still running; checking again in 15 seconds.')
        sleep(min(15, max(0, deadline - clock())))


REOPEN_CLAIM = """set -eu
docker restart coolify >/dev/null
for attempt in $(seq 1 60); do
    if [ "$(docker inspect --format '{{.State.Health.Status}}' coolify)" = healthy ]; then
        exit 0
    fi
    sleep 2
done
exit 1
"""


def reopen_claim(address):
    try:
        result = subprocess.run(['tailscale', 'ssh', 'root@'+tailnet_address(address), 'sh', '-s'],
                                input=REOPEN_CLAIM.encode(), stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=150, env={'PATH': os.environ.get('PATH', '')})
    except (OSError, subprocess.TimeoutExpired):
        raise OperationRefused('Could not confirm the Coolify restart over Tailscale SSH. Inspect the uncertain claim before retrying.') from None
    if result.returncode:
        raise OperationRefused('Coolify did not become healthy after the restart. Inspect the uncertain claim before retrying.')
