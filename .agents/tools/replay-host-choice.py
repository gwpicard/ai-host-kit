#!/usr/bin/env python3
"""Build local host-choice cases; run a model only with the explicit --run flag."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / '.agents/tests/replays/host-choice'
# Keep this independent of the skill text so dry mode detects drift on either side.
SCRIPT_ALLOW_RULE = 'Bash(python3 .agents/skills/host-fit/scripts/host_fit.py *)'
PLACE = 'hosting/place-record.json'
ANSWERS = 'hosting/host-fit-answers.tmp.json'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def skill_command(skill, route='Project skills'):
    rows = re.findall(r'^\| ' + re.escape(route) + r' \| `([^`]+)` \|$',
                      skill.read_text(), re.MULTILINE)
    require(len(rows) == 1, 'skill needs one command prefix for ' + route)
    return rows[0]


def check_command_rule(prefix):
    # Claude Code's documented trailing " *" matches the literal prefix and
    # its arguments. This checks that narrow form, not the full permission engine.
    # https://code.claude.com/docs/en/permissions#wildcard-patterns
    require(re.fullmatch(r'python3 [a-zA-Z0-9_./-]+', prefix) is not None,
            'replay needs a literal project-relative script command')
    require(not shlex.split(prefix)[1].startswith('/'), 'replay script path must be relative')
    require(SCRIPT_ALLOW_RULE == 'Bash(' + prefix + ' *)',
            'skill command and harness allow rule differ')


def check_place_location(project):
    for name in ('setup-hosting', 'host-fit'):
        text = (project / '.agents/skills' / name / 'SKILL.md').read_text()
        paths = re.findall(r'`([^`]*place-record\.json)`', text)
        require(bool(paths) and set(paths) == {PLACE},
                name + ': draft place record location differs from harness')
    source = project / '.agents/skills/host-fit/scripts/host_fit.py'
    defaults = {}
    for node in ast.walk(ast.parse(source.read_text())):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'add_argument' and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in ('--place', '--output')):
            defaults[node.args[0].value] = next(
                (ast.literal_eval(k.value) for k in node.keywords if k.arg == 'default'), None)
    require(defaults == {'--place': PLACE, '--output': PLACE},
            'script defaults and harness draft place record location differ')


def checked_command(prefix, action, *args):
    check_command_rule(prefix)
    command = prefix + ' ' + shlex.join([action, *args])
    literal = SCRIPT_ALLOW_RULE[len('Bash('):-len(' *)')]
    require(command.startswith(literal + ' '), 'script command does not match allow rule')
    return shlex.split(command)


def load_case(path):
    case = json.loads(path.read_text())
    require(set(case) == {'name', 'handover', 'place', 'turns', 'expected'}, 'case fields differ')
    require(case['name'] == path.stem, 'case name differs from file')
    require(isinstance(case['turns'], list) and case['turns'] and all(isinstance(t, str) and t.strip() for t in case['turns']), 'case needs scripted person turns')
    expected = case['expected']
    require(set(expected) == {'host', 'answers', 'wish', 'questions', 'warnings', 'acceptance', 'outcomes'}, 'expected fields differ')
    require(expected['host'] in ('azure', 'coolify-hetzner', 'vercel-postgres'), 'expected host is unsupported')
    require(expected['wish'] in (None, 'aws', 'google-cloud'), 'invalid wish')
    require(isinstance(expected['warnings'], int) and expected['warnings'] >= 0, 'invalid warning count')
    require(isinstance(expected['outcomes'], list) and expected['outcomes'] and all(isinstance(x, str) and x.strip() for x in expected['outcomes']), 'case needs transcript and file outcomes')
    require(isinstance(expected['questions'], list) and len(set(expected['questions'])) == len(expected['questions']) and set(expected['questions']) <= {'cloud','care','long_work'}, 'invalid question list')
    require(expected['acceptance'] is None or isinstance(expected['acceptance'], str), 'invalid acceptance')
    return case


def build(case, folder):
    folder.mkdir()
    skills = folder / '.agents/skills'
    skills.mkdir(parents=True)
    for name in ('setup-hosting', 'host-fit'):
        shutil.copytree(ROOT / '.agents/skills' / name, skills / name, ignore=shutil.ignore_patterns('__pycache__'))
    (folder / 'hosting').mkdir()
    (folder / 'hosting/handover.json').write_text(json.dumps(case['handover'], indent=2) + '\n')
    if case['place']:
        (folder / PLACE).write_text(json.dumps(case['place'], indent=2) + '\n')
    (folder / 'AGENTS.md').write_text('This is a local replay project. Follow .agents/skills/setup-hosting/SKILL.md. Read only the supplied handover. Never contact hosts, provider APIs or external repositories. Do not run another model. Write only local choice files. Do not invent a person\'s answers or acceptance.\n')
    (folder / 'expected.json').write_text(json.dumps(case['expected'], indent=2) + '\n')
    (folder / 'person-turns.json').write_text(json.dumps(case['turns'], indent=2) + '\n')
    # The model must not read the expected result or future person turns.
    (folder / 'AGENTS.md').write_text((folder / 'AGENTS.md').read_text() + 'Do not read expected.json or person-turns.json. They are maintainer evidence, not project inputs.\n')
    subprocess.run(['git', 'init', '-q', str(folder)], check=True)
    return folder


def dry_check(case, project):
    check_place_location(project)
    prefix = skill_command(project / '.agents/skills/host-fit/SKILL.md')
    check_command_rule(prefix)
    # Execute exactly the documented command from the throwaway project root.
    def call(action, *args):
        result = subprocess.run(checked_command(prefix, action, *args), cwd=project, text=True, capture_output=True)
        require(result.returncode == 0, 'assembled project check failed: ' + result.stdout + result.stderr)
        return result.stdout
    h = ['--handover', 'hosting/handover.json']
    # Exercise the default input path, including existing records.
    questions = json.loads(call('questions', *h))
    require([q['id'] for q in questions] == case['expected']['questions'], 'question expectation differs')
    (project / ANSWERS).write_text(json.dumps(case['expected']['answers']))
    result = json.loads(call('suggest', *h, '--answers', ANSWERS))
    require(result['host'] == case['expected']['host'] and result['wish'] == case['expected']['wish'], 'suggestion expectation differs')
    require(result['proof'] == 'not yet proven', 'stub became proven')
    require(json.loads(call('menu')) == [], 'stub reached the menu')
    call('check-recipes')
    for host in ('azure', 'coolify-hetzner', 'vercel-postgres'):
        call('fit', *h, '--recipe', host)
    pending = json.loads(call('warnings', *h, '--recipe', case['expected']['host']))
    require(len(pending) == case['expected']['warnings'], 'warning expectation differs')
    record = project / PLACE
    original = record.read_bytes() if record.exists() else None
    try:
        call('record', *h, '--answers', ANSWERS, '--recipe', case['expected']['host'])
        saved = json.loads(record.read_text())
        require(saved['choice']['host'] == case['expected']['host'], 'default record output differs')
        require(not (project / 'place-record.json').exists(), 'record written at project root')
        if case['place']:
            require(all(saved[k] == v for k, v in case['place'].items() if k != 'choice'),
                    'default record update changed infrastructure fields')
    finally:
        # Dry checks must not supply future answers to a subsequent model replay.
        if original is None:
            record.unlink(missing_ok=True)
        else:
            record.write_bytes(original)
    (project / ANSWERS).unlink()


def run_case(case, project, evidence):
    session = str(uuid.uuid4())
    transcript = evidence / 'transcript.jsonl'
    # Keep only CLI/runtime essentials; provider credentials are not needed.
    env = {k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG','SHELL','USER')}
    for index, turn in enumerate(case['turns']):
        args = ['claude', '-p', '--output-format', 'json', '--tools', 'Read,Write,Edit,Bash', '--permission-mode', 'acceptEdits', '--allowedTools', 'Read', 'Write', 'Edit', SCRIPT_ALLOW_RULE]
        args += ['--session-id' if index == 0 else '--resume', session]
        prompt = ('Follow AGENTS.md and run the setup-hosting choice step. ' if index == 0 else '') + turn
        result = subprocess.run(args + [prompt], cwd=project, env=env, text=True, capture_output=True, timeout=600)
        with transcript.open('a') as stream:
            stream.write(json.dumps({'person':turn,'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr})+'\n')
        require(result.returncode == 0, 'model call failed; inspect transcript')
    (evidence / 'REVIEW.md').write_text('Not judged. Compare the transcript and project files with expected.json. Count warnings by meaning, check the saved choice and acceptance, and confirm that the command stopped without creating anything on a host. A completed model call is not a replay pass.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry', action='store_true')
    mode.add_argument('--run', action='store_true')
    parser.add_argument('--case', default='all')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        paths = sorted(CASES.glob('*.json'))
        if args.case != 'all':
            paths = [p for p in paths if p.stem == args.case]
        require(bool(paths), 'no matching replay case')
        require(not args.run or args.output is not None, '--run needs a new --output folder')
        with tempfile.TemporaryDirectory(prefix='host-choice-dry-') as temporary:
            out = args.output.resolve() if args.output else Path(temporary) / 'cases'
            require(not out.exists(), 'output folder must be new')
            require(out != ROOT and ROOT not in out.parents, 'output must be outside the repository')
            out.mkdir(parents=True)
            for path in paths:
                case = load_case(path)
                evidence = out / case['name']; evidence.mkdir()
                project = build(case, evidence / 'project')
                dry_check(case, project)
                # Keep answers and future turns outside the model's working folder.
                for name in ('expected.json','person-turns.json'):
                    shutil.move(str(project / name), evidence / name)
                if args.run:
                    run_case(case, project, evidence)
                    print(case['name'] + ': run saved, maintainer judgement pending')
                else:
                    print(case['name'] + ': dry passed; skill command matches allow rule and runs from project root, no model called')
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print('replay failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
