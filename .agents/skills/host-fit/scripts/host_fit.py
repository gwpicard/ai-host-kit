"""Local host choice. Reads declarations; never contacts a provider."""
import argparse
import contextlib
from datetime import date
import io
import json
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True

RESOURCES = Path(__file__).resolve().parents[1] / 'resources'
sys.path.insert(0, str(RESOURCES))
import record_validation as rv
rv.ROOT = RESOURCES
RECIPES = RESOURCES / 'recipes'
HOSTS = ('azure', 'coolify-hetzner', 'vercel-postgres')
CHOICES = HOSTS + ('existing',)
TRADE = {
    'existing': 'Keeps the organisation in its recorded place; this provider has no recipe, so its hosting capabilities remain unknown.',
    'azure-required': "Stays inside your company's Microsoft account and sign-in; someone with admin rights in your directory must approve the app once.",
    'azure': 'Runs long work without a server to keep; needs an Azure subscription; a Microsoft 365 firm already has the directory it would sign in with.',
    'coolify-hetzner': 'One server runs all your tools and long work; you approve its updates and its backups are yours to keep.',
    'vercel-postgres': 'No server to update, and previews and rollback are built in; background work must finish within the function time limit.',
}
QUESTIONS = {
    'cloud': 'Does your company or a client require this tool to run inside a cloud account you already use, such as Microsoft Azure, AWS or Google Cloud?',
    'care': "Would you rather have nothing to look after, or one rented server that can run several tools and that you look after with the kit's help?",
    'long_work': 'Will the tool do long work in the background, such as processing a batch of documents or a nightly sync that runs for more than a few minutes?',
}


def checked(kind, value):
    # Reuse exactly the contract reader, including secret and reference protections.
    with tempfile.TemporaryDirectory(prefix='host-fit-validate-') as folder:
        path = Path(folder) / 'record.json'
        path.write_text(json.dumps(value))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = rv.validate(kind, path)
    if status:
        raise ValueError(output.getvalue().strip())
    return value


def read(kind, path):
    return checked(kind, rv.read_json(path))


def handover(path, questions_only=False):
    value = rv.read_json(path)
    candidate = value
    # The provisional contract requires a duration when jobs is present. The
    # interview can fill that knowledge gap without declaring the record valid.
    if questions_only and isinstance(value, dict) and isinstance(value.get('jobs'), dict):
        if value['jobs'].get('longest_job_seconds') is None:
            candidate = dict(value)
            candidate['jobs'] = dict(value['jobs'], longest_job_seconds=1)
    checked('handover', candidate)
    return value


def need_values(value, path=()):
    if path in (('schema_version',), ('tool', 'name'), ('tool', 'owner'), ('tool', 'successor')):
        return
    if path == ('processes', 'worker') and value is None:
        return
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from need_values(child, path + (key,))
    elif isinstance(value, list) and value:
        if len({'number' if json_number(child) else type(child).__name__ for child in value}) > 1:
            yield path, value
        for index, child in enumerate(value):
            yield from need_values(child, path + (index,))
    else:
        yield path, value


def capability_path(path):
    return '.'.join('*' if isinstance(p, int) else p.replace('\\', '\\\\').replace('.', '\\.').replace('*', '\\*') for p in path)


def need_path(path):
    parts = []
    for part in path:
        if isinstance(part, int):
            parts.append(f'[{part}]')
        else:
            safe = rv.field_path((part,))
            parts.append('[' + json.dumps(safe) + ']' if '.' in safe or safe == '*' else ('.' if parts else '') + safe)
    return ''.join(parts)


def lookup(value, path):
    if not path:
        return [value]
    key, *rest = path
    if key == '*':
        if not isinstance(value, list) or not value:
            return [None]
        return [item for child in value for item in lookup(child, rest)]
    if not isinstance(value, dict) or key not in value:
        return [None]
    return lookup(value[key], rest)


def json_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def json_equal(actual, expected):
    if json_number(actual) and json_number(expected):
        return actual == expected
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(json_equal(a, e) for a, e in zip(actual, expected))
    return type(actual) is type(expected) and actual == expected


def condition_result(condition, h):
    results = [compare_condition(condition, actual) for actual in lookup(h, condition['field'].split('.'))]
    if 'not satisfied' in results:
        return 'not satisfied'
    return 'unknown' if 'unknown' in results else 'satisfied'


def compare_condition(condition, actual):
    if actual is None:
        return 'unknown'
    expected, op = condition['value'], condition['operator']
    if op == 'eq':
        result = json_equal(actual, expected)
    elif op == 'in':
        result = isinstance(expected, list) and any(json_equal(actual, item) for item in expected)
    elif isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(expected, (int, float)) and not isinstance(expected, bool):
        result = actual <= expected if op == 'lte' else actual >= expected
    else:
        return 'unknown'
    return 'satisfied' if result else 'not satisfied'


def fit(h, recipe):
    caps = read('capabilities', recipe / 'capabilities.json') if recipe is not None else {}
    rows = []
    for path, value in need_values(h):
        field = capability_path(path)
        selectors = caps.get(field, {})
        # Scalar arrays declared as a whole still apply to each scalar item.
        if isinstance(path[-1], int) and not isinstance(value, (dict, list)):
            selectors = caps.get(field, caps.get(capability_path(path[:-1]), {}))
        selector = str(value).lower() if isinstance(value, bool) else str(value)
        entry = selectors.get(selector, selectors.get('*', {}))
        status = entry.get('status', 'unknown')
        detail = ''
        if status == 'cannot':
            detail = entry['reason']
        elif status == 'met-if':
            c = entry['condition']
            detail = f"{c['field']} {c['operator']} {json.dumps(c['value'])}; {condition_result(c, h)}"
        line = need_path(path) + ': ' + ('met if' if status == 'met-if' else status)
        if detail:
            line += ' - ' + detail
        rows.append({'field': field, 'status': status, 'line': line})
    return rows


PROOF_AREAS = ('Provision', 'Deploy', 'Company sign-in', 'Files', 'Jobs',
               'Backup and restore', 'Previews', 'Rollback')


def proof_errors(recipe):
    # The maintained format is ../proof-format.md. Never echo proof contents.
    try:
        lines = (recipe / 'PROVEN.md').read_text().splitlines()
    except (OSError, UnicodeError):
        return ['PROVEN.md is missing or unreadable']
    runs = [line for line in lines if line.startswith('Real run:')]
    version = r'[A-Za-z][A-Za-z0-9_.-]*=v?[0-9][A-Za-z0-9_.+-]*'
    pattern = r'Real run: ([0-9]{4}-[0-9]{2}-[0-9]{2}); versions: ' + version + r'(?:, ' + version + r')*'
    match = re.fullmatch(pattern, runs[0]) if len(runs) == 1 else None
    errors = []
    try:
        if match is None:
            raise ValueError
        date.fromisoformat(match[1])
    except ValueError:
        errors.append('Real run: needs one valid date and named versions')
    for area in PROOF_AREAS:
        outcomes = [line for line in lines if line.startswith(area + ':')]
        if len(outcomes) != 1 or not re.fullmatch(re.escape(area) + r': passed - \S[^\r\n]*', outcomes[0]):
            errors.append(area + ': needs one passed outcome with details')
    return errors


def menu(recipes=RECIPES, explain=False):
    proven = []
    for recipe in sorted(recipes.iterdir()):
        if not recipe.is_dir():
            continue
        errors = proof_errors(recipe)
        if errors:
            if explain and (recipe / 'PROVEN.md').exists():
                print(recipe.name + ': not yet proven; ' + '; '.join(errors), file=sys.stderr)
        else:
            proven.append(recipe.name)
    return proven


def answers_for(place, answers):
    combined = dict((place or {}).get('choice', {}).get('answers', {}))
    combined.update(answers)
    schema = rv.read_json(RESOURCES / 'contracts/place-record.schema.json')['properties']['choice']['properties']['answers']
    validator, formats = rv.dependencies()
    if list(validator(schema, format_checker=formats).iter_errors(combined)):
        raise ValueError('answers: choose the supported cloud, care and long_work options')
    return combined


def questions(h, place=None, answers=None):
    a = answers_for(place, answers or {})
    needed = [q for q in QUESTIONS if q not in a]
    if json_number(h.get('jobs', {}).get('longest_job_seconds')):
        needed = [q for q in needed if q != 'long_work']
    return [{'id': q, 'question': QUESTIONS[q]} for q in needed]


def existing_host(place):
    if not place:
        return None
    if 'place' not in place and 'choice' in place:
        return place['choice']['host']
    provider = place.get('place', {}).get('provider', '').lower()
    return {'hetzner': 'coolify-hetzner', 'coolify': 'coolify-hetzner', 'vercel': 'vercel-postgres', 'azure': 'azure', 'microsoft azure': 'azure'}.get(provider, 'existing')


def suggest(h, a, place=None):
    a = answers_for(place, a)
    missing = questions(h, place, a)
    if missing:
        raise ValueError('answers: still needed: ' + ', '.join(q['id'] for q in missing))
    duration = h.get('jobs', {}).get('longest_job_seconds')
    long_work = duration > 300 if json_number(duration) else a['long_work']
    cloud = a['cloud']
    host = 'azure' if cloud == 'azure' else ('coolify-hetzner' if a['care'] == 'server' else ('azure' if long_work else 'vercel-postgres'))
    alternatives = ['coolify-hetzner'] if host == 'azure' and cloud != 'azure' else []
    previous = existing_host(place)
    lines = []
    if previous:
        if host != previous:
            alternatives.insert(0, host)
        host = previous
        lines.append('Suggested first because this organisation already has a recorded place.' if 'place' in place else 'Suggested first because this organisation already has a recorded host choice.')
        if 'place' in place and 'choice' in place:
            lines.append('Saved host preference: ' + place['choice']['host'] + '.')
    proven_hosts = menu()
    wish = cloud if cloud in ('aws', 'google-cloud') else None
    # A nearest proven option is preferred for an unsupported cloud wish.
    if wish and not previous and proven_hosts and host not in proven_hosts:
        host = next((x for x in [host] + alternatives + list(HOSTS) if x in proven_hosts), host)
    key = 'azure-required' if host == 'azure' and cloud == 'azure' else host
    trade_off = TRADE[key]
    if wish:
        lines.append(trade_off)
        trade_off = 'The kit will say plainly that nothing is guaranteed on an unproven host.'
    if cloud == 'not-sure':
        lines.append('Ask whoever looks after your Microsoft or Google accounts; until then I will treat it as no requirement.')
    if host == 'coolify-hetzner' and h['residency'] == 'uk':
        alternatives.append('azure')
        lines.append('This host has no UK location; your data would be in Germany or Finland.')
    return {'host': host, 'proven': host in proven_hosts, 'proof': 'proven' if host in proven_hosts else 'not yet proven', 'trade_off': trade_off, 'lines': lines, 'alternatives': [{'host': x, 'proof': 'proven' if x in proven_hosts else 'not yet proven'} for x in dict.fromkeys(alternatives) if x != host], 'wish': wish}


def warnings(h, host, place):
    old = (place or {}).get('choice', {})
    accepted = {a['field'] for a in old.get('accepted_shortfalls', [])} if old.get('host') == host else set()
    return [row['line'] for row in fit(h, RECIPES / host if host != 'existing' else None) if row['status'] == 'cannot' and row['field'] not in accepted]


def record(h, a, place, host, acceptances, output):
    suggestion = suggest(h, a, place)
    old = (place or {}).get('choice', {})
    accepted = list(old.get('accepted_shortfalls', [])) if old.get('host') == host else []
    for acceptance in acceptances:
        accepted = [x for x in accepted if x['field'] != acceptance['field']]
        accepted.append(acceptance)
    choice = {'host': host, 'proven': host in menu(), 'answers': answers_for(place, a), 'accepted_shortfalls': accepted}
    if suggestion['wish']:
        choice['wish'] = suggestion['wish']
    result = dict(place or {'schema_version': '1.0'}, choice=choice)
    checked('place-record', result)
    # Validation happens before any file is changed. Only the supplied local record changes.
    output.write_text(json.dumps(result, indent=2) + '\n')
    return {'recorded': True, 'host': host, 'proven': choice['proven']}


SECTION = {'image':'Going live','processes':'Going live','health':'Health',
           'config':'Secrets','postgres':'Going live','files':'Files','email':'Email',
           'jobs':'Jobs','sign_in':'Sign-in','ai':'Access','access':'Access',
           'residency':'Residency','data_risk':'Backup','recovery':'Restore',
           'limits':'Going live','previews':'Preview'}


def check_recipes(recipes=RECIPES):
    for recipe in sorted(recipes.iterdir()):
        if not recipe.is_dir():
            continue
        caps = read('capabilities', recipe / 'capabilities.json')
        text = (recipe / 'recipe.md').read_text()
        sections = re.split(r'^## ', text, flags=re.M)[1:]
        declared = []
        for section in sections:
            match = re.search(r'^Capabilities: (.+)$', section, re.M)
            if not match:
                raise ValueError('recipe section has no capability entry')
            fields = re.findall(r'`([^`]+)`', match[1])
            if not fields or any(f not in caps for f in fields):
                raise ValueError('recipe section has no capability entry')
            if any(SECTION.get(f.split('.')[0]) != section.splitlines()[0].strip() for f in fields):
                raise ValueError('capability belongs to a different recipe section')
            declared.extend(fields)
        if set(declared) != set(caps) or len(declared) != len(set(declared)):
            raise ValueError('capability entry has no unique recipe section')
    return {'checked': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['fit', 'questions', 'suggest', 'menu', 'check-recipes', 'warnings', 'record'])
    parser.add_argument('--handover', type=Path)
    parser.add_argument('--recipe', choices=CHOICES)
    parser.add_argument('--place', type=Path)
    parser.add_argument('--answers', type=Path)
    parser.add_argument('--acceptances', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'menu':
            result = menu(explain=True)
        elif args.action == 'check-recipes':
            result = check_recipes()
        else:
            if not args.handover:
                raise ValueError('handover: supply --handover')
            h = handover(args.handover, args.action in ('questions', 'suggest', 'record'))
            place = read('place-record', args.place) if args.place else None
            a = rv.read_json(args.answers) if args.answers else {}
            if not isinstance(a, dict):
                raise ValueError('answers: expected an object')
            if args.action in ('fit', 'warnings', 'record') and not args.recipe:
                raise ValueError('recipe: supply --recipe')
            if args.action == 'fit':
                print('\n'.join(row['line'] for row in fit(h, RECIPES / args.recipe if args.recipe != 'existing' else None)))
                return 0
            if args.action == 'questions':
                result = questions(h, place, a)
            elif args.action == 'suggest':
                result = suggest(h, a, place)
            elif args.action == 'warnings':
                result = warnings(h, args.recipe, place)
            elif args.action == 'record':
                if not args.output:
                    raise ValueError('output: supply a local place record path')
                if args.output.exists() and (not args.place or args.output.resolve() != args.place.resolve()):
                    raise ValueError('output: read the existing record with --place before updating it')
                accepted = rv.read_json(args.acceptances) if args.acceptances else []
                if not isinstance(accepted, list):
                    raise ValueError('accepted_shortfalls: expected an array')
                # Validate before inspecting arbitrary acceptance fields.
                checked('place-record', {'schema_version':'1.0', 'choice':{'host':args.recipe, 'proven':False, 'answers':a, 'accepted_shortfalls':accepted}})
                result = record(h, a, place, args.recipe, accepted, args.output)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        # OSError can include user-controlled paths, so withhold its details.
        print(str(exc) if isinstance(exc, ValueError) else 'file: could not read or write the local file', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
