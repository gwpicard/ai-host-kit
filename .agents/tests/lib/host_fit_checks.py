"""Outcome checks for local host choice, with mutations in disposable copies."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile

from checks import ROOT, run

SKILL = ROOT / '.agents/skills/host-fit'
FIXTURES = ROOT / '.agents/tests/fixtures/contracts'
EXPECTED = ROOT / '.agents/tests/fixtures/host-fit'


def load(skill=SKILL):
    sys.path.insert(0, str(skill / 'scripts'))
    sys.path.insert(0, str(skill / 'resources'))
    sys.modules.pop('record_validation', None)
    spec = importlib.util.spec_from_file_location('host_fit', skill / 'scripts/host_fit.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fit_checks(m, work):
    expected = json.loads((EXPECTED / 'fit-lines.json').read_text())
    assert set(expected) == {p.name for p in (FIXTURES / 'handover').glob('*.json') if not p.name.startswith('invalid-')}
    for name, lines in expected.items():
        h = m.handover(FIXTURES / 'handover' / name)
        for host in m.HOSTS:
            actual = [x['line'] for x in m.fit(h, m.RECIPES / host)]
            assert actual == lines, (name, host, actual)
            assert sum(x.startswith('residency:') for x in actual) == 1
    # Every invalid handover is refused without producing a misleading fit report.
    for case in json.loads((FIXTURES / 'invalid-cases.json').read_text()):
        if case['kind'] != 'handover':
            continue
        for host in m.HOSTS:
            result = run([sys.executable, SKILL / 'scripts/host_fit.py', 'fit', '--handover', FIXTURES / case['file'], '--recipe', host], expected=1)
            assert case['field'] + ':' in result.stdout and 'synthetic-secret-marker' not in result.stdout
    h = json.loads((FIXTURES / 'handover/valid.json').read_text())
    h['residency'] = 'uk'
    for host in m.HOSTS:
        rows = m.fit(h, m.RECIPES / host)
        line = next(x['line'] for x in rows if x['field'] == 'residency')
        assert line == ('residency: cannot - This host has no UK location; your data would be in Germany or Finland.' if host == 'coolify-hetzner' else 'residency: unknown')
    # Synthetic secret values in permitted handover text are never echoed.
    h['processes']['web']['command'] = 'synthetic-secret-marker'
    h['config'][0]['name'] = 'SYNTHETIC_SECRET_MARKER'
    for host in m.HOSTS:
        rendered = json.dumps(m.fit(h, m.RECIPES / host))
        assert 'synthetic-secret-marker' not in rendered and 'SYNTHETIC_SECRET_MARKER' not in rendered
    recipe = work / 'conditional'; recipe.mkdir(exist_ok=True)
    (recipe / 'capabilities.json').write_bytes((FIXTURES / 'capabilities/valid.json').read_bytes())
    rows = m.fit(h, recipe)
    assert next(x for x in rows if x['field'] == 'jobs.runner')['line'] == 'jobs.runner: met'
    h['jobs']['runner'] = 'host-tick'
    for duration, result in ((100,'satisfied'),(900,'not satisfied')):
        h['jobs']['longest_job_seconds'] = duration
        line = next(x for x in m.fit(h, recipe) if x['field'] == 'jobs.runner')['line']
        assert line == 'jobs.runner: met if - jobs.longest_job_seconds lte 300; ' + result
    for condition, expected in [({'field':'residency','operator':'eq','value':'uk'}, 'satisfied'), ({'field':'residency','operator':'in','value':['eu']}, 'not satisfied'), ({'field':'jobs.longest_job_seconds','operator':'gte','value':1000}, 'not satisfied')]:
        assert m.condition_result(condition, h) == expected
    del h['jobs']['longest_job_seconds']
    assert next(x for x in m.fit(h, recipe) if x['field'] == 'jobs.runner')['line'].endswith('; unknown')


def question_checks(m, work):
    h = json.loads((FIXTURES / 'handover/valid.json').read_text())
    assert [x['id'] for x in m.questions(h)] == ['cloud','care']
    del h['jobs']
    assert [x['id'] for x in m.questions(h)] == ['cloud','care','long_work']
    place = json.loads((FIXTURES / 'place-record/choice.json').read_text())
    assert [x['id'] for x in m.questions(h, place)] == ['long_work']
    for duration in (None, 'missing'):
        incomplete = json.loads((FIXTURES / 'handover/valid.json').read_text())
        if duration is None:
            incomplete['jobs']['longest_job_seconds'] = None
        else:
            del incomplete['jobs']['longest_job_seconds']
        path = work / 'incomplete.json'; path.write_text(json.dumps(incomplete))
        assert 'long_work' in [q['id'] for q in m.questions(m.handover(path, True))]
    assert m.questions(h, place, {'long_work':False}) == []
    assert all('residency' not in q['id'] for q in m.questions(h))


def suggestion_checks(m, work):
    trade = json.loads((EXPECTED / 'trade-offs.json').read_text())
    for path in sorted((ROOT / '.agents/tests/replays/host-choice').glob('*.json')):
        case = json.loads(path.read_text()); e = case['expected']
        result = m.suggest(case['handover'], e['answers'], case['place'])
        assert result['host'] == e['host'], path.name
        assert result['wish'] == e['wish'], path.name
        assert result['proof'] == 'not yet proven' and not result['proven']
        key = 'wish' if e['wish'] else ('azure-required' if e['answers']['cloud'] == 'azure' else e['host'])
        assert result['trade_off'] == trade[key], path.name
        if case['name'] == 'uk-accepted':
            assert 'This host has no UK location; your data would be in Germany or Finland.' in result['lines']
            assert result['alternatives'] == [{'host':'azure','proof':'not yet proven'}]
        if case['name'] == 'managed-long':
            assert result['alternatives'] == [{'host':'coolify-hetzner','proof':'not yet proven'}]
        if case['name'] == 'existing-place':
            assert result['lines'][0] == 'Suggested first because this organisation already has a recorded place.'
        if case['name'] == 'not-sure':
            assert any('Ask whoever looks after' in x for x in result['lines'])
    place = json.loads((FIXTURES / 'place-record/valid.json').read_text())
    place['place']['provider'] = 'Unlisted provider'
    h = json.loads((FIXTURES / 'handover/valid.json').read_text())
    result = m.suggest(h, {'cloud':'none','care':'managed'}, place)
    assert result['host'] == 'existing' and result['proof'] == 'not yet proven'
    assert all(row['status'] == 'unknown' for row in m.fit(h, None))
    # Known duration wins over a contradictory answer.
    h = json.loads((FIXTURES / 'handover/valid.json').read_text())
    assert m.suggest(h, {'cloud':'none','care':'managed','long_work':False})['host'] == 'azure'


def recipe_checks(m, work):
    assert m.menu() == []
    assert {p.name for p in m.RECIPES.iterdir()} == set(m.HOSTS)
    assert m.check_recipes() == {'checked':True}
    recipes = work / 'recipes'
    if recipes.exists():shutil.rmtree(recipes)
    shutil.copytree(m.RECIPES, recipes)
    target = recipes / 'azure'
    (target / 'PROVEN.md').write_text('Synthetic recorded run for menu presence testing only.\n')
    assert m.menu(recipes) == ['azure']
    (target / 'PROVEN.md').unlink()
    original = (target / 'recipe.md').read_text()
    (target / 'recipe.md').write_text(original + '\n## Jobs\n\nCapabilities: `jobs.runner`\n')
    try:m.check_recipes(recipes)
    except ValueError as exc:assert 'section has no capability' in str(exc)
    else:raise AssertionError('section without capability passed')
    (target / 'recipe.md').write_text(original)
    (target / 'capabilities.json').write_text('{"jobs.runner":{"worker":{"status":"met"}}}\n')
    try:m.check_recipes(recipes)
    except ValueError as exc:assert 'capability entry has no unique recipe section' in str(exc)
    else:raise AssertionError('capability without section passed')


def record_checks(m, work):
    case = json.loads((ROOT / '.agents/tests/replays/host-choice/uk-accepted.json').read_text())
    h, a = case['handover'], case['expected']['answers']
    host = 'coolify-hetzner'; path = work / 'place-record.json'
    assert len(m.warnings(h, host, None)) == 1
    accepted = [{'field':'residency','status':'accepted','date':'2026-11-04','words':case['expected']['acceptance']}]
    m.record(h, a, None, host, accepted, path)
    record = m.read('place-record', path)
    assert record['choice']['accepted_shortfalls'] == accepted
    assert not record['choice']['proven']
    assert m.warnings(h, host, record) == []
    m.record(h, a, record, host, [], path)
    assert m.read('place-record', path)['choice']['accepted_shortfalls'] == accepted
    # Existing details survive; no network or state fields are invented for a draft.
    existing = json.loads((FIXTURES / 'place-record/valid.json').read_text())
    m.record(h, a, existing, host, accepted, path)
    result = m.read('place-record', path)
    assert all(result[k] == v for k,v in existing.items())
    assert set(record) == {'schema_version','choice'}
    for wish in ('aws','google-cloud'):
        m.record(h, dict(a,cloud=wish), record, host, [], path)
        assert m.read('place-record',path)['choice']['wish'] == wish
    before = path.read_bytes()
    for words in ('password=synthetic-secret-marker','See https://example.invalid/?synthetic-secret-marker'):
        bad = copy.deepcopy(accepted);bad[0]['words']=words
        try:m.record(h,a,record,host,bad,path)
        except ValueError as exc:assert 'choice.accepted_shortfalls[0].words:' in str(exc) and words not in str(exc)
        else:raise AssertionError('secret or reference text accepted')
        assert path.read_bytes() == before


def schema_checks(m, work):
    for case in json.loads((FIXTURES / 'invalid-cases.json').read_text()):
        if case['kind'] != 'capabilities' and 'invalid-choice-' not in case['file']:
            continue
        try:m.read(case['kind'], FIXTURES / case['file'])
        except ValueError as exc:assert case['field'] + ':' in str(exc) and 'synthetic-secret-marker' not in str(exc)
        else:raise AssertionError('invalid new contract accepted: ' + case['file'])


def replay_checks(m, work):
    spec=importlib.util.spec_from_file_location('replay',ROOT/'.agents/tools/replay-host-choice.py')
    replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
    for path in replay.CASES.glob('*.json'):replay.load_case(path)
    path=work/'bad.json'
    case=json.loads((replay.CASES/'azure.json').read_text());case['name']='bad';case['turns']=[]
    path.write_text(json.dumps(case))
    try:replay.load_case(path)
    except ValueError:pass
    else:raise AssertionError('empty replay turns passed')


CHECKS = {'fit':fit_checks,'questions':question_checks,'suggestions':suggestion_checks,'recipes':recipe_checks,'records':record_checks,'schemas':schema_checks,'replays':replay_checks}


def mutations(work):
    # Each changed copy runs the same outcome assertions used above. A surviving
    # mutation is a failed check, not evidence of protection.
    mutations = [
        ('residency line', 'fit', 'scripts/host_fit.py', "rows.append({'field': field, 'status': status, 'line': line})", "\n        if field != 'residency': rows.append({'field': field, 'status': status, 'line': line})"),
        ('unknown needs visible', 'fit', 'scripts/host_fit.py', "rows.append({'field': field, 'status': status, 'line': line})", "\n        if status != 'unknown': rows.append({'field': field, 'status': status, 'line': line})"),
        ('condition evaluation', 'fit', 'scripts/host_fit.py', "return 'satisfied' if result else 'not satisfied'", "return 'satisfied'"),
        ('record values withheld', 'fit', 'scripts/host_fit.py', "line = rv.field_path(path) + ': ' + ('met if' if status == 'met-if' else status)", "line = rv.field_path(path) + ': ' + str(value) + ' ' + status"),
        ('known duration skip', 'questions', 'scripts/host_fit.py', "needed = [q for q in needed if q != 'long_work']", 'needed = needed'),
        ('suggestion routing', 'suggestions', 'scripts/host_fit.py', "host = 'azure' if cloud == 'azure'", "host = 'vercel-postgres' if cloud == 'azure'"),
        ('wish recorded', 'suggestions', 'scripts/host_fit.py', "wish = cloud if cloud in ('aws', 'google-cloud') else None", 'wish = None'),
        ('existing place priority', 'suggestions', 'scripts/host_fit.py', 'previous = existing_host(place)', 'previous = None'),
        ('menu proof gate', 'recipes', 'scripts/host_fit.py', " and (p / 'PROVEN.md').is_file()", ''),
        ('section to capability', 'recipes', 'scripts/host_fit.py', "raise ValueError('recipe section has no capability entry')", 'pass'),
        ('capability to section', 'recipes', 'scripts/host_fit.py', "raise ValueError('capability entry has no unique recipe section')", 'pass'),
        ('acceptance warning suppression', 'records', 'scripts/host_fit.py', " and row['field'] not in accepted", ''),
        ('acceptance retention', 'records', 'scripts/host_fit.py', "accepted = list(old.get('accepted_shortfalls', [])) if old.get('host') == host else []", 'accepted = []'),
        ('record validation', 'schemas', 'resources/record_validation.py', 'for error in validator_type(schema, format_checker=formats).iter_errors(value):', 'for error in []:'),
        ('secret text scan', 'records', 'resources/record_validation.py', 'for parts in secret_fields(value):', 'for parts in []:'),
    ]
    for index,(label,check,file,before,after) in enumerate(mutations):
        folder=work/str(index);shutil.copytree(SKILL,folder)
        path=folder/file;source=path.read_text();assert before in source,label
        path.write_text(source.replace(before,after))
        scratch=work/('test-'+str(index));scratch.mkdir()
        try:CHECKS[check](load(folder),scratch)
        except (AssertionError,ValueError):print('Mutation caught: '+label)
        else:raise AssertionError('mutation survived: '+label)
    # Remove individual schema protections, leaving the rest of validation intact.
    schema_mutations = [
        ('capability status', 'capabilities.schema.json', lambda s: s['$defs']['entry']['oneOf'][0]['properties']['status'].pop('const')),
        ('capability field', 'capabilities.schema.json', lambda s: s.pop('additionalProperties')),
        ('condition operator', 'capabilities.schema.json', lambda s: s['$defs']['entry']['oneOf'][1]['properties']['condition']['properties']['operator'].pop('enum')),
        ('numeric condition', 'capabilities.schema.json', lambda s: s['$defs']['entry']['oneOf'][1]['properties']['condition'].pop('allOf')),
        ('check reference', 'capabilities.schema.json', lambda s: s['$defs']['entry']['oneOf'][0]['properties']['check'].pop('pattern')),
        ('condition required', 'capabilities.schema.json', lambda s: s['$defs']['entry']['oneOf'][1]['required'].remove('condition')),
        ('reason required', 'capabilities.schema.json', lambda s: s['$defs']['entry']['oneOf'][2]['required'].remove('reason')),
        ('acceptance date', 'place-record.schema.json', lambda s: s['properties']['choice']['properties']['accepted_shortfalls']['items']['properties']['date'].pop('format')),
        ('acceptance words', 'place-record.schema.json', lambda s: s['properties']['choice']['properties']['accepted_shortfalls']['items']['required'].remove('words')),
        ('accepted status', 'place-record.schema.json', lambda s: s['properties']['choice']['properties']['accepted_shortfalls']['items']['properties']['status'].pop('const')),
        ('acceptance reference protection', 'place-record.schema.json', lambda s: s['properties']['choice']['properties']['accepted_shortfalls']['items']['properties']['words'].pop('pattern')),
        ('proof recorded', 'place-record.schema.json', lambda s: s['properties']['choice']['required'].remove('proven')),
    ]
    for index,(label,file,change) in enumerate(schema_mutations):
        folder=work/('schema-'+str(index));shutil.copytree(SKILL,folder)
        path=folder/'resources/contracts'/file;schema=json.loads(path.read_text());change(schema);path.write_text(json.dumps(schema))
        try:schema_checks(load(folder),work)
        except AssertionError:print('Mutation caught: '+label)
        else:raise AssertionError('mutation survived: '+label)
    # The dry-mode case validator itself is checked with its required turns removed.
    source=(ROOT/'.agents/tools/replay-host-choice.py').read_text()
    target=work/'replay.py'
    target.write_text(source.replace("require(isinstance(case['turns'], list) and case['turns'] and all(isinstance(t, str) and t.strip() for t in case['turns']), 'case needs scripted person turns')", 'pass'))
    spec=importlib.util.spec_from_file_location('mutant_replay',target);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    case=json.loads((ROOT/'.agents/tests/replays/host-choice/azure.json').read_text());case['name']='bad';case['turns']=[]
    bad=work/'bad.json';bad.write_text(json.dumps(case))
    assert module.load_case(bad)['turns']==[]
    print('Mutation caught: replay turn protection (empty turns accepted only after removal)')


def main():
    m=load()
    if m.rv.dependencies() is None:
        print('could-not-run: schema packages are missing');return 2
    with tempfile.TemporaryDirectory(prefix='host-fit-checks-') as folder:
        work=Path(folder)
        for name,check in CHECKS.items():
            scratch=work/name;scratch.mkdir();check(m,scratch);print('Passed: '+name)
        mutations(work)
    return 0


if __name__=='__main__':
    sys.exit(main())
