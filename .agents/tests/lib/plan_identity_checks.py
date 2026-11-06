"""Check checksum-bound identity records and controlled planning without a host."""
import json
from pathlib import Path
import shutil
from unittest.mock import patch


def planning(checks, gate, project, work):
    plan = project / 'controlled.plan'
    record = gate.identity_path(plan)
    for path in (plan, record):
        path.unlink(missing_ok=True)
    with checks.directory(project):
        error, output = checks.capture(lambda: gate.plan(plan))
        assert not error and plan.is_file() and record.is_file(), error
        value = gate.records.read_json(record)
        assert value['plan_sha256'] == gate.digest(plan.read_bytes())
        assert value['target'] == gate.target_identity()
        assert gate.records.validate('plan-identity', record) == 0
        assert record.stat().st_mode & 0o777 == 0o600
        saved = plan.read_bytes()
        assert checks.capture(lambda: gate.plan(plan))[0]
        assert plan.exists() and plan.read_bytes() == saved
    plan.unlink(); record.unlink()
    actual = gate.tofu
    config = project / 'main.tf'; original = config.read_text()
    keep = project / 'keep.txt'; keep.write_text('synthetic file to preserve')
    def changed(*args):
        result = actual(*args)
        if args[0] == 'plan':
            config.write_text(original + '\n# synthetic change while planning\n')
        return result
    try:
        with checks.directory(project), patch.object(gate, 'tofu', side_effect=changed):
            error, output = checks.capture(lambda: gate.plan(plan))
        assert error and 'changed during planning' in error, 'changing identity was accepted'
        assert not plan.exists() and not record.exists() and keep.exists()
    finally:
        config.write_text(original)
        plan.unlink(missing_ok=True); record.unlink(missing_ok=True); keep.unlink()


def identity_refusals(checks, gate, project, work, case):
    plan = project / 'first.plan'; path = gate.identity_path(plan)
    original = path.read_bytes()
    approval = work / 'identity-synthetic-approval.json'
    with checks.directory(project): approval.write_text(json.dumps(checks.record_for(gate, plan)))
    value = json.loads(original)
    if case == 'missing': path.unlink()
    elif case == 'malformed': path.write_text('{}')
    elif case == 'schema':
        value['unexpected'] = 'synthetic'
        path.write_text(json.dumps(value))
    elif case == 'checksum': path.write_bytes(gate.identity_path(project / 'second.plan').read_bytes())
    elif case == 'target':
        value['target']['configuration_sha256'] = 'b' * 64
        path.write_text(json.dumps(value))
    try:
        with checks.directory(project):
            error, output = checks.capture(lambda: gate.planned_identity(plan, gate.digest(plan.read_bytes())))
        assert error and 'Save and approve a new plan' in error, case + ' identity was accepted'
        with checks.directory(project):
            error, output = checks.capture(lambda: gate.apply(plan, approval))
        assert error and 'Save and approve a new plan' in error, case + ' identity reached apply'
        destination = work / 'identity-terminal-approval.json'; destination.unlink(missing_ok=True)
        skill = Path(gate.__file__).resolve().parents[1]
        status, text = checks.terminal_run(skill, project, destination)
        assert status != 0 and not destination.exists() and 'Save and approve a new plan' in text
    finally:
        path.write_bytes(original)
        approval.unlink(missing_ok=True)


def late_identity(checks, gate, project, work, approval=False, skill=None):
    plan = project / 'first.plan'; path = gate.identity_path(plan)
    original = path.read_bytes()
    destination = work / 'late-approval.json'; destination.unlink(missing_ok=True)
    try:
        if approval:
            status, text = checks.terminal_run(skill or checks.SKILL, project, destination,
                                              before_words=lambda: path.unlink())
            assert status != 0 and not destination.exists() and 'plan-time identity record' in text, text
        else:
            actual = gate.read_plan; calls = []
            def read_then_remove(*args, **kwargs):
                result = actual(*args, **kwargs); path.unlink(); return result
            with checks.directory(project):
                record = checks.record_for(gate, plan)
                destination.write_text(json.dumps(record))
                with patch.object(gate, 'read_plan', side_effect=read_then_remove), patch.object(gate, 'tofu', wraps=gate.tofu) as observed:
                    error, output = checks.capture(lambda: gate.apply(plan, destination))
                calls = [call for call in observed.call_args_list if call.args[0] == 'apply']
            assert error and 'plan-time identity record' in error and not calls
    finally:
        path.write_bytes(original); destination.unlink(missing_ok=True)


def backend_restrictions(checks, gate, project, work, case):
    metadata = project / '.terraform/terraform.tfstate'
    original = metadata.read_bytes() if metadata.exists() else None
    approval = work / 'backend-synthetic-approval.json'
    with checks.directory(project): approval.write_text(json.dumps(checks.record_for(gate, project / 'first.plan')))
    value = dict(backend=dict(type='local', config=dict(path='terraform.tfstate', workspace_dir=None)))
    overrides = {}
    if case == 'http':
        value['backend'] = dict(type='http', config=dict(address=None))
        overrides = {'TF_HTTP_ADDRESS': 'http://127.0.0.1:18473/planned'}
    elif case == 'explicit-http': value['backend'] = dict(type='http', config=dict(address='http://127.0.0.1:18473/planned'))
    elif case == 'null': value['backend']['config']['path'] = None
    elif case == 'empty': value['backend']['config']['path'] = ''
    elif case == 'unsupported-shaped': value['backend']['type'] = 'http'
    else: overrides = {case: {'TF_WORKSPACE': 'default', 'TF_DATA_DIR': '.terraform', 'TF_CLI_ARGS': '', 'TF_CLI_ARGS_plan': '', 'TF_CLI_ARGS_apply': ''}.get(case, 'synthetic-override')}
    metadata.parent.mkdir(exist_ok=True)
    metadata.write_text(json.dumps(value))
    path = project / 'refused.plan'; path.unlink(missing_ok=True)
    try:
        with checks.directory(project), patch.dict(checks.os.environ, overrides):
            actual = gate.tofu
            calls = []
            def observe(*args):
                import subprocess
                calls.append(args[0])
                if args[0] == 'workspace': return subprocess.CompletedProcess(args, 0, b'default\n', b'')
                if args[0] == 'plan':
                    path.write_bytes((project / 'first.plan').read_bytes())
                    return subprocess.CompletedProcess(args, 0, b'', b'')
                if args[0] == 'apply': return subprocess.CompletedProcess(args, 0, b'', b'')
                return actual(*args)
            with patch.object(gate, 'tofu', side_effect=observe):
                error, output = checks.capture(lambda: gate.plan(path))
                assert error and not path.exists() and 'plan' not in calls, case + ' reached planning'
                error, output = checks.capture(lambda: gate.planned_identity(project / 'first.plan', gate.digest((project / 'first.plan').read_bytes())))
                assert error, case + ' passed approval identity check'
                error, output = checks.capture(lambda: gate.apply(project / 'first.plan', approval))
                assert error and 'apply' not in calls, case + ' reached apply'
    finally:
        if original is None: metadata.unlink()
        else: metadata.write_bytes(original)
        approval.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        gate.identity_path(path).unlink(missing_ok=True)


def real_http(checks, gate, work):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404); self.end_headers()
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    assert server.server_port != 3000
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    project = work / 'real-http'; project.mkdir()
    (project / 'main.tf').write_text('terraform {\n  backend "http" {}\n}\nresource "terraform_data" "fixture" {}\n')
    shutil.copy2(checks.ROOT / 'tofu/encryption.tf', project / 'encryption.tf')
    address = 'http://127.0.0.1:' + str(server.server_port) + '/planned'
    try:
        checks.tofu(project, 'init', '-input=false', env={'TF_HTTP_ADDRESS': address})
        with checks.directory(project), patch.dict(checks.os.environ, {'TF_HTTP_ADDRESS': address}):
            error, output = checks.capture(lambda: gate.plan(project / 'http.plan'))
        assert error and 'backend is not supported' in error and not (project / 'http.plan').exists()
        # The backend itself refuses even when the environment override is absent.
        with checks.directory(project):
            error, output = checks.capture(lambda: gate.plan(project / 'http.plan'))
        assert error and 'backend is not supported' in error
    finally:
        server.shutdown(); server.server_close(); thread.join()
    print('HTTP backend probe refused before planning, including TF_HTTP_ADDRESS; loopback only.')


def fragment_presence(checks, gate, project, work):
    fragment = project / 'encryption.tf'; original = fragment.read_bytes()
    plan = project / 'fragment.plan'
    try:
        # Valid encryption configuration, but no verbatim bundled fragment.
        fragment.write_bytes(b'# synthetic prefix\n' + original)
        with checks.directory(project):
            error, output = checks.capture(lambda: gate.plan(plan))
        assert error and 'fragment is missing' in error and not plan.exists()
    finally:
        fragment.write_bytes(original)
        plan.unlink(missing_ok=True); gate.identity_path(plan).unlink(missing_ok=True)


def version_pin(checks, gate, project, work):
    import subprocess
    actual = gate.tofu; calls = []
    with checks.directory(project): record = checks.record_for(gate, project / 'first.plan')
    approval = work / 'version-approval.json'; approval.write_text(json.dumps(record))
    def wrong(*args):
        calls.append(args[0])
        if args[0] == 'version': return subprocess.CompletedProcess(args, 0, b'{"terraform_version":"1.13.1"}', b'')
        return actual(*args)
    try:
        with checks.directory(project), patch.object(gate, 'tofu', side_effect=wrong):
            with gate.saved_plan(project / 'first.plan') as (snapshot, sha):
                error, output = checks.capture(lambda: gate.read_plan(snapshot))
            assert error and 'show' not in calls
            error, output = checks.capture(lambda: gate.apply(project / 'first.plan', approval))
            assert error and 'apply' not in calls
    finally: approval.unlink(missing_ok=True)

def apply_version_recheck(checks, gate, project, work):
    import subprocess
    actual = gate.tofu; versions = []; applied = []
    with checks.directory(project): record = checks.record_for(gate, project / 'first.plan')
    approval = work / 'late-version.json'; approval.write_text(json.dumps(record))
    def changed(*args):
        if args[0] == 'version':
            versions.append(True)
            if len(versions) > 1:
                return subprocess.CompletedProcess(args, 0, b'{"terraform_version":"1.13.1"}', b'')
        if args[0] == 'apply':
            applied.append(True)
            return subprocess.CompletedProcess(args, 0, b'', b'')
        return actual(*args)
    try:
        with checks.directory(project), patch.object(gate, 'tofu', side_effect=changed):
            error, output = checks.capture(lambda: gate.apply(project / 'first.plan', approval))
        assert error and 'version differs' in error and not applied
    finally: approval.unlink(missing_ok=True)


def hidden_destinations(checks, gate, project, work):
    state = project / 'terraform.tfstate'
    original = state.read_bytes() if state.exists() else None
    targets = []
    try:
        for name in ('token=synthetic-before', 'token=synthetic-after'):
            state.unlink(missing_ok=True)
            state.symlink_to(work / name)
            with checks.directory(project): targets.append(gate.target_identity())
        assert all(target['backend_settings']['path'] == '<destination path withheld>' for target in targets)
        assert targets[0] != targets[1], 'withheld destination change escaped the fingerprint'
    finally:
        state.unlink(missing_ok=True)
        if original is not None: state.write_bytes(original)


def run_checks(checks, work):
    work.mkdir()
    project = checks.fixture_plans(work)
    gate = checks.load()
    def check_all(module):
        planning(checks, module, project, work)
        hidden_destinations(checks, module, project, work)
        for case in ('missing', 'malformed', 'checksum', 'target'):
            identity_refusals(checks, module, project, work, case)
        late_identity(checks, module, project, work)
        late_identity(checks, module, project, work, approval=True)
        for case in ('http', 'explicit-http', 'null', 'empty', 'TF_WORKSPACE', 'TF_DATA_DIR',
                     'TF_CLI_ARGS', 'TF_CLI_ARGS_plan', 'TF_CLI_ARGS_apply', 'TF_LOCAL_PATH'):
            backend_restrictions(checks, module, project, work, case)
        fragment_presence(checks, module, project, work)
        version_pin(checks, module, project, work)
        apply_version_recheck(checks, module, project, work)
    check_all(gate)
    real_http(checks, gate, work)
    print('Identity regressions passed: absent, malformed, other plan, changed target, late removal, backend and environment restrictions, fragment and version.')
    scratch = work / 'mutated-skill'; shutil.copytree(checks.SKILL, scratch)
    script = scratch / 'scripts/approval_gate.py'; original = script.read_text()
    mutations = [
        ('existing plan preservation', '    if path.exists() or record_path.exists():', '    if False:', lambda m: planning(checks, m, project, work)),
        ('plan-time checksum binding', 'plan_sha256=digest(path.read_bytes())', "plan_sha256='0' * 64", lambda m: planning(checks, m, project, work)),
        ('withheld destination fingerprint', 'backend, settings_sha, workspace', 'backend, workspace', lambda m: hidden_destinations(checks, m, project, work)),
        ('identity change during planning', '        if before != after:', '        if False:', lambda m: planning(checks, m, project, work)),
        ('identity schema', '        if status:', '        if False:', lambda m: identity_refusals(checks, m, project, work, 'schema')),
        ('identity checksum', "record['plan_sha256'] != sha", 'False', lambda m: identity_refusals(checks, m, project, work, 'checksum')),
        ('identity target', "record['target'] != target_identity()", 'False', lambda m: identity_refusals(checks, m, project, work, 'target')),
        ('late approval identity', '        match_target(record, planned_identity(path, sha))\n        unchanged(path, sha)', '        unchanged(path, sha)', lambda m: late_identity(checks, m, project, work, approval=True, skill=scratch)),
        ('late apply identity', "        match_target(record, planned_identity(path, sha))\n        applied", '        applied', lambda m: late_identity(checks, m, project, work)),
        ('redirecting environment', '    if redirecting:', '    if False:', lambda m: backend_restrictions(checks, m, project, work, 'TF_WORKSPACE')),
        ('unsupported backend', "    if backend_record['type'] != 'local':", '    if False:', lambda m: backend_restrictions(checks, m, project, work, 'unsupported-shaped')),
        ('explicit local destination', "not isinstance(settings.get('path'), str) or not settings['path']", 'False', lambda m: backend_restrictions(checks, m, project, work, 'empty')),
        ('bundled encryption fragment', '    if not any(p.is_file()', '    if False and not any(p.is_file()', lambda m: fragment_presence(checks, m, project, work)),
        ('final apply version check', '        check_version()\n        require_encryption()\n        match_target', '        require_encryption()\n        match_target', lambda m: apply_version_recheck(checks, m, project, work)),
        ('version pin', "if version.returncode or json.loads(version.stdout).get('terraform_version') != VERSION:", 'if False:', lambda m: version_pin(checks, m, project, work)),
    ]
    for name, old, new, check in mutations:
        script.write_text(checks.mutate_text(original, old, new, name))
        try:
            try:
                check(checks.load(scratch))
            except AssertionError:
                print('Protection removal detected: ' + name)
            else:
                raise AssertionError('protection removal escaped its check: ' + name)
        finally: script.write_text(original)
        check(checks.load(scratch))
        print('Restored protection passed: ' + name)
