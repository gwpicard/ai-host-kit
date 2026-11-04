#!/usr/bin/env python3
"""Build local host-choice cases; run a model only with the explicit --run flag."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / '.agents/tests/replays/host-choice'


def require(ok, message):
    if not ok:
        raise ValueError(message)


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
        (folder / 'place-record.json').write_text(json.dumps(case['place'], indent=2) + '\n')
    (folder / 'AGENTS.md').write_text('This is a local replay project. Follow .agents/skills/setup-hosting/SKILL.md. Read only the supplied handover. Never contact hosts, provider APIs or external repositories. Do not run another model. Write only local choice files. Do not invent a person\'s answers or acceptance.\n')
    (folder / 'expected.json').write_text(json.dumps(case['expected'], indent=2) + '\n')
    (folder / 'person-turns.json').write_text(json.dumps(case['turns'], indent=2) + '\n')
    # The model must not read the expected result or future person turns.
    (folder / 'AGENTS.md').write_text((folder / 'AGENTS.md').read_text() + 'Do not read expected.json or person-turns.json. They are maintainer evidence, not project inputs.\n')
    subprocess.run(['git', 'init', '-q', str(folder)], check=True)
    return folder


def dry_check(case, project):
    sys.path.insert(0, str(project / '.agents/skills/host-fit/scripts'))
    # A fresh subprocess proves the assembled, installed script resolves its resources.
    script = project / '.agents/skills/host-fit/scripts/host_fit.py'
    base = [sys.executable, str(script)]
    def call(action, *args):
        result = subprocess.run(base + [action] + list(args), cwd=project, text=True, capture_output=True)
        require(result.returncode == 0, 'assembled project check failed: ' + result.stdout + result.stderr)
        return result.stdout
    h = ['--handover', 'hosting/handover.json']
    place = ['--place', 'place-record.json'] if case['place'] else []
    questions = json.loads(call('questions', *h, *place))
    require([q['id'] for q in questions] == case['expected']['questions'], 'question expectation differs')
    (project / 'answers.json').write_text(json.dumps(case['expected']['answers']))
    result = json.loads(call('suggest', *h, *place, '--answers', 'answers.json'))
    require(result['host'] == case['expected']['host'] and result['wish'] == case['expected']['wish'], 'suggestion expectation differs')
    require(result['proof'] == 'not yet proven', 'stub became proven')
    require(json.loads(call('menu')) == [], 'stub reached the menu')
    call('check-recipes')
    for host in ('azure', 'coolify-hetzner', 'vercel-postgres'):
        call('fit', *h, '--recipe', host)
    pending = json.loads(call('warnings', *h, *place, '--recipe', case['expected']['host']))
    require(len(pending) == case['expected']['warnings'], 'warning expectation differs')
    (project / 'answers.json').unlink()


def run_case(case, project, evidence):
    session = str(uuid.uuid4())
    transcript = evidence / 'transcript.jsonl'
    # Keep only CLI/runtime essentials; provider credentials are not needed.
    env = {k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG','SHELL','USER')}
    for index, turn in enumerate(case['turns']):
        args = ['claude', '-p', '--output-format', 'json', '--tools', 'Read,Write,Edit,Bash', '--permission-mode', 'acceptEdits', '--allowedTools', 'Read', 'Write', 'Edit', 'Bash(python3 .agents/skills/host-fit/scripts/host_fit.py *)']
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
                    print(case['name'] + ': dry passed; project assembled, no model called')
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print('replay failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
