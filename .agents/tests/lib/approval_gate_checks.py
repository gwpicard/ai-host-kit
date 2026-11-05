"""Exercise saved plans, terminal approval, redaction and protection removals locally."""
import contextlib
import copy
import fnmatch
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from unittest.mock import patch

from checks import ROOT, run

SKILL = ROOT / '.agents/skills/setup-hosting'
FIXTURES = ROOT / '.agents/tests/fixtures/approval-gate'
PASSPHRASE = 'synthetic-test-passphrase-only'
SECRET = 'synthetic-plan-secret-marker'
ENV = dict(TF_VAR_host_state_passphrase=PASSPHRASE, TF_VAR_fixture_secret=SECRET,
           TF_IN_AUTOMATION='1', TF_INPUT='0')


def load(skill=SKILL):
    sys.modules.pop('record_validation', None)
    spec = importlib.util.spec_from_file_location('approval_gate', skill / 'scripts/approval_gate.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def tofu(project, *args, expected=0, env=None):
    result = run(['tofu', *args], cwd=project, env=dict(ENV, **(env or {})), expected=None)
    assert result.returncode == expected, 'OpenTofu fixture command failed; raw values withheld: ' + args[0]
    return result


def capture(action):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        try:
            action()
            error = None
        except (ValueError, OSError) as exc:
            error = str(exc)
    return error, stream.getvalue()


def fixture_plans(work):
    project = work / 'project'
    project.mkdir()
    for name in ('main.tf', 'offline.tftest.hcl'):
        shutil.copy2(FIXTURES / name, project / name)
    shutil.copy2(ROOT / 'tofu/encryption.tf', project / 'encryption.tf')
    tofu(project, 'init', '-input=false', '-no-color')
    tofu(project, 'validate', '-no-color')
    tofu(project, 'test', '-no-color')
    tofu(project, 'plan', '-input=false', '-no-color', '-out=first.plan')
    tofu(project, 'plan', '-input=false', '-no-color', '-var=fixture_value=second fixture', '-out=second.plan')
    first = (project / 'first.plan').read_bytes()
    second = (project / 'second.plan').read_bytes()
    assert first != second
    for data in (first, second):
        assert json.loads(data)['encryption_version'] == 'v0'
        assert SECRET.encode() not in data and PASSPHRASE.encode() not in data
    print('Real offline saved plans, tofu validate and tofu test passed with the shared encryption fragment.')
    return project


def summary_checks(gate):
    plan = json.loads((FIXTURES / 'network.show.json').read_text())
    summary = gate.summarise(plan)
    rendered = gate.render('a' * 64, summary)
    changes = '\n'.join(summary['changes'])
    assert 'Destroy: hcloud_volume.old.' in changes
    assert 'Replace and destroy the old resource: aws_s3_bucket.archive.' in changes
    assert changes.index('Destroy: hcloud_volume.old.') < changes.index('Change: hcloud_firewall.web.')
    assert changes.index('Replace and destroy the old resource: aws_s3_bucket.archive.') < changes.index('Change: hcloud_firewall.web.')
    assert 'hcloud_volume.old' in '\n'.join(summary['irreversible'])
    assert 'storage changes may lose data' in '\n'.join(summary['irreversible'])
    internet = '\n'.join(summary['internet'])
    assert 'port: 443 -> 443' in internet and 'port: not set -> 8080' in internet
    assert '10.0.0.0/8 -> all sources (0.0.0.0/0)' in internet and '::/0' in internet
    assert 'private -> public-read' in internet and '198.51.100.10' in internet
    assert 'azuread_application.staff' in '\n'.join(summary['access'])
    assert 'Unrecognised resource type future_unknown: future_unknown.widget' in changes
    assert 'Unrecognised change' in changes
    for resource in plan['resource_changes']:
        assert resource['address'] in changes
    for secret in ('synthetic-', '65432', '65431', '65430', '192.0.2.89', '9999'):
        assert secret not in rendered, 'summary disclosed a fixture value'
    assert 'rule[0]' in rendered and 'sensitive or unknown' in rendered
    assert 'lost passphrase means the state cannot be read' in rendered
    assert rendered.count('What ') == 4 and 'aaaa-aaaa-aaaa' in rendered
    indexed = copy.deepcopy(plan)
    indexed['resource_changes'][0]['address'] = 'module.site["synthetic-instance-secret"].hcloud_firewall.web'
    indexed_text = gate.render('a' * 64, gate.summarise(indexed))
    assert 'module.site[instance name withheld].hcloud_firewall.web' in indexed_text
    assert 'synthetic-instance-secret' not in indexed_text
    drift = dict(format_version='1.2', resource_drift=[plan['resource_changes'][1]],
                 deferred_changes=[{'resource_change':plan['resource_changes'][0]}])
    drift_text = gate.render('a' * 64, gate.summarise(drift))
    assert 'Observed drift: Destroy: hcloud_volume.old' in drift_text
    assert 'Deferred change: Change: hcloud_firewall.web' in drift_text
    return summary


def record_for(gate, plan):
    with gate.saved_plan(plan) as (snapshot, sha):
        summary = gate.read_plan(snapshot)
    return dict(schema_version='1.0', plan_sha256=sha, approved_at='2026-11-05T12:00:00Z',
                words='I approve the local fixture changes.', confirmation='approve ' + gate.short_hash(sha),
                method='terminal-checksum', summary=summary, target=gate.target_identity())


def record_checks(gate, work):
    record = json.loads((ROOT / '.agents/tests/fixtures/contracts/approval-record/valid.json').read_text())
    file = work / 'record-contract.json'
    def valid(value):
        file.write_text(json.dumps(value))
        return capture(lambda: gate.validate_record(file))[0] is None
    assert valid(record)
    for field in record:
        bad = copy.deepcopy(record); del bad[field]
        assert not valid(bad), 'missing approval field accepted'
    for field in record['target']:
        bad = copy.deepcopy(record); del bad['target'][field]
        assert not valid(bad), 'missing target identity field accepted'
        bad = copy.deepcopy(record); bad['target'][field] = 'token=synthetic-marker'
        assert not valid(bad), 'unsafe target identity accepted'
    for field, value in [('approved_at', '2026-02-30T12:00:00Z'), ('plan_sha256', 'short'),
                         ('schema_version', '1.1'), ('method', 'agent'), ('extra', 'unexpected')]:
        bad = dict(record, **{field:value})
        assert not valid(bad), 'malformed approval accepted'
    for text in ('https://user:synthetic@example.invalid/a', 'https://example.invalid/a?q=synthetic',
                 'https://example.invalid/a#fragment', 'https://example.invalid/a%2f',
                 'token=synthetic-marker', 'password: synthetic-marker',
                 'abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        for field in ('words', 'changes', 'internet', 'access', 'irreversible'):
            bad = copy.deepcopy(record)
            if field == 'words': bad[field] = text
            else: bad['summary'][field] = [text]
            assert not valid(bad), 'unsafe approval text accepted'
    file.write_text('{"schema_version":"1.0","schema_version":"1.0"}')
    assert capture(lambda: gate.validate_record(file))[0]


def apply_case(gate, project, case):
    first = project / 'first.plan'
    current = project / 'current.plan'
    current.write_bytes(first.read_bytes())
    record = record_for(gate, first)
    approval = project / 'approval.json'
    if approval.exists(): approval.unlink()
    if case == 'missing':
        pass
    elif case == 'malformed':
        approval.write_text('{}')
    else:
        if case == 'checksum': record['plan_sha256'] = 'b' * 64
        if case == 'summary': record['summary']['changes'] = ['A different summary.']
        if case == 'confirmation': record['confirmation'] = 'approve 0000-0000-0000'
        approval.write_text(json.dumps(record))
    if case == 'replaced': current.write_bytes((project / 'second.plan').read_bytes())
    if case == 'appended': current.write_bytes(current.read_bytes() + b' ')
    calls = []
    actual = gate.tofu
    def observed(*args):
        if args[0] == 'apply':
            calls.append((args, Path(args[1]).read_bytes()))
            return subprocess.CompletedProcess(args, 0, b'', b'')
        return actual(*args)
    original_match = gate.match_record
    def race(*args):
        original_match(*args)
        current.write_bytes((project / 'second.plan').read_bytes())
    with patch.object(gate, 'tofu', side_effect=observed):
        with patch.object(gate, 'match_record', side_effect=race) if case == 'race' else contextlib.nullcontext():
            error, output = capture(lambda: gate.apply(current, approval))
    if case == 'valid':
        assert error is None and len(calls) == 1, 'matching approval did not apply'
        args, data = calls[0]
        assert len(args) == 2, 'apply supplied extra arguments or re-planned'
        assert data == first.read_bytes(), 'applied different bytes'
        assert Path(args[1]) != current, 'apply used a replaceable original path'
    else:
        assert error and not calls, 'apply reached OpenTofu without the required approval protection: ' + case
    assert SECRET not in output and PASSPHRASE not in output


def terminal_run(skill, project, destination, piped=False, wrong=False, words='I approve the local fixture changes.'):
    # A synthetic terminal is test machinery, not evidence of a real person's approval.
    sha = hashlib.sha256((project / 'first.plan').read_bytes()).hexdigest()
    confirmation = 'approve ' + '-'.join(sha[n:n+4] for n in (0,4,8))
    if wrong: confirmation = 'approve 0000-0000-0000'
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(project)
        if piped:
            read_fd, write_fd = os.pipe()
            os.write(write_fd, (confirmation + '\n' + words + '\n').encode())
            os.close(write_fd)
            os.dup2(read_fd, 0)
            os.close(read_fd)
        os.environ.update(ENV)
        os.execv(sys.executable, [sys.executable, str(skill / 'scripts/approval_gate.py'),
                                 'approve', 'first.plan', str(destination)])
    output = b''
    sent_confirmation = sent_words = False
    deadline = time.monotonic() + 15
    status = None
    try:
        while time.monotonic() < deadline:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    chunk = b''
                output += chunk
            if b'Type approve followed' in output and not sent_confirmation:
                os.write(fd, (confirmation + '\n').encode()); sent_confirmation = True
            if b'Input is hidden:' in output and not sent_words:
                os.write(fd, (words + '\n').encode()); sent_words = True
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                return os.waitstatus_to_exitcode(status), output.decode(errors='replace')
        os.kill(pid, 9); os.waitpid(pid, 0)
        raise AssertionError('terminal approval fixture timed out')
    finally:
        os.close(fd)


def terminal_checks(skill, project, work, pipe_only=False):
    destination = work / 'terminal-approval.json'
    if destination.exists(): destination.unlink()
    status, output = terminal_run(skill, project, destination, piped=True)
    assert status != 0 and not destination.exists(), 'piped approval was accepted'
    if pipe_only: return
    assert 'without a pipe' in output
    status, output = terminal_run(skill, project, destination, wrong=True)
    assert status != 0 and not destination.exists(), 'wrong typed checksum was accepted'
    status, output = terminal_run(skill, project, destination, words='password=synthetic-typed-secret')
    assert status != 0 and not destination.exists(), 'unsafe words were recorded'
    assert 'synthetic-typed-secret' not in output, 'terminal echoed unsafe words'
    status, output = terminal_run(skill, project, destination)
    assert status == 0 and destination.exists(), 'terminal approval failed: ' + output
    record = json.loads(destination.read_text())
    assert record['words'] == 'I approve the local fixture changes.'
    assert destination.stat().st_mode & 0o777 == 0o600
    assert SECRET not in output + destination.read_text() and PASSPHRASE not in output + destination.read_text()
    return destination


def settings_check(path):
    settings = json.loads(path.read_text())
    asks = settings['permissions']['ask']
    for command in ('tofu apply planfile', 'tofu destroy', 'tofu -chdir=hosting apply planfile',
                    '/opt/bin/tofu apply planfile', 'sh /kit/scripts/approve.sh planfile record',
                    'python3 /kit/scripts/approval_gate.py approve planfile record',
                    'sh /kit/scripts/apply.sh planfile record'):
        assert any(fnmatch.fnmatchcase(command, rule[5:-1]) for rule in asks if rule.startswith('Bash(')), 'missing ask rule'


def encryption_checks(project, work):
    tofu(project, 'show', '-json', 'first.plan', expected=1,
         env={'TF_VAR_host_state_passphrase': 'different-synthetic-passphrase'})
    # The passphrase is ephemeral: even the decrypted saved JSON has no value for it.
    shown = tofu(project, 'show', '-json', 'first.plan').stdout
    assert PASSPHRASE not in shown
    state = (project / 'terraform.tfstate').read_bytes()
    assert json.loads(state)['encryption_version'] == 'v0'
    assert SECRET.encode() not in state and PASSPHRASE.encode() not in state
    plain = work / 'plaintext'; plain.mkdir()
    (plain / 'main.tf').write_text('resource "terraform_data" "plain" { input = "synthetic" }\n')
    tofu(plain, 'init', '-input=false')
    tofu(plain, 'plan', '-out=plain.plan', '-input=false')
    tofu(plain, 'apply', 'plain.plan')
    shutil.copy2(ROOT / 'tofu/encryption.tf', plain / 'encryption.tf')
    tofu(plain, 'plan', '-input=false', expected=1)
    tofu(plain, 'show', '-json', 'plain.plan', expected=1)
    print('Encryption passed: plan and state ciphertext, ephemeral passphrase, wrong key and plaintext refusals.')


def enforced_check(work, fragment, section):
    project = work / ('enforced-' + section)
    project.mkdir(exist_ok=True)
    # A future unencrypted fallback must fail while enforcement is enabled.
    text = fragment.replace('    state {', '    method "unencrypted" "unsafe" {}\n    state {')
    text = text.replace('    ' + section + ' {', '    ' + section + ' {\n      fallback { method = method.unencrypted.unsafe }')
    (project / 'encryption.tf').write_text(text)
    result = run(['tofu', 'plan', '-input=false', '-no-color'], cwd=project, env=ENV, expected=None)
    assert result.returncode != 0 and 'unencrypted' in result.stdout.lower(), 'unencrypted fallback accepted'


def encryption_removals(work):
    fragment = (ROOT / 'tofu/encryption.tf').read_text()
    for section in ('state', 'plan'):
        enforced_check(work, fragment, section)
        before = '    ' + section + ' {\n      method = method.aes_gcm.host\n      enforced = true'
        assert before in fragment
        weakened = fragment.replace(before, before.replace('true', 'false'))
        try: enforced_check(work, weakened, section)
        except AssertionError: print('Protection removal detected: enforced ' + section + ' encryption')
        else: raise AssertionError('encryption enforcement removal escaped check')
    project = work / 'non-ephemeral'; project.mkdir()
    (project / 'encryption.tf').write_text(fragment.replace('  ephemeral = true\n', ''))
    (project / 'main.tf').write_text('resource "terraform_data" "local" { input = "synthetic" }\n')
    tofu(project, 'init', '-input=false')
    tofu(project, 'plan', '-out=planfile', '-input=false')
    shown = tofu(project, 'show', '-json', 'planfile').stdout
    try: assert PASSPHRASE not in shown, 'passphrase persisted in plan'
    except AssertionError: print('Protection removal detected: ephemeral passphrase')
    else: raise AssertionError('ephemeral removal escaped check')


def diagnostic_check(gate, project):
    # Provider errors and successful output are both untrusted and can contain values.
    original = gate.tofu
    def failed(*args):
        if args[0] == 'show': return subprocess.CompletedProcess(args, 1, SECRET.encode(), SECRET.encode())
        return original(*args)
    with gate.saved_plan(project / 'first.plan') as (snapshot, sha), patch.object(gate, 'tofu', side_effect=failed):
        error, output = capture(lambda: gate.read_plan(snapshot))
    assert error and SECRET not in error + output
    assert 'Raw diagnostics are withheld' in error


def incomplete_check(gate, project):
    original = gate.tofu
    def incomplete(*args):
        result = original(*args)
        if args[0] == 'show':
            value = json.loads(result.stdout)
            value['complete'] = False
            return subprocess.CompletedProcess(args, 0, json.dumps(value).encode(), b'')
        return result
    with gate.saved_plan(project / 'first.plan') as (snapshot, sha), patch.object(gate, 'tofu', side_effect=incomplete):
        error, output = capture(lambda: gate.read_plan(snapshot))
        assert error and 'incomplete' in error, 'incomplete plan was accepted for approval'
        assert gate.read_plan(snapshot, require_complete=False)['changes']


def mutations(work, project):
    scratch = work / 'mutated-skill'
    shutil.copytree(SKILL, scratch)
    script = scratch / 'scripts/approval_gate.py'
    original = script.read_text()
    cases = [
        ('approval record gate', "    record = validate_record(record_path)", "    record = validate_record(record_path)"),
        ('checksum match', "if record['plan_sha256'] != sha:", 'if False:'),
        ('replacement binding', "        match_record(record, sha, summary)", '        pass'),
        ('changed bytes binding', "        match_record(record, sha, summary)", '        pass'),
        ('summary match', "if record['summary'] != summary:", 'if False:'),
        ('typed checksum match', "if record['confirmation'] != 'approve ' + short_hash(sha):", 'if False:'),
        ('last checksum check', 'if digest(Path(path).read_bytes()) != sha:', 'if False:'),
        ('destroy order', "0 if 'delete' in actions else 1", '1'),
        ('destroy visibility', "result['changes'].append(f'{verb}: {name}.')", "\n        if 'delete' not in actions: result['changes'].append(f'{verb}: {name}.')"),
        ('opened ports', 'if name in PORTS:', 'if False:'),
        ('sensitive masks', 'if sensitive_before is True or sensitive_after is True or unknown is True:', 'if False:'),
        ('unknown masks', ' or unknown is True:', ':'),
        ('unknown resource', 'if kind not in KNOWN_TYPES:', 'if False:'),
        ('storage warning', "if actions != ['no-op'] and isinstance(kind, str) and re.search(r'bucket|volume|disk|database|db_instance', kind):", 'if False:'),
        ('key-loss warning', "result['irreversible'].append(KEY_WARNING)", "result['irreversible'].append('Warning removed.')"),
        ('complete plan gate', "if require_complete and (plan.get('deferred_changes') or plan.get('complete') is False):", 'if False:'),
        ('diagnostic redaction', "if shown.returncode:\n        refuse(", "if shown.returncode:\n        print(shown.stderr.decode())\n        refuse("),
        ('terminal-only input', 'if not sys.stdin.isatty() or not sys.stdout.isatty():', 'if False:'),
    ]
    for name, old, new in cases:
        if name == 'approval record gate':
            start = original.index('    if not Path(record_path).is_file():', original.index('def apply('))
            end = original.index('\n\ndef main():', start)
            mutated = original[:start] + "    with saved_plan(path) as (snapshot, sha):\n        read_plan(snapshot)\n        unchanged(path, sha)\n        tofu('apply', snapshot)\n" + original[end:]
        else:
            assert old in original, name
            mutated = original.replace(old, new, 1)
        script.write_text(mutated)
        gate = load(scratch)
        try:
            if name == 'terminal-only input': terminal_checks(scratch, project, work, pipe_only=True)
            elif name == 'complete plan gate': incomplete_check(gate, project)
            elif name == 'diagnostic redaction': diagnostic_check(gate, project)
            elif name == 'approval record gate': apply_case(gate, project, 'missing')
            elif name == 'checksum match':
                for case in ('checksum', 'replaced', 'appended'): apply_case(gate, project, case)
            elif name == 'replacement binding': apply_case(gate, project, 'replaced')
            elif name == 'changed bytes binding': apply_case(gate, project, 'appended')
            elif name == 'summary match': apply_case(gate, project, 'summary')
            elif name == 'typed checksum match': apply_case(gate, project, 'confirmation')
            elif name == 'last checksum check': apply_case(gate, project, 'race')
            else: summary_checks(gate)
        except AssertionError:
            print('Protection removal detected: ' + name)
        else:
            raise AssertionError('protection removal escaped its outcome check: ' + name)
        finally:
            script.write_text(original)
    # Separate schema and shared-reader removals use the same contract assertions.
    schema_path = scratch / 'resources/contracts/approval-record.schema.json'
    schema_original = schema_path.read_text()
    schema = json.loads(schema_original)
    for name in ('references', 'required fields'):
        changed = copy.deepcopy(schema)
        if name == 'required fields': changed['required'] = []
        else:
            changed['properties']['words'].pop('pattern')
            for value in changed['properties']['summary']['properties'].values(): value['items'].pop('pattern')
        schema_path.write_text(json.dumps(changed))
        try:
            record_checks(load(scratch), work)
        except AssertionError:
            print('Protection removal detected: approval ' + name)
        else:
            raise AssertionError('approval schema removal escaped checks')
        finally: schema_path.write_text(schema_original)
    reader = scratch / 'resources/record_validation.py'
    reader_original = reader.read_text()
    reader.write_text(reader_original.replace("'capabilities', 'approval-record'):", "'capabilities'):", 1))
    try:
        record_checks(load(scratch), work)
    except AssertionError:
        print('Protection removal detected: approval secret-text scan')
    else: raise AssertionError('secret scan removal escaped checks')
    finally: reader.write_text(reader_original)
    settings = work / 'settings.json'
    settings.write_text('{"permissions":{"ask":[]}}')
    try: settings_check(settings)
    except AssertionError: print('Protection removal detected: agent ask rules')
    else: raise AssertionError('missing ask rules escaped checks')


def installer_checks(work):
    source = ROOT / '.agents/tools/install-tofu.py'
    scratch = work / 'installer-source/.agents/tools/install-tofu.py'
    scratch.parent.mkdir(parents=True)
    original = source.read_text()
    def archive(content):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zipped: zipped.writestr('tofu', content)
        return buffer.getvalue()
    good = archive(b'synthetic executable fixture')
    changed = archive(b'different executable fixture')
    expected = hashlib.sha256(good).hexdigest()
    def check(text, suffix):
        scratch.write_text(text)
        spec = importlib.util.spec_from_file_location('installer', scratch)
        installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
        with patch.object(installer.platform, 'system', return_value='Linux'), \
             patch.object(installer.platform, 'machine', return_value='x86_64'), \
             patch.object(installer, 'CHECKSUMS', {'linux_amd64':expected}):
            for case, checksum, data in [('valid', expected, good), ('published', 'b' * 64, good), ('archive', expected, changed)]:
                destination = work / ('install-' + suffix + '-' + case)
                def response(url, **kwargs):
                    content = (checksum + '  tofu_1.13.2_linux_amd64.zip\n').encode() if url.endswith('SHA256SUMS') else data
                    return io.BytesIO(content)
                with patch.object(installer.urllib.request, 'urlopen', side_effect=response):
                    error, output = capture(lambda: installer.install(destination))
                if case == 'valid':
                    assert not error and (destination / 'tofu').read_bytes() == b'synthetic executable fixture'
                else:
                    assert error and not destination.exists(), 'installer accepted unchecked bytes: ' + case
    check(original, 'baseline')
    for name, old in [('published checksum pin', "if published != [CHECKSUMS[target]]:"),
                      ('archive checksum', 'if hashlib.sha256(archive).hexdigest() != CHECKSUMS[target]:')]:
        assert old in original
        try: check(original.replace(old, 'if False:'), name.replace(' ', '-'))
        except AssertionError: print('Protection removal detected: ' + name)
        else: raise AssertionError('installer checksum removal escaped checks')


def main():
    if not shutil.which('tofu'):
        print('could not check: install the pinned OpenTofu with .agents/tools/install-tofu.py and add it to PATH')
        return 2
    version = run(['tofu', 'version', '-json']).stdout
    if json.loads(version)['terraform_version'] != '1.13.2':
        print('could not check: these tests require OpenTofu 1.13.2')
        return 2
    with tempfile.TemporaryDirectory(prefix='ai-host-kit-approval-checks-') as temp, patch.dict(os.environ, ENV):
        work = Path(temp)
        cli_config = work / 'empty-tofu-config'
        cli_config.write_text('')
        os.environ['TF_CLI_CONFIG_FILE'] = str(cli_config)
        project = fixture_plans(work)
        with directory(project):
            gate = load()
            summary_checks(gate)
            print('Network JSON fixture passed: ports, widened sources, public access, destruction, unknown types and redaction.')
            record_checks(gate, work)
            for case in ('missing', 'malformed', 'checksum', 'summary', 'confirmation', 'replaced', 'appended', 'race', 'valid'):
                apply_case(gate, project, case)
                print('Saved-plan approval case passed: ' + case)
            cli = [sys.executable, SKILL / 'scripts/approval_gate.py']
            result = run(cli + ['apply', project / 'first.plan', work / 'absent.json'], cwd=project, env=ENV, expected=1)
            assert 'No approval record' in result.stdout
            result = run(cli + ['approve', project / 'first.plan', work / 'pipe.json'], cwd=project, env=ENV, input='approve anything\n', expected=1)
            assert 'terminal' in result.stdout and not (work / 'pipe.json').exists()
            approval = terminal_checks(SKILL, project, work)
            run(cli + ['apply', project / 'first.plan', approval], cwd=project, env=ENV)
            print('Synthetic terminal approval and exact-plan apply passed; pipe, wrong checksum and unsafe words refused.')
            # Build real replacement and destroy plans against the fixture state.
            tofu(project, 'plan', '-var=fixture_value=third fixture', '-out=replace.plan', '-input=false')
            tofu(project, 'plan', '-destroy', '-out=destroy.plan', '-input=false')
            for name in ('replace.plan', 'destroy.plan'):
                result = run(cli + ['summary', project / name], cwd=project, env=ENV)
                assert 'terraform_data.keep' in result.stdout and 'estroy' in result.stdout
                assert SECRET not in result.stdout
            encryption_checks(project, work)
            encryption_removals(work)
            diagnostic_check(gate, project)
            incomplete_check(gate, project)
            settings_check(ROOT / '.claude/settings.json')
            mutations(work, project)
            installer_checks(work)
            from approval_regressions import run_regressions
            run_regressions(sys.modules[__name__], work / 'review-regressions')
    print('Approval gate checks passed. All fixtures are local; no provider, cloud, model or person approval was used.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
