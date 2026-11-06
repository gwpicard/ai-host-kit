"""Check record rejection, field messages, version handling and vendor comparison."""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

from checks import ROOT, run

TOOLS = ROOT / '.agents/tools'
sys.path.insert(0, str(TOOLS))
from record_validation import dependencies, field_path, SCHEMAS, validate

FIXTURES = ROOT / '.agents/tests/fixtures/contracts'
VALIDATE = [sys.executable, TOOLS / 'record_validation.py']
VENDOR = [sys.executable, TOOLS / 'check-handover-vendor.py']


def vendor_checks(work):
    spec = importlib.util.spec_from_file_location('handover_vendor', TOOLS / 'check-handover-vendor.py')
    vendor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    fixtures = FIXTURES / 'vendoring'
    schema_copy = ROOT / SCHEMAS['handover']
    duplicate = work / 'duplicate.json'
    duplicate.write_bytes(schema_copy.read_bytes())
    for supplied in (schema_copy, duplicate, fixtures / 'published-match.schema.json'):
        refused = run(VENDOR + ['--published', supplied], expected=2)
        assert 'passed:' not in refused.stdout and 'matches the published copy' not in refused.stdout
    assert vendor.same_bytes(schema_copy.read_bytes(), duplicate.read_bytes())
    assert vendor.same_bytes((fixtures / 'copy.schema.json').read_bytes(),
                             (fixtures / 'published-match.schema.json').read_bytes())
    assert not vendor.same_bytes((fixtures / 'copy.schema.json').read_bytes(),
                                 (fixtures / 'published-different.schema.json').read_bytes())

    repo = work / 'upstream'; repo.mkdir()
    run(['git', 'init', '-q', '-b', 'main', repo])
    upstream_file = repo / 'handover.schema.json'
    upstream_file.write_bytes(schema_copy.read_bytes())
    run(['git', 'add', '.'], cwd=repo)
    run(['git', '-c', 'user.name=Guillaume Picard', '-c', 'user.email=rehearsal@example.invalid',
         '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Save the schema fixture'], cwd=repo)
    commit = run(['git', 'rev-parse', 'HEAD'], cwd=repo).stdout.strip()
    blob = run(['git', 'rev-parse', 'HEAD:handover.schema.json'], cwd=repo).stdout.strip()
    assert run(['git', 'tag'], cwd=repo).stdout == ''
    pin = dict(repository=vendor.REPOSITORY, ref='main', commit=commit, blob=blob,
               path='handover.schema.json', sha256=hashlib.sha256(schema_copy.read_bytes()).hexdigest())
    # An inherited repository override must not redirect the vendor's Git calls.
    with patch.dict(vendor.os.environ, {'GIT_DIR': str(ROOT / '.git')}):
        observed = vendor.git(repo, 'rev-parse', 'HEAD').decode().strip()
    assert observed == commit, 'vendor Git environment filtering did not preserve the selected repository'
    # Inherited configuration must not rewrite the repository being fetched.
    with patch.dict(vendor.os.environ, {
            'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': 'url.' + str(work / 'absent') + '.insteadOf',
            'GIT_CONFIG_VALUE_0': str(repo)}):
        assert vendor.confirmed_upstream(pin, _test_repository=repo) == schema_copy.read_bytes()
    print('Vendor Git environment filtering ignores repository and URL rewrite overrides.')
    confirmed = vendor.confirmed_upstream
    # Exercise main's status and messages, replacing only the pin reader and
    # transport. The production pin reader and CLI have no override mechanism.
    def check(candidate, expected, phrase, source=repo):
        output = io.StringIO()
        with patch.object(vendor, 'saved_pin', return_value=candidate), \
             patch.object(vendor, 'VENDORED', duplicate), \
             patch.object(vendor, 'confirmed_upstream', side_effect=lambda p: confirmed(p, _test_repository=source)), \
             patch.object(sys, 'argv', ['check-handover-vendor.py']), contextlib.redirect_stdout(output):
            status = vendor.main()
        message = output.getvalue()
        assert status == expected, message
        assert phrase in message, message
        if expected:
            assert 'passed:' not in message
        print('Vendor fixture: ' + message.strip())
    check(None, 2, 'could not check:')
    check(pin, 0, 'matches the published copy byte for byte')
    duplicate.write_bytes(duplicate.read_bytes() + b'\n')
    check(pin, 1, 'differs')
    duplicate.write_bytes(schema_copy.read_bytes())
    check(pin, 2, 'could not check:', source=work / 'absent-repository')
    check(dict(pin, blob='0' * 40), 2, 'blob')
    check(dict(pin, sha256='0' * 64), 2, 'SHA-256')
    check(dict(pin, commit='0' * 40), 2, 'pinned commit')
    check(dict(pin, path='absent.json'), 2, 'could not check:')
    check(dict(pin, repository=str(repo)), 2, 'must name the AI Build Kit repository')
    check(dict(pin, _test_repository=str(repo)), 2, 'unsupported fields')
    check({}, 2, 'incomplete')
    # A fetched commit on a separate branch cannot claim membership of main.
    run(['git', 'checkout', '-qb', 'side'], cwd=repo)
    upstream_file.write_bytes(schema_copy.read_bytes() + b'\n')
    run(['git', 'add', '.'], cwd=repo)
    run(['git', '-c', 'user.name=Guillaume Picard', '-c', 'user.email=rehearsal@example.invalid',
         '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Change the schema fixture'], cwd=repo)
    side = run(['git', 'rev-parse', 'HEAD'], cwd=repo).stdout.strip()
    check(dict(pin, commit=side), 2, 'not reachable from the named ref')
    run(['git', 'checkout', '-q', 'main'], cwd=repo)
    # A later branch tip still confirms the original ancestor commit.
    (repo / 'note').write_text('fixture')
    run(['git', 'add', '.'], cwd=repo)
    run(['git', '-c', 'user.name=Guillaume Picard', '-c', 'user.email=rehearsal@example.invalid',
         '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Advance the fixture branch'], cwd=repo)
    check(pin, 0, 'matches the published copy')
    # A pin must be committed and unchanged in the working tree.
    pin_file = repo / vendor.PIN
    pin_file.parent.mkdir(parents=True)
    pin_file.write_text('null\n')
    with patch.object(vendor, 'ROOT', repo):
        try:
            vendor.saved_pin()
            raise AssertionError('an untracked pin was accepted')
        except vendor.CouldNotCheck:
            pass
        run(['git', 'add', '.'], cwd=repo)
        run(['git', '-c', 'user.name=Guillaume Picard', '-c', 'user.email=rehearsal@example.invalid',
             '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Save the empty fixture pin'], cwd=repo)
        assert vendor.saved_pin() is None
        pin_file.write_text(json.dumps(pin))
        try:
            vendor.saved_pin()
            raise AssertionError('an unsaved pin was accepted')
        except vendor.CouldNotCheck as exc:
            assert 'unsaved changes' in str(exc)
    # Test the real CLI in a source copy with an empty saved pin. Never invoke
    # the current checkout's default command: a future pin may fetch upstream.
    cli_tools = repo / '.agents/tools'
    cli_tools.mkdir(parents=True)
    for name in ('check-handover-vendor.py', 'record_validation.py'):
        shutil.copyfile(TOOLS / name, cli_tools / name)
    cli = [sys.executable, cli_tools / 'check-handover-vendor.py']
    missing = run(cli, expected=2)
    assert 'unsaved changes' in missing.stdout and 'passed:' not in missing.stdout
    pin_file.write_text('null\n')
    missing = run(cli, expected=2)
    assert 'could not check: no published AI Build Kit schema is pinned' in missing.stdout
    assert 'passed:' not in missing.stdout
    # The tracked format cannot enable local transport, even with a real commit.
    pin_file.write_text(json.dumps(dict(pin, repository=str(repo))))
    run(['git', 'add', vendor.PIN], cwd=repo)
    run(['git', '-c', 'user.name=Guillaume Picard', '-c', 'user.email=rehearsal@example.invalid',
         '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Save an invalid fixture pin'], cwd=repo)
    missing = run(cli, expected=2)
    assert 'must name the AI Build Kit repository' in missing.stdout
    assert 'passed:' not in missing.stdout
    print('Caller files cannot establish publication; saved pin, reachability, blob, hash and byte checks passed without network access.')


def reference_checks(work):
    sample = work / 'reference.json'
    fields = {
        'host-record': [('address',), ('health_address',), ('last_backup_check', 'evidence'),
                        ('last_restore_drill', 'evidence')],
        'place-record': [('backup_storage', 'location'), ('encrypted_state', 'location'),
                         ('tools', 0, 'host_record')],
    }
    for kind, paths in fields.items():
        for parts in paths:
            for suffix in ('?token=synthetic-secret-marker', '#synthetic-secret-marker', ''):
                record = json.loads((FIXTURES / kind / 'valid.json').read_text())
                obj = record
                for part in parts[:-1]:
                    obj = obj[part]
                obj[parts[-1]] = ('https://user:synthetic-secret-marker@example.invalid/ref' if not suffix
                                 else 'https://example.invalid/ref' + suffix)
                sample.write_text(json.dumps(record))
                output = run(VALIDATE + [kind, sample], expected=1).stdout
                assert field_path(parts) + ':' in output and 'synthetic-secret-marker' not in output
    for kind, paths in fields.items():
        for parts in paths:
            for reference in ('https://example.invalid:8443/check.txt',
                              'https://example.invalid/ref%3Ftoken',
                              'https://example.invalid/ref\n'):
                record = json.loads((FIXTURES / kind / 'valid.json').read_text())
                obj = record
                for part in parts[:-1]:
                    obj = obj[part]
                obj[parts[-1]] = reference
                sample.write_text(json.dumps(record))
                expected = 0 if reference.endswith('check.txt') else 1
                output = run(VALIDATE + [kind, sample], expected=expected).stdout
                if expected:
                    assert field_path(parts) + ':' in output
    # Descriptions are published metadata, not an extra Host Kit refusal.
    record = json.loads((FIXTURES / 'handover/valid.json').read_text())
    record['config'][0]['description'] = 'Database connection supplied at runtime'
    record['tool']['x' * 64] = {'optional_note': 'Future declaration'}
    sample.write_text(json.dumps(record))
    run(VALIDATE + ['handover', sample])
    # Both declaration kinds stay closed, even under future minor versions.
    for kind in ('secret', 'setting'):
        record = json.loads((FIXTURES / 'handover/valid.json').read_text())
        record['schema_version'] = '1.99'
        record['config'][0].update(kind=kind, extra={'nested': ['synthetic-secret-marker']})
        sample.write_text(json.dumps(record))
        output = run(VALIDATE + ['handover', sample], expected=1).stdout
        assert 'config[0].extra:' in output and 'synthetic-secret-marker' not in output
    # Fixed messages withhold each obvious assignment and key marker.
    for content in ('key=', 'token=', 'sig=', 'password=', 'API_KEY =', 'TOKEN:',
                    '-----BEGIN ' + 'PRIVATE KEY-----', '0123456789abcdef' * 4):
        record = json.loads((FIXTURES / 'host-record/valid.json').read_text())
        record['recipe'] = content + 'synthetic-secret-marker'
        sample.write_text(json.dumps(record))
        output = run(VALIDATE + ['host-record', sample], expected=1).stdout
        assert 'recipe:' in output and 'synthetic-secret-marker' not in output
    print('All address, storage and evidence fields refuse URL credentials, queries and fragments.')


def string_checks(work):
    sample = work / 'string.json'
    def check(kind, expected):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = validate(kind, sample)
        assert status == expected, f'{kind}: expected status {expected}, got {status}: {output.getvalue()}'
        return output.getvalue()

    def strings(value, path=()):
        if isinstance(value, dict):
            for key, child in value.items():
                yield from strings(child, path + (key,))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from strings(child, path + (index,))
        elif isinstance(value, str):
            yield path

    for kind in SCHEMAS:
        baseline = json.loads((FIXTURES / kind / 'valid.json').read_text())
        if kind == 'handover':
            baseline['postgres']['extensions'] = ['pgcrypto']
        for parts in strings(baseline):
            for reference in ('https://user:synthetic-secret-marker@example.invalid/ref',
                              'https://example.invalid/ref?synthetic-secret-marker',
                              'https://example.invalid/ref#synthetic-secret-marker',
                              'https://example.invalid/ref%3Fsynthetic-secret-marker',
                              'https://example.invalid/ref\\synthetic-secret-marker'):
                record = copy.deepcopy(baseline)
                obj = record
                for part in parts[:-1]:
                    obj = obj[part]
                # Preserve the five-part cron rule so only the URL rule refuses it.
                obj[parts[-1]] = reference + (' 0 * * *' if parts[-1] == 'cron' else '')
                sample.write_text(json.dumps(record))
                output = check(kind, 1)
                assert field_path(parts) + ':' in output and reference not in output
                assert 'synthetic-secret-marker' not in output

    for parts in (('health', 'path'), ('sign_in', 'staff', 'redirect_path')):
        for reference in ('/api/health', '//user:synthetic-secret-marker@example.invalid',
                          '/api?synthetic-secret-marker', '/api#synthetic-secret-marker',
                          '/api%3Fsynthetic-secret-marker', '/api\\synthetic-secret-marker',
                          '/api\n'):
            record = json.loads((FIXTURES / 'handover/valid.json').read_text())
            obj = record
            for part in parts[:-1]:
                obj = obj[part]
            obj[parts[-1]] = reference
            sample.write_text(json.dumps(record))
            expected = 0 if reference in ('/api/health', '//user:synthetic-secret-marker@example.invalid', '/api%3Fsynthetic-secret-marker', '/api\\synthetic-secret-marker', '/api\n') else 1
            output = check('handover', expected)
            if expected:
                assert field_path(parts) + ':' in output and reference not in output

    for kind, parts in (('handover', ('processes', 'web', 'command')),
                        ('host-record', ('gaps', 0, 'reason')),
                        ('place-record', ('network', 'private_access'))):
        for suffix, expected in (('', 1 if kind == 'handover' else 0), ('?synthetic-secret-marker', 1)):
            record = json.loads((FIXTURES / kind / 'valid.json').read_text())
            obj = record
            for part in parts[:-1]:
                obj = obj[part]
            obj[parts[-1]] = 'Use https://example.invalid/ref' + suffix + ' for details.'
            sample.write_text(json.dumps(record))
            output = check(kind, expected)
            if expected:
                assert field_path(parts) + ':' in output and 'synthetic-secret-marker' not in output

    digest = hashlib.sha256(b'synthetic image contents').hexdigest()
    for reference, expected in (
            ('registry.example.invalid/team/tool:v1.2', 0),
            ('registry.example.invalid:5000/team/tool:previous', 0),
            ('localhost:5000/tool@sha256:' + digest, 0),
            ('registry.example.invalid/tool', 1),
            ('registry.example.invalid/tool@sha256:abc', 1),
            ('registry.example.invalid/tool:previous?synthetic-secret-marker', 1),
            ('registry.example.invalid/tool:previous#synthetic-secret-marker', 1),
            ('user:synthetic-secret-marker@registry.example.invalid/tool:previous', 1),
            ('registry.example.invalid/tool:previous\n', 1)):
        record = json.loads((FIXTURES / 'host-record/valid.json').read_text())
        # A digest is allowed at any rollback index, but stays subject to scanning elsewhere.
        record['rollback_targets'].append(copy.deepcopy(record['rollback_targets'][0]))
        record['rollback_targets'][1]['image'] = reference
        sample.write_text(json.dumps(record))
        output = check('host-record', expected)
        if expected:
            assert 'rollback_targets[1].image:' in output and reference not in output
        else:
            assert 'valid:' in output
    record['recipe'] = digest
    record['rollback_targets'][1]['image'] = 'registry.example.invalid/tool@sha256:' + digest
    sample.write_text(json.dumps(record))
    output = check('host-record', 1)
    assert 'recipe:' in output and digest not in output
    print('Every declared string field refuses credential-bearing URL forms; tagged and digested images pass.')


def main():
    loaded = dependencies()
    if loaded is None:
        print('could-not-run: schema validation needs .agents/tools/schema-requirements.txt')
        return 2
    validator, formats = loaded
    for kind, schema_path in SCHEMAS.items():
        validator.check_schema(json.loads((ROOT / schema_path).read_text()))
        run(VALIDATE + [kind, FIXTURES / kind / 'valid.json'])
    run(VALIDATE + ['handover', FIXTURES / 'handover/minimal.json'])
    run(VALIDATE + ['host-record', FIXTURES / 'host-record/found.json'])
    run(VALIDATE + ['place-record', FIXTURES / 'place-record/choice.json'])
    future = run(VALIDATE + ['handover', FIXTURES / 'handover/future-minor.json'])
    for field in ('optional_note', 'limits.optional_limit'):
        assert field + ': unknown optional field; ignored' in future.stdout, future.stdout
    cases = json.loads((FIXTURES / 'invalid-cases.json').read_text())
    actual = {str(p.relative_to(FIXTURES)) for p in FIXTURES.glob('*/invalid-*.json')}
    assert actual == {case['file'] for case in cases}, 'every invalid fixture needs an expected field'
    for case in cases:
        result = run(VALIDATE + [case['kind'], FIXTURES / case['file']], expected=None)
        assert result.returncode == 1, case['file'] + ': expected refusal; ' + result.stdout
        assert case['field'] + ':' in result.stdout, result.stdout
        assert 'valid:' not in result.stdout
        assert 'example-value-that-must-not-be-shown' not in result.stdout
        assert 'synthetic-secret-marker' not in result.stdout
        if 'withheld' in case:
            assert case['withheld'] not in result.stdout
        print('Refused: ' + case['file'] + ' names ' + case['field'])
    major = run(VALIDATE + ['handover', FIXTURES / 'handover/invalid-major.json'], expected=1)
    assert 'major version is not supported' in major.stdout and 'update AI Host Kit' in major.stdout
    with tempfile.TemporaryDirectory(prefix='ahk-contracts-') as folder:
        work = Path(folder)
        handover = json.loads((FIXTURES / 'handover/valid.json').read_text())
        sample = work / 'sample.json'
        # Known fields still fail in a newer minor version.
        future_bad = copy.deepcopy(handover)
        future_bad['schema_version'] = '1.99'
        future_bad['recovery']['max_restore_hours'] = -1
        sample.write_text(json.dumps(future_bad))
        assert 'recovery.max_restore_hours:' in run(VALIDATE + ['handover', sample], expected=1).stdout
        # All declared schedule runners are accepted; email links require email.
        for runner in ('worker', 'in-app', 'host-tick'):
            handover['jobs']['runner'] = runner
            sample.write_text(json.dumps(handover))
            run(VALIDATE + ['handover', sample])
        handover['sign_in']['outsiders'] = 'email-link'
        sample.write_text(json.dumps(handover))
        run(VALIDATE + ['handover', sample])
        del handover['email']
        sample.write_text(json.dumps(handover))
        assert 'email:' in run(VALIDATE + ['handover', sample], expected=1).stdout
        # Parser errors and wrong root types stay controlled and withhold values.
        for raw, field in (('{"schema_version":"1.0","schema_version":"1.0"}', 'schema_version'),
                           ('{"sensitive":"example-value-that-must-not-be-shown",}', '$'),
                           ('{"schema_version":NaN}', '$'), ('[]', '$')):
            sample.write_text(raw)
            result = run(VALIDATE + ['handover', sample], expected=1)
            assert field + ':' in result.stdout and 'example-value-that-must-not-be-shown' not in result.stdout
            assert 'Traceback' not in result.stdout
        missing = run([sys.executable, '-S', TOOLS / 'record_validation.py', 'handover', sample], expected=2)
        assert 'could not check:' in missing.stdout and 'valid:' not in missing.stdout
        vendor_checks(work)
        reference_checks(work)
        string_checks(work)
        from integration_regressions import checks as integration_checks
        integration_checks(work)
    print(f'All schemas, valid fixtures and {len(cases)} field-specific refusals passed.')
    print('Version handling, withheld values and match, drift and unavailable vendor outcomes passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
