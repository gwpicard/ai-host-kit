"""Outcome checks for local host choice, with mutations in disposable copies."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import shlex
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
    typed = json.loads((FIXTURES / 'handover/valid.json').read_text())
    required_needs = {
        'sign_in.staff_provider', 'sign_in.public_origin_env',
        'sign_in.configuration.AUTH_BASE_URL', 'sign_in.secret_files[0].name',
        'sign_in.secret_files[0].required_when', 'sign_in.secret_files[0].description',
        'sign_in.host_setup.owner', 'sign_in.host_setup.request',
        'sign_in.host_setup.microsoft', 'sign_in.host_setup.google',
        'sign_in.host_setup.callbacks.microsoft', 'sign_in.host_setup.callbacks.google',
        'sign_in.email_link.verification_path', 'sign_in.email_link.requires',
        'postgres.roles.auth', 'postgres.sign_in.schema', 'postgres.sign_in.tables[0]',
        'postgres.sign_in.owner', 'postgres.sign_in.migration',
        'postgres.sign_in.runtime_role', 'postgres.sign_in.permissions',
    }
    for host in m.HOSTS:
        rows = {row['line'].split(': ', 1)[0]: row for row in m.fit(typed, m.RECIPES / host)}
        assert required_needs <= rows.keys(), required_needs - rows.keys()
        assert all(rows[field]['status'] == 'unknown' for field in required_needs)
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
    (target / 'PROVEN.md').write_bytes((EXPECTED / 'proof/valid.md').read_bytes())
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
    # Exercise the documented shared paths, including a Claude-only copy.
    for route, location in (('Project skills', '.agents/skills'),
                            ('Claude-only shared skills', '.claude/skills')):
        project = work / route
        skill = project / location / 'host-fit'
        shutil.copytree(SKILL, skill)
        (project / 'hosting').mkdir()
        shutil.copy2(FIXTURES / 'handover/valid.json', project / 'hosting/handover.json')
        prefix = replay.skill_command(skill / 'SKILL.md', route)
        result = run(shlex.split(prefix) + ['questions', '--handover', 'hosting/handover.json'], cwd=project)
        assert [q['id'] for q in json.loads(result.stdout)] == ['cloud', 'care']

    # Run the real dry entry point in a disposable source copy. Change each
    # side independently, then restore it and prove the dry check passes again.
    tree = work / 'replay-source'
    for relative in ('.agents/skills/host-fit', '.agents/skills/setup-hosting',
                     '.agents/tests/replays/host-choice'):
        shutil.copytree(ROOT / relative, tree / relative)
    script = tree / '.agents/tools/replay-host-choice.py'
    script.parent.mkdir(parents=True)
    shutil.copy2(ROOT / '.agents/tools/replay-host-choice.py', script)
    skill = tree / '.agents/skills/host-fit/SKILL.md'
    command = [sys.executable, script, '--dry', '--case', 'azure']
    run(command)
    for label, path, before, after in (
        ('skill command', skill, 'python3 .agents/skills/host-fit/scripts/host_fit.py',
         'python3 .agents/skills/host-fit/scripts/renamed.py'),
        ('allow rule', script, "SCRIPT_ALLOW_RULE = 'Bash(python3 .agents/skills/host-fit/scripts/host_fit.py *)'",
         "SCRIPT_ALLOW_RULE = 'Bash(python3 .agents/skills/host-fit/scripts/renamed.py *)'"),
        ('broad allow rule', script, "SCRIPT_ALLOW_RULE = 'Bash(python3 .agents/skills/host-fit/scripts/host_fit.py *)'",
         "SCRIPT_ALLOW_RULE = 'Bash(python3 *)'"),
    ):
        original = path.read_text()
        assert before in original
        path.write_text(original.replace(before, after))
        try:
            result = run(command, expected=1)
            assert 'skill command and harness allow rule differ' in result.stdout, result.stdout
            print(label + ': dry mode refused drift')
        finally:
            path.write_text(original)
        run(command)
    print('Replay command mutations restored; dry mode passed without a model.')


def future_need_checks(m, work):
    h = m.handover(EXPECTED / 'future-needs.json')
    expected = [
        'tool.runtime_requirements.gpu: unknown',
        'accelerator: unknown',
        'encryption_policy: unknown',
        'future_resources: unknown',
        'future_resources[0]: unknown',
        'future_resources[1].dedicated_gpu: unknown',
    ]
    for host in m.HOSTS:
        lines = [row['line'] for row in m.fit(h, m.RECIPES / host)]
        assert [line for line in lines if line.startswith(('tool.', 'accelerator:', 'encryption_policy:', 'future_resources'))] == expected
    h['future_resources'] = [False, {}, [], [None, {'gpu': True}], 'synthetic-secret-marker']
    m.checked('handover', h)
    lines = [row['line'] for row in m.fit(h, None) if row['line'].startswith('future_resources')]
    assert lines == [f'future_resources{suffix}: unknown' for suffix in ('', '[0]', '[1]', '[2]', '[3]', '[3][0]', '[3][1].gpu', '[4]')]
    assert 'synthetic-secret-marker' not in json.dumps(m.fit(h, None))


def path_checks(m, work):
    h = json.loads((FIXTURES / 'handover/valid.json').read_text())
    h['limits.memory_mb'] = 99999
    # Literal dots are refused by the published schema. The path renderer still
    # distinguishes them when used internally with unvalidated structures.
    try:
        m.checked('handover', h)
    except ValueError as exc:
        assert 'limits.memory_mb: has the wrong form' in str(exc)
    else:
        raise AssertionError('unsafe extension name accepted')
    recipe = work / 'paths'; recipe.mkdir(exist_ok=True)
    (recipe / 'capabilities.json').write_text(json.dumps({'limits.memory_mb': {'*': {'status': 'met'}}}))
    rows = m.fit(h, recipe)
    assert next(row for row in rows if row['line'] == 'limits.memory_mb: met')['field'] == 'limits.memory_mb'
    dotted = next(row for row in rows if row['line'].startswith('["limits.memory_mb"]:'))
    assert dotted == {'field': 'limits\\.memory_mb', 'status': 'unknown', 'line': '["limits.memory_mb"]: unknown'}
    assert len({row['field'] for row in rows if 'memory_mb' in row['field']}) == 2


def proof_checks(m, work):
    recipes = work / 'proof-recipes'
    target = recipes / 'azure'; target.mkdir(parents=True, exist_ok=True)
    proof = target / 'PROVEN.md'
    for case in json.loads((EXPECTED / 'proof/cases.json').read_text()):
        proof.write_bytes((EXPECTED / 'proof' / case['file']).read_bytes())
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            result = m.menu(recipes, explain=True)
        assert result == case['menu'], case['file']
        assert all(reason in output.getvalue() for reason in case['reasons']), case['file']
        assert 'synthetic-secret-marker' not in output.getvalue()
    valid = (EXPECTED / 'proof/valid.md').read_text()
    # Every required outcome independently gates the menu, including duplicates.
    for line in valid.splitlines()[1:]:
        for replacement in ('', line.replace('passed', 'failed'), line.replace('passed - Synthetic outcome checked.', 'No real run yet'), line.split(' - ')[0] + ' - ', line + '\n' + line):
            proof.write_text(valid.replace(line, replacement))
            assert m.menu(recipes) == [], line
            assert line.split(':')[0] + ': needs one passed outcome with details' in m.proof_errors(target)
    proof.write_text(valid + valid.splitlines()[0] + '\n')
    assert m.menu(recipes) == []
    proof.unlink()
    assert m.menu(recipes) == []


def marker_menu(m, work, text):
    recipes = work / 'marker-recipes'
    target = recipes / 'azure'; target.mkdir(parents=True, exist_ok=True)
    (target / 'PROVEN.md').write_text(text)
    output = io.StringIO()
    with contextlib.redirect_stderr(output):
        result = m.menu(recipes, explain=True)
    return result, output.getvalue()


def required_marker_checks(m, work):
    valid = (EXPECTED / 'proof/valid.md').read_text()
    for line in valid.splitlines()[1:]:
        area = line.split(':')[0]
        for details in ('No real run yet', 'synthetic-secret-marker No real run yet; checks pending'):
            result, reason = marker_menu(m, work, valid.replace(line, area + ': passed - ' + details))
            assert result == [], area
            assert reason == 'azure: not yet proven; ' + area + ': no real run recorded\n', (area, reason)


def later_marker_note_checks(m, work):
    valid = (EXPECTED / 'proof/valid.md').read_text()
    assert marker_menu(m, work, valid + '\n## Later section\n\nNo real run yet\n') == (['azure'], '')


def later_marker_outcome_checks(m, work):
    valid = (EXPECTED / 'proof/valid.md').read_text()
    assert marker_menu(m, work, valid + '\n## Later section\n\nExtra checks: passed - No real run yet\n') == (['azure'], '')


def number_checks(m, work):
    h = json.loads((FIXTURES / 'handover/valid.json').read_text())
    for duration, host in ((900.0, 'azure'), (300.0, 'vercel-postgres'), (301, 'azure')):
        h['jobs']['longest_job_seconds'] = duration
        path = work / 'duration.json'; path.write_text(json.dumps(h))
        valid = m.handover(path)
        assert [q['id'] for q in m.questions(valid)] == ['cloud', 'care'], duration
        for answer in ({}, {'long_work': False}, {'long_work': True}):
            assert m.suggest(valid, dict(answer, cloud='none', care='managed'))['host'] == host, duration


def place_priority_checks(m, work):
    h = json.loads((FIXTURES / 'handover/valid.json').read_text())
    place = json.loads((FIXTURES / 'place-record/valid.json').read_text())
    place['place']['provider'] = 'Hetzner'
    output = work / 'place.json'
    # This conflict must work through the normal writer as well as direct input.
    m.record(h, {'cloud': 'none', 'care': 'managed'}, place, 'vercel-postgres', [], output)
    saved = m.read('place-record', output)
    result = m.suggest(h, {}, saved)
    assert result['host'] == 'coolify-hetzner'
    assert 'Saved host preference: vercel-postgres.' in result['lines']
    assert result['lines'][0] == 'Suggested first because this organisation already has a recorded place.'
    assert all(saved[k] == v for k, v in place.items())
    assert m.suggest(h, {}, {'schema_version': '1.0', 'choice': saved['choice']})['host'] == 'vercel-postgres'


def membership_checks(m, work):
    h = json.loads((FIXTURES / 'handover/valid.json').read_text())
    recipe = work / 'membership'; recipe.mkdir(exist_ok=True)
    for field, expected, outcome in (
        ('limits.outbound_internet', [1], 'not satisfied'),
        ('limits.outbound_internet', [True], 'satisfied'),
        ('limits.memory_mb', [True], 'not satisfied'),
        ('limits.memory_mb', [1.0], 'satisfied'),
    ):
        h['limits']['memory_mb'] = 1
        m.checked('handover', h)
        condition = {'field': field, 'operator': 'in', 'value': expected}
        (recipe / 'capabilities.json').write_text(json.dumps({'jobs.runner': {'*': {'status': 'met-if', 'condition': condition}}}))
        line = next(row['line'] for row in m.fit(h, recipe) if row['field'] == 'jobs.runner')
        assert line.endswith('; ' + outcome), (field, expected, line)
    for actual, expected, outcome in ((True, 1, 'not satisfied'), (1, True, 'not satisfied'), (1.0, 1, 'satisfied')):
        assert m.condition_result({'field': 'value', 'operator': 'eq', 'value': expected}, {'value': actual}) == outcome


def wildcard_checks(m, work):
    h = json.loads((FIXTURES / 'handover/valid.json').read_text())
    recipe = work / 'wildcard'; recipe.mkdir(exist_ok=True)
    condition = {'field': 'files.buckets.*.private', 'operator': 'eq', 'value': True}
    (recipe / 'capabilities.json').write_text(json.dumps({'files.buckets.*.link_minutes': {'*': {'status': 'met-if', 'condition': condition}}}))
    line = next(row['line'] for row in m.fit(h, recipe) if row['field'] == 'files.buckets.*.link_minutes')
    assert line == 'files.buckets[0].link_minutes: met if - files.buckets.*.private eq true; satisfied'
    for items, outcome in (([{'private': True}, {'private': True}], 'satisfied'),
                           ([{'private': True}, {'private': False}], 'not satisfied'),
                           ([{'private': False}, {'private': True}], 'not satisfied'),
                           ([], 'unknown'), ([{'private': True}, {}], 'unknown'),
                           ([{'private': True}, None], 'unknown'),
                           ([{}, {'private': False}], 'not satisfied')):
        h['files']['buckets'] = items
        assert m.condition_result(condition, h) == outcome, items


CHECKS = {'fit':fit_checks,'questions':question_checks,'suggestions':suggestion_checks,'recipes':recipe_checks,'records':record_checks,'schemas':schema_checks,'replays':replay_checks,
          'future needs':future_need_checks, 'literal paths':path_checks, 'proof records':proof_checks,
          'required outcome markers':required_marker_checks, 'later section marker note':later_marker_note_checks,
          'later section marker outcome':later_marker_outcome_checks,
          'JSON numbers':number_checks, 'place before preference':place_priority_checks,
          'typed membership':membership_checks, 'wildcards':wildcard_checks}


def mutations(work):
    # Each changed copy runs the same outcome assertions used above. A surviving
    # mutation is a failed check, not evidence of protection.
    mutations = [
        ('residency line', 'fit', 'scripts/host_fit.py', "rows.append({'field': field, 'status': status, 'line': line})", "\n        if field != 'residency': rows.append({'field': field, 'status': status, 'line': line})"),
        ('unknown needs visible', 'fit', 'scripts/host_fit.py', "rows.append({'field': field, 'status': status, 'line': line})", "\n        if status != 'unknown': rows.append({'field': field, 'status': status, 'line': line})"),
        ('condition evaluation', 'fit', 'scripts/host_fit.py', "return 'satisfied' if result else 'not satisfied'", "return 'satisfied'"),
        ('record values withheld', 'fit', 'scripts/host_fit.py', "line = need_path(path) + ': ' + ('met if' if status == 'met-if' else status)", "line = need_path(path) + ': ' + str(value) + ' ' + status"),
        ('known duration skip', 'questions', 'scripts/host_fit.py', "needed = [q for q in needed if q != 'long_work']", 'needed = needed'),
        ('suggestion routing', 'suggestions', 'scripts/host_fit.py', "host = 'azure' if cloud == 'azure'", "host = 'vercel-postgres' if cloud == 'azure'"),
        ('wish recorded', 'suggestions', 'scripts/host_fit.py', "wish = cloud if cloud in ('aws', 'google-cloud') else None", 'wish = None'),
        ('existing place priority', 'suggestions', 'scripts/host_fit.py', 'previous = existing_host(place)', 'previous = None'),
        ('menu proof gate', 'recipes', 'scripts/host_fit.py', 'errors = proof_errors(recipe)', 'errors = []'),
        ('section to capability', 'recipes', 'scripts/host_fit.py', "raise ValueError('recipe section has no capability entry')", 'pass'),
        ('capability to section', 'recipes', 'scripts/host_fit.py', "raise ValueError('capability entry has no unique recipe section')", 'pass'),
        ('acceptance warning suppression', 'records', 'scripts/host_fit.py', " and row['field'] not in accepted", ''),
        ('acceptance retention', 'records', 'scripts/host_fit.py', "accepted = list(old.get('accepted_shortfalls', [])) if old.get('host') == host else []", 'accepted = []'),
        ('record validation', 'schemas', 'resources/record_validation.py', 'for error in validator_type(schema, format_checker=formats).iter_errors(value):', 'for error in []:'),
        ('secret text scan', 'records', 'resources/record_validation.py', 'for parts in secret_fields(value):', 'for parts in []:'),
        ('future null needs', 'future needs', 'scripts/host_fit.py', 'else:\n        yield path, value', 'elif value is not None:\n        yield path, value'),
        ('future empty objects', 'future needs', 'scripts/host_fit.py', 'isinstance(value, dict) and value:', 'isinstance(value, dict):'),
        ('mixed array traversal', 'future needs', 'scripts/host_fit.py', 'isinstance(value, list) and value:', 'isinstance(value, list) and value and isinstance(value[0], dict):'),
        ('mixed array container', 'future needs', 'scripts/host_fit.py', "if len({'number' if json_number(child) else type(child).__name__ for child in value}) > 1:", 'if False:'),
        ('unknown tool needs', 'future needs', 'scripts/host_fit.py', "if path in (('schema_version',)", "if path in (('tool',), ('schema_version',)"),
        ('literal dot distinction', 'literal paths', 'scripts/host_fit.py', "else p.replace('\\\\', '\\\\\\\\').replace('.', '\\\\.').replace('*', '\\\\*')", 'else p'),
        ('proof content required', 'proof records', 'scripts/host_fit.py', 'errors = proof_errors(recipe)', "errors = [] if (recipe / 'PROVEN.md').is_file() else ['missing']"),
        ('proof date and versions', 'proof records', 'scripts/host_fit.py', "errors.append('Real run: needs one valid date and named versions')", 'pass'),
        ('proof outcomes required', 'proof records', 'scripts/host_fit.py', "errors.append(area + ': needs one passed outcome with details')", 'pass'),
        ('required outcome marker veto', 'required outcome markers', 'scripts/host_fit.py', "if any('No real run yet' in line for line in outcomes):", 'if False:'),
        ('later marker note allowed', 'later section marker note', 'scripts/host_fit.py', "if any('No real run yet' in line for line in outcomes):", "if any('No real run yet' in line for line in lines):"),
        ('later marker outcome allowed', 'later section marker outcome', 'scripts/host_fit.py', "if any('No real run yet' in line for line in outcomes):", "if any('No real run yet' in line for line in lines):"),
        ('JSON numeric durations', 'JSON numbers', 'scripts/host_fit.py', 'return isinstance(value, (int, float)) and not isinstance(value, bool)', 'return isinstance(value, int) and not isinstance(value, bool)'),
        ('actual place before choice', 'place before preference', 'scripts/host_fit.py', "if 'place' not in place and 'choice' in place:", "if 'choice' in place:"),
        ('membership type distinction', 'typed membership', 'scripts/host_fit.py', 'any(json_equal(actual, item) for item in expected)', 'actual in expected'),
        ('wildcard resolution', 'wildcards', 'scripts/host_fit.py', 'return [item for child in value for item in lookup(child, rest)]', 'return [None]'),
        ('all wildcard items', 'wildcards', 'scripts/host_fit.py', 'for child in value for item in lookup(child, rest)', 'for child in value[:1] for item in lookup(child, rest)'),
    ]
    for index,(label,check,file,before,after) in enumerate(mutations):
        folder=work/str(index);shutil.copytree(SKILL,folder)
        path=folder/file;source=path.read_text();assert before in source,label
        path.write_text(source.replace(before,after))
        scratch=work/('test-'+str(index));scratch.mkdir()
        try:CHECKS[check](load(folder),scratch)
        except (AssertionError,ValueError):print('Mutation caught: '+label)
        else:raise AssertionError('mutation survived: '+label)
        finally:path.write_text(source)
        CHECKS[check](load(folder),scratch)
        print('Restored check passed: '+label)
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
