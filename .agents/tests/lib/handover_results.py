"""Check handover compatibility and the published request and result definitions."""
import contextlib
import copy
import io
import sys

from checks import ROOT, run
from record_validation import SCHEMAS, dependencies, read_json, validate

FIXTURES = ROOT / '.agents/tests/fixtures/contracts'


def checks():
    validator, formats = dependencies()
    schema = read_json(ROOT / SCHEMAS['handover'])
    published = validator(schema, format_checker=formats)
    # Compare the reader with the published contract, including invalid fixtures.
    paths = sorted((FIXTURES / 'handover').glob('*.json'))
    for path in paths:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = validate('handover', path)
        assert (status == 0) == published.is_valid(read_json(path)), path.name
    for name, version in (('valid.json', '1.0'), ('valid-1-1.json', '1.1')):
        path = FIXTURES / 'handover' / name
        assert read_json(path)['schema_version'] == version
        # Use the skill entry point, which locates its bundled reader and schema.
        reader = ROOT / '.agents/skills/host-fit/scripts/host_fit.py'
        output = run([sys.executable, reader, 'fit', '--handover', path, '--recipe', 'azure']).stdout
        assert 'residency: unknown' in output
    print(f'Published schema and Host Kit agree on all {len(paths)} handover fixtures; 1.0 and 1.1 pass both readers.')

    # Results are transient documents. Validate the definitions without imposing
    # the handover object's required fields on a request or result.
    def definition(name):
        return validator({'$schema': schema['$schema'], '$defs': schema['$defs'],
                          '$ref': '#/$defs/' + name}, format_checker=formats)

    request_schema = definition('request')
    result_schema = definition('response')
    exchanges = read_json(FIXTURES / 'request-results.json')
    assert {case['request']['action'] for case in exchanges} == {'preview', 'logs', 'health', 'release'}
    for case in exchanges:
        request, result = case['request'], case['result']
        request_schema.validate(request)
        result_schema.validate(result)
        assert result['action'] == request['action']
        if request['action'] in ('preview', 'release'):
            assert result['commit'] == request['commit']
            assert result['migration'] == request.get('migration', False)
        # All statuses must retain the fields that bind a result to its request.
        fields = ['action']
        if result['action'] in ('preview', 'release'):
            fields += ['commit', 'migration', 'rehearsal']
        if result['action'] in ('health', 'release'):
            fields += ['running_commit']
        for status in ('passed', 'failed', 'could-not-check'):
            candidate = copy.deepcopy(result)
            candidate['status'] = status
            candidate.pop('reason', None)
            if status == 'passed' and candidate.get('migration'):
                candidate['rehearsal']['status'] = 'passed'
            result_schema.validate(candidate)
            for field in fields:
                incomplete = copy.deepcopy(candidate)
                del incomplete[field]
                assert not result_schema.is_valid(incomplete), (result['action'], status, field)

    contradictory = read_json(FIXTURES / 'contradictory-result.json')
    errors = list(result_schema.iter_errors(contradictory))
    assert errors, 'held release accepted a rehearsal outcome that contradicts its reason'
    repaired = copy.deepcopy(contradictory)
    repaired['rehearsal']['status'] = 'failed'
    result_schema.validate(repaired)
    # Exercise both migration branches and the passed-result rule on each action.
    for action in ('preview', 'release'):
        baseline = next(case['result'] for case in exchanges
                        if case['result']['action'] == action and case['result']['status'] == 'passed')
        for migration, rehearsal in ((False, 'passed'), (True, 'not-needed'), (True, 'failed')):
            candidate = copy.deepcopy(baseline)
            candidate.update(migration=migration, rehearsal=dict(status=rehearsal, evidence='checks/rehearsal.txt'))
            assert not result_schema.is_valid(candidate), (action, migration, rehearsal)
        for commit in ('a' * 39, 'a' * 41, 'a' * 40 + '\n'):
            candidate = dict(baseline, commit=commit)
            assert not result_schema.is_valid(candidate), (action, 'incomplete commit')
    held = next(case['result'] for case in exchanges if case['result']['status'] == 'held')
    for candidate in (dict(held, reason='other'), {k: v for k, v in held.items() if k != 'reason'},
                      dict(held, status='failed')):
        assert not result_schema.is_valid(candidate), 'held-release reason rule was not enforced'
    for action in ('health', 'release'):
        baseline = next(case['result'] for case in exchanges if case['result']['action'] == action)
        result_schema.validate(dict(baseline, running_commit=None))
        assert not result_schema.is_valid(dict(baseline, running_commit='a' * 39))
    print('All four request and result actions pass; missing bindings, incomplete commits and contradictory rehearsals are refused by the schema.')
