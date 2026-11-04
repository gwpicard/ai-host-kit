"""Boundary rehearsals for AI Host Kit; no host, model or credentials required."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
COMMANDS = {'setup-hosting', 'go-live', 'check-live', 'change-live'}


def run(args, cwd=ROOT, expected=0, env=None, input=None):
    merged = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    # Disposable runners must not append their planted failures to the real job summary.
    merged.pop('GITHUB_STEP_SUMMARY', None)
    if env:
        merged.update(env)
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=merged, input=input,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if expected is not None:
        assert result.returncode == expected, f'{args[0]} exited {result.returncode}:\n{result.stdout}'
    return result


def snapshot(destination):
    destination.mkdir()
    paths = run(['git', 'ls-files', '-z']).stdout.split('\0')
    for name in filter(None, paths):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, path)
    run(['git', 'init', '-q'], cwd=destination)
    run(['git', 'add', '-A'], cwd=destination)
    return destination


def refused(args, cwd, reason):
    result = run(args, cwd=cwd, expected=None)
    assert result.returncode != 0, f'fault was accepted: {reason}'
    assert reason in result.stdout, result.stdout
    return result.stdout


def source_rules(work):
    tree = snapshot(work / 'source')
    validator = ['./.agents/tools/validate-kit.sh']
    run(validator, cwd=tree)
    def mutation(name, replacement, reason):
        path = tree / name
        original = path.read_text()
        path.write_text(replacement(original))
        try:
            output = refused(validator, tree, reason)
            print('Refused: ' + reason)
            return output
        finally:
            path.write_text(original)
    mutation('README.md', lambda t: '\n'.join(s for s in t.splitlines() if not s.startswith('>')) + '\n', 'README beta notice is required')
    # A line saying beta elsewhere does not replace the warning block.
    mutation('README.md', lambda t: '\n'.join(s for s in t.splitlines() if not s.startswith('>')) + '\nBeta.\n', 'README beta notice is required')
    mutation('README.md', lambda t: t + '\nIssue ' + chr(35) + '7\n', 'issue or pull request number')
    mutation('README.md', lambda t: t + '\nhttps://github.com/example/tool/pull/' + '12345\n', 'issue or pull request number')
    mutation('README.md', lambda t: t + '\nCo-' + 'Authored-By: Example\n', 'attribution or session link')
    mutation('README.md', lambda t: t + '\nGenerated ' + 'by Codex\n', 'attribution or session link')
    mutation('README.md', lambda t: t + '\nA sentence' + chr(0x2014) + 'with a dash.\n', 'em or en dash')
    mutation('README.md', lambda t: t.replace('| `/go-live` |', '| `/publish` |'), 'command list does not match')
    mutation('.claude/commands/check-live.md', lambda t: t + '\nStale.\n', 'adapter drift')
    mutation('.agents/tools/kit-inventory.txt', lambda t: t + 'command fifth\n', 'exactly the four hosting commands')
    mutation('release-manifest.txt', lambda t: t + '.agents/maintainer-skills|\n', 'maintainer or undeclared material')
    mutation('.claude-plugin/plugin.json', lambda t: t.replace('"0.0.1"', '"0.0.2"'), 'version markers disagree')
    # The scanner reports the path, never the planted value.
    fake = 'gh' + 'p_' + ('X' * 36)
    output = mutation('README.md', lambda t: t + '\n' + fake + '\n', 'possible secret, value withheld')
    assert fake not in output
    path = tree / '.agents/maintainer-skills/writing-review/LICENSE'
    licence = path.read_bytes()
    path.unlink()
    try:
        refused(validator, tree, 'licence is missing')
    finally:
        path.write_bytes(licence)
    # Rewrapping the warning preserves it.
    p = tree / 'README.md'
    original = p.read_text()
    p.write_text(original.replace('and no\n> host is proven yet.', 'and no host is proven yet.'))
    run(validator, cwd=tree)
    p.write_text(original)
    # A future stable version may remove the warning, but a different beta cannot.
    for version in ('0.9.9', '1.0.0'):
        beta = snapshot(work / ('beta-' + version))
        for name in ('.claude-plugin/plugin.json', 'agent-plugin/plugin.json'):
            p = beta / name
            data = json.loads(p.read_text()); data['version'] = version
            p.write_text(json.dumps(data, indent=2) + '\n')
        (beta / '.ai-host-kit-version').write_text('v' + version + '\n')
        p = beta / 'README.md'
        p.write_text('\n'.join(s for s in p.read_text().splitlines() if not s.startswith('>')) + '\n')
        if version.startswith('0'):
            refused(validator, beta, 'README beta notice is required')
        else:
            run(validator, cwd=beta)
    print('Source mutations failed for their intended rules; stable-version notice boundary passed.')


def release_builder(work):
    builder = ROOT / '.agents/tools/build-release.sh'
    packs = [work / 'pack-a', work / 'pack-b']
    for p in packs:
        run([builder, 'v0.0.2', p])
    def contents(pack):
        return {str(p.relative_to(pack)): (p.read_bytes(), p.stat().st_mode & 0o777)
                for p in pack.rglob('*') if p.is_file()}
    assert contents(packs[0]) == contents(packs[1]), 'release is not repeatable'
    pack = packs[0]
    assert (pack / '.ai-host-kit-version').read_text() == 'v0.0.2\n'
    for name in ('LICENSE', 'NOTICES'):
        assert (pack / name).read_bytes() == (ROOT / name).read_bytes()
    for name in ('.claude-plugin/plugin.json', 'agent-plugin/plugin.json'):
        assert json.loads((pack / name).read_text())['version'] == '0.0.2'
    for name in COMMANDS:
        source = (ROOT / f'.agents/skills/{name}/SKILL.md').read_bytes()
        assert (pack / f'.agents/skills/{name}/SKILL.md').read_bytes() == source
        assert (pack / f'agent-plugin/skills/{name}/SKILL.md').read_bytes() == source
    for forbidden in ('AGENTS.md', '.agents/tools', '.agents/tests', '.agents/maintainer-skills', '.githooks', '.github/workflows', 'docs/MAINTAINING.md', 'release-manifest.txt'):
        assert not (pack / forbidden).exists(), f'maintainer material shipped: {forbidden}'
    # The manifest predicts exactly the built tree, including plugin skill copies.
    sys.path.insert(0, str(ROOT / '.agents/tools'))
    import kit
    assert set(contents(pack)) == set(kit.packing_list())
    refused([builder, 'v0.0.2', pack], ROOT, 'output already exists')
    refused([builder, '0.0.2', work / 'invalid'], ROOT, 'usage:')
    tree = snapshot(work / 'source')
    local_builder = ['./.agents/tools/build-release.sh', 'v0.0.1']
    refused(local_builder + [tree / 'inside'], tree, 'outside the maintainer source')
    alias = work / 'alias'; alias.symlink_to(tree, target_is_directory=True)
    refused(local_builder + [alias / 'inside'], tree, 'outside the maintainer source')
    (tree / '.agents/skills/go-live/untracked.txt').write_text('Do not ship.\n')
    clean = work / 'without-untracked'
    run(local_builder + [clean], cwd=tree)
    assert not (clean / '.agents/skills/go-live/untracked.txt').exists()
    manifest = tree / 'release-manifest.txt'
    original = manifest.read_text()
    for addition, reason in (
        ('../outside|README.md\n', 'manifest path must stay'),
        ('README.md|../outside\n', 'manifest path must stay'),
        ('README.md|README.md\n', 'overlapping release destination'),
        ('.agents/maintainer-skills|\n', 'maintainer or undeclared material'),
        ('AGENTS.md|README.md\n', 'maintainer or undeclared material')):
        manifest.write_text(original + addition)
        output = work / 'refused'
        refused(local_builder + [output], tree, reason)
        assert not output.exists(), 'refusal left an output folder'
    manifest.write_text(original)
    readme = tree / 'README.md'; readme.unlink(); readme.symlink_to(ROOT / 'README.md')
    refused(local_builder + [work / 'symlink'], tree, 'release source is a symlink')
    assert not (work / 'symlink').exists()
    print('Repeatable release, complete plugins, preserved notices and all packing refusals passed.')


def yaml_document(path):
    output = run(['ruby', '-ryaml', '-rjson', '-e', 'puts JSON.generate(YAML.load_file(ARGV[0]))', path]).stdout
    return json.loads(output)


def pull_request_checks(work):
    base = ROOT / '.agents/tools/check-pull-request-base.sh'
    run([base, 'main'])
    for value in ('stable', 'feature', '', 'main; echo unsafe'):
        result = run([base, value], expected=None)
        assert result.returncode != 0
    run([base], expected=2)
    label = ROOT / '.agents/tools/check-release-label.sh'
    for value in ('feature', 'enhancement', 'bug', 'documentation', 'chore', 'skip-release-notes', 'release-major', 'release-minor', 'release-patch'):
        run([label], input=value + '\n')
    for value in ('', 'area:release\n', 'not-chore\n', 'chore; echo unsafe\n'):
        run([label], input=value, expected=1)
    workflows = ROOT / '.github/workflows'
    source = yaml_document(workflows / 'source-checks.yml')
    assert set(source['jobs']) == {'source-kit-validation', 'rehearsal'}
    assert 'pull_request' in source.get('on', source.get('true', {}))
    required = {'source-kit-validation': ['.agents/tools/build-adapters.sh --check', '.agents/tools/validate-kit.sh'],
                'rehearsal': ['.agents/tests/run-all.sh']}
    for name, commands in required.items():
        job = source['jobs'][name]
        assert 'if' not in job, 'source check can be skipped'
        runs = [step.get('run', '') for step in job['steps']]
        assert all(c in runs for c in commands)
    for name, job_id, events, command, variable in (
        ('pull-request-base.yml', 'pull-request-base', {'edited'}, '.agents/tools/check-pull-request-base.sh "$BASE"', 'BASE'),
        ('release-label.yml', 'release-label', {'labeled', 'unlabeled'}, '.agents/tools/check-release-label.sh', 'LABELS')):
        document = yaml_document(workflows / name)
        triggers = document.get('on', document.get('true'))
        assert events <= set(triggers['pull_request']['types'])
        assert set(document['jobs']) == {job_id}
        steps = document['jobs'][job_id]['steps']
        matching = [s for s in steps if command in s.get('run', '')]
        assert len(matching) == 1 and variable in matching[0]['env']
    for path in workflows.glob('*.yml'):
        document = yaml_document(path)
        assert document['permissions'] == {'contents': 'read'}
        assert 'pull_request_target' not in document.get('on', document.get('true'))
        for job in document['jobs'].values():
            assert 'if' not in job
            assert any('checkout@' in s.get('uses', '') and s.get('with', {}).get('persist-credentials') is False for s in job['steps'])
    print('Unlabelled pull requests and every base except main refused; workflow wiring passed.')


def commit_hook(work):
    repo = work / 'repo'; repo.mkdir()
    run(['git', 'init', '-q'], cwd=repo)
    run(['git', 'config', 'core.hooksPath', str(ROOT / '.githooks')], cwd=repo)
    (repo / 'sample').write_text('A saved checkpoint.\n')
    run(['git', 'add', 'sample'], cwd=repo)
    message = work / 'message'
    message.write_text('Check the commit hook\n\nProse about Claude Code stays.\n\n---\n\nCo-' + 'Authored-By: Claude <noreply@' + 'anthropic.com>\nClaude-' + 'Session: https://claude.ai/code/' + 'session_sample\n')
    run(['git', '-c', 'user.name=Guillaume Picard', '-c', 'user.email=rehearsal@example.invalid', 'commit', '-q', '-F', message], cwd=repo)
    saved = run(['git', 'log', '-1', '--format=%B'], cwd=repo).stdout.strip()
    assert saved == 'Check the commit hook\n\nProse about Claude Code stays.', saved
    assert run(['git', 'log', '-1', '--format=%an'], cwd=repo).stdout.strip() == 'Guillaume Picard'
    print('A real disposable commit kept the prose and removed the attribution block and separator.')


def rehearsal_runner(work):
    def suite(name, scripts):
        folder = work / name / '.agents/tests'; folder.mkdir(parents=True)
        shutil.copy2(ROOT / '.agents/tests/run-all.sh', folder / 'run-all.sh')
        for title, body in scripts.items():
            p = folder / title; p.write_text('#!/usr/bin/env sh\n' + body); p.chmod(0o755)
        return folder.parents[1]
    mixed = suite('mixed', {'a-fail.sh':'echo first-failed\nexit 1\n', 'b-pass.sh':'echo later-ran\n', 'c-incomplete.sh':'echo "could-not-run: tool unavailable"\nexit 2\n'})
    result = run(['.agents/tests/run-all.sh'], cwd=mixed, expected=1)
    assert 'later-ran' in result.stdout and '1 of 3 rehearsals passed' in result.stdout
    assert '1 failed; 1 could not run' in result.stdout
    incomplete = suite('incomplete', {'only.sh':'echo "could-not-run: tool unavailable"\nexit 2\n'})
    result = run(['.agents/tests/run-all.sh'], cwd=incomplete, env={'GITHUB_ACTIONS':'false'})
    assert '0 of 1 rehearsals passed' in result.stdout
    run(['.agents/tests/run-all.sh'], cwd=incomplete, expected=1, env={'GITHUB_ACTIONS':'true'})
    crashed = suite('crashed', {'only.sh':'exit 2\n'})
    run(['.agents/tests/run-all.sh'], cwd=crashed, expected=1)
    # A synchronisation copy must not make the runner call itself forever.
    shutil.copy2(ROOT / '.agents/tests/run-all.sh', incomplete / '.agents/tests/run-all copy.sh')
    run(['.agents/tests/run-all.sh'], cwd=incomplete, env={'GITHUB_ACTIONS':'false'})
    print('Runner continued after failure and never counted an incomplete or crashed check as passed.')


if __name__ == '__main__':
    actions = {'source-rules': source_rules, 'release-builder': release_builder,
               'pull-request-checks': pull_request_checks, 'commit-hook': commit_hook,
               'rehearsal-runner': rehearsal_runner}
    with tempfile.TemporaryDirectory(prefix='ahk-check-') as folder:
        actions[sys.argv[1]](Path(folder))
