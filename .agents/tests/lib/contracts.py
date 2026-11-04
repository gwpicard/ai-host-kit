"""Check record rejection, field messages, version handling and vendor comparison."""
import copy
import json
from pathlib import Path
import sys
import tempfile

from checks import ROOT, run

TOOLS = ROOT / '.agents/tools'
sys.path.insert(0, str(TOOLS))
from record_validation import dependencies, SCHEMAS

FIXTURES = ROOT / '.agents/tests/fixtures/contracts'
VALIDATE = [sys.executable, TOOLS / 'record_validation.py']
VENDOR = [sys.executable, TOOLS / 'check-handover-vendor.py']


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
    future = run(VALIDATE + ['handover', FIXTURES / 'handover/future-minor.json'])
    for field in ('optional_note', 'limits.optional_limit'):
        assert field + ': unknown optional field; ignored' in future.stdout, future.stdout
    cases = json.loads((FIXTURES / 'invalid-cases.json').read_text())
    actual = {str(p.relative_to(FIXTURES)) for p in FIXTURES.glob('*/invalid-*.json')}
    assert actual == {case['file'] for case in cases}, 'every invalid fixture needs an expected field'
    for case in cases:
        result = run(VALIDATE + [case['kind'], FIXTURES / case['file']], expected=1)
        assert case['field'] + ':' in result.stdout, result.stdout
        assert 'valid:' not in result.stdout
        assert 'example-value-that-must-not-be-shown' not in result.stdout
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
        vendor_fixtures = FIXTURES / 'vendoring'
        args = VENDOR + ['--vendored', vendor_fixtures / 'copy.schema.json']
        matched = run(args + ['--published', vendor_fixtures / 'published-match.schema.json'])
        assert 'passed:' in matched.stdout
        different = run(args + ['--published', vendor_fixtures / 'published-different.schema.json'], expected=1)
        assert 'differs' in different.stdout and 'passed' not in different.stdout
        for command in (VENDOR, args + ['--published', work / 'absent.json']):
            missing = run(command, expected=2)
            assert 'could not check:' in missing.stdout and 'passed' not in missing.stdout
            if command == VENDOR:
                print('Actual published comparison: ' + missing.stdout.strip())
        # Exercise the actual default copy, not just the small comparison fixture.
        sample.write_bytes((ROOT / SCHEMAS['handover']).read_bytes())
        run(VENDOR + ['--published', sample])
        sample.write_bytes(sample.read_bytes() + b'\n')
        run(VENDOR + ['--published', sample], expected=1)
        sample.write_text('{}')
        run(args + ['--published', sample], expected=1)
    print(f'All three schemas, valid fixtures and {len(cases)} field-specific refusals passed.')
    print('Version handling, withheld values and match, drift and unavailable vendor outcomes passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
