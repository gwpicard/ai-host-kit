"""Read fixed node facts over Tailscale SSH; never run a supplied command."""
# Node checks adapted from coolify-launchpad; see docs/SOURCES.md.
import json
import subprocess
from place import require, tailnet_address

KEY_PATH = '/run/ai-host-kit/tailscale-auth-key'
PROBE = r"""python3 - <<'HOST_KIT_NODE'
import json, os, subprocess
read = lambda *a: json.loads(subprocess.check_output(a, stderr=subprocess.DEVNULL))
result = dict(status=read('tailscale','status','--json'), prefs=read('tailscale','debug','prefs'),
              key_file_gone=not os.path.lexists('/run/ai-host-kit/tailscale-auth-key'),
              instance_id=subprocess.check_output(['curl','-fsS','--max-time','5','http://169.254.169.254/hetzner/v1/metadata/instance-id'], stderr=subprocess.DEVNULL).decode().strip(),
              cloud_init=json.load(open('/var/lib/cloud/data/result.json')))
print(json.dumps(result))
HOST_KIT_NODE
"""


def read_node(address):
    result = subprocess.run(['tailscale','ssh','root@'+tailnet_address(address),'sh','-s'],
                            input=PROBE.encode(), stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=45)
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
        ('Cloud-init completed', facts.get('cloud_init', {}).get('v1', {}).get('errors') == []),
    ]
    return [(name, 'passed' if ok else 'failed') for name, ok in checks]


def bootstrap(record, read=read_node):
    rows = node_rows(record, read(record['infrastructure']['tailnet_ipv4']))
    require(all(status == 'passed' for _, status in rows),
            'Bootstrap checks failed. The server, firewall and SSH key may exist; keep the encrypted state and retire with an approved destroy plan.')
    return rows
