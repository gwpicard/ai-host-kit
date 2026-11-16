"""Exercise release verification, health waits and safe bootstrap reasons offline."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
RECIPE = ROOT/'.agents/skills/recipes/coolify-hetzner'
sys.path.insert(0, str(ROOT/'.agents/tools'))
from check_coolify_pin import check, FILES
from kit import posix_shell
sys.path.insert(0, str(RECIPE/'scripts'))
import node


def fails(action):
    try:
        action()
    except (ValueError, KeyError):
        return
    raise AssertionError('Removed protection escaped the check')


def pins(work):
    check(RECIPE)
    target = work/'recipe'
    shutil.copytree(RECIPE, target, ignore=shutil.ignore_patterns('.terraform', '__pycache__'))
    path = target/'dependencies.json'
    original = path.read_text()
    for kind in ('version', 'installer release', 'compose release', 'missing checksum'):
        data = json.loads(original)
        if kind == 'version': data['coolify'] = '4.7.6'
        elif kind == 'missing checksum': del data['coolify_files']['docker-compose.yml']['sha256']
        else:
            name = 'install.sh' if kind == 'installer release' else 'docker-compose.prod.yml'
            data['coolify_files'][name]['url'] = data['coolify_files'][name]['url'].replace('v4.7.5', 'v4.3.23')
        path.write_text(json.dumps(data))
        fails(lambda: check(target))
        path.write_text(original)
        check(target)
        print('Protection removal rejected and restored: ' + kind)
    cloud = target/'tofu/hetzner-server/cloud-init.sh'
    original = cloud.read_text()
    cloud.write_text(original.replace('sha256sum --check --status', 'cat >/dev/null'))
    fails(lambda: check(target))
    cloud.write_text(original)
    check(target)
    print('Protection removal rejected and restored: runtime checksum verification')


def install(work):
    source = (RECIPE/'tofu/hetzner-server/cloud-init.sh').read_text()
    section = source[source.index('# Verify every release file'):]
    upstream = work/'upstream'; upstream.mkdir()
    download = lambda n: f'curl -fsSL -L $CDN/{n} -o {work}/destination/{n}\n'
    for name in FILES:
        content = 'synthetic release file\n'
        if name in ('install.sh', 'upgrade.sh'):
            names = [n for n in FILES if n != 'install.sh' and (name == 'install.sh' or n != 'upgrade.sh')]
            content = 'set -e\n' + ''.join(download(n) for n in names)
            if name == 'install.sh':
                content += '# Fetch versions.json once\nexit 93\ncase "$OS_TYPE" in\n*) ;;\nesac\nMAX_WAIT=180\nHEALTH_WAIT=60\n'
        (upstream/name).write_text(content)
    for name, pin in json.loads((RECIPE/'dependencies.json').read_text())['coolify_files'].items():
        section = section.replace(pin['sha256'], hashlib.sha256((upstream/name).read_bytes()).hexdigest())
    original_hash = hashlib.sha256((upstream/'install.sh').read_bytes()).hexdigest()
    section = section.replace('/run/ai-host-kit/coolify', str(work/'cache')).replace('/data/coolify/source', str(work/'destination'))
    (work/'destination').mkdir()
    prefix = '''set -eu
sha256sum() { shasum -a 256 --check --status; }
export OS_TYPE=synthetic
export LC_ALL=C
curl() {
 while [ "$1" != -o ]; do url="$1"; shift; done
 cp "$UPSTREAM/${url##*/}" "$2"
 if [ "${CORRUPT:-}" = "${url##*/}" ]; then printf corrupted >>"$2"; fi
}
sleep() { :; }
docker() {
 printf '%s' '[{"State":{"Health":{"Status":"'
 cat "$HEALTH"
 printf '%s\\n' '"}}}]'
}
'''
    health = work/'health';health.write_text('healthy')
    def run(corrupt='', text=section):
        target = work/'run.sh';target.write_text(prefix+text)
        return subprocess.run([posix_shell(), str(target)], env=dict(os.environ, UPSTREAM=str(upstream), HEALTH=str(health), CORRUPT=corrupt), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result = run();assert result.returncode == 0, result.stderr.decode()
    assert b'Coolify is healthy.' in result.stdout
    prepared = (work/'cache/install.sh').read_text()
    assert 'curl -fsSL -L $CDN/' not in prepared and 'HEALTH_WAIT=600' in prepared and 'LATEST_HELPER_VERSION=1.0.19' in prepared
    for name in FILES:
        result = run(name)
        assert result.returncode != 0 and b'checksum mismatch' in result.stderr, name
    # A malformed upstream download layout must stop before execution.
    bad = (upstream/'install.sh').read_text().replace(download('upgrade.sh'), '')
    (upstream/'install.sh').write_text(bad)
    old = original_hash
    result = run(text=section.replace(old, hashlib.sha256(bad.encode()).hexdigest()))
    assert result.returncode != 0 and b'layout changed' in result.stderr
    # Restore the installer fixture and test the independent health deadline.
    good = bad.replace('set -e\n', 'set -e\n'+download('upgrade.sh'), 1)
    (upstream/'install.sh').write_text(good)
    health.write_text('starting')
    result = run(text=section.replace(old, hashlib.sha256(good.encode()).hexdigest()))
    assert result.returncode != 0 and b'within 10 minutes' in result.stderr
    assert b'waited 590 seconds' in result.stdout
    print('All six corrupt downloads refused; preparation and bounded health waits exercised.')


def bootstrap():
    record = json.loads((ROOT/'.agents/tests/fixtures/place/place-record.json').read_text())
    facts = dict(status=dict(BackendState='Running', Self=dict(HostName='test-place', TailscaleIPs=['100.64.0.10'], Tags=['tag:server'], KeyExpiry=None)), prefs=dict(RunSSH=True), instance_id='101', key_file_gone=True, cloud_init={'v1': {'errors': []}}, cloud_init_state='done', coolify_healthy=True)
    node.bootstrap(record, lambda _: facts)
    for field, value, reason in [('key_file_gone', False, 'key file is still present'), ('prefs', {'RunSSH': False}, 'SSH is off'), ('coolify_healthy', False, 'Coolify is not healthy'), ('cloud_init', {'v1': {'errors': ['secret-marker']}}, 'Cloud-init failed')]:
        bad = dict(facts, **{field: value})
        try: node.bootstrap(record, lambda _: bad)
        except node.BootstrapFailed as error:
            assert reason in str(error) and 'secret-marker' not in str(error)
        else: raise AssertionError(reason)
    bad = copy.deepcopy(facts);bad['status']['Self']['Tags']=[];bad['status']['Self']['KeyExpiry']='secret-marker'
    try: node.bootstrap(record,lambda _:bad)
    except node.BootstrapFailed as error: assert 'tag is missing' in str(error) and 'expiry is on' in str(error) and 'secret-marker' not in str(error)
    bad = dict(facts, cloud_init_state='error', cloud_init={'v1': {'errors': ['secret-marker']}}, cloud_init_modules=['scripts_user','secret-marker'])
    try: node.bootstrap(record, lambda _:bad)
    except node.BootstrapFailed as error: assert 'scripts_user' in str(error) and 'secret-marker' not in str(error)
    running = dict(facts, cloud_init_state='running', cloud_init={'v1': {'errors': ['failed']}})
    reads = iter([running, running, facts]); clock=[0]; messages=[]
    def sleep(seconds):clock[0]+=seconds
    assert node.wait_bootstrap(record, lambda _:next(reads), sleep=sleep, clock=lambda:clock[0], report=messages.append) == facts
    assert len(messages)==2 and clock[0]==30
    try: node.wait_bootstrap(record, lambda _:running, timeout=30, sleep=sleep, clock=lambda:clock[0], report=messages.append)
    except node.BootstrapFailed as error: assert 'still running' in str(error)
    else: raise AssertionError('Unbounded cloud-init wait')
    print('Bootstrap reports safe row reasons and waits for running cloud-init with a deadline.')



def probe():
    from contextlib import redirect_stdout
    from io import StringIO
    from types import SimpleNamespace
    from unittest.mock import patch
    # Exercise the remote probe before Docker or result.json exists, then with
    # a failed module whose raw message contains a synthetic secret marker.
    code = node.PROBE.split("<<'HOST_KIT_NODE'\n", 1)[1].split('\nHOST_KIT_NODE', 1)[0]
    for state in ('running', 'error'):
        def run(command, **kwargs):
            if command[0] == 'cloud-init':
                return SimpleNamespace(stdout=json.dumps({'status': state}).encode())
            raise FileNotFoundError('Docker is not installed yet')
        def output(command, **kwargs):
            if command[0] == 'curl': return b'101'
            return b'{}'
        def read_file(*args, **kwargs):
            if state == 'running': raise FileNotFoundError('No result yet')
            return StringIO(json.dumps({'v1': {'errors': ["('scripts_user', RuntimeError('secret-marker'))"]}}))
        captured = StringIO()
        with patch('subprocess.run', side_effect=run), patch('subprocess.check_output', side_effect=output), patch('builtins.open', side_effect=read_file), redirect_stdout(captured):
            exec(compile(code, '<node probe>', 'exec'), {})
        assert 'secret-marker' not in captured.getvalue()
        facts = json.loads(captured.getvalue())
        assert facts['cloud_init_state'] == state and not facts['coolify_healthy']
        assert facts['cloud_init_modules'] == (['scripts_user'] if state == 'error' else [])
    print('Remote probe tolerates missing Docker and cloud-init result, and withholds raw module errors.')


with tempfile.TemporaryDirectory(prefix='coolify-pin-') as temporary:
    work = Path(temporary)
    pins(work)
    install(work)
    bootstrap()
    probe()
