"""Boundary rehearsals for AI Host Kit; no host, model or credentials required."""
import json
import importlib.util
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
COMMANDS = {'setup-hosting', 'go-live', 'check-live', 'change-live'}
CATEGORIES = ('feature', 'enhancement', 'bug', 'documentation', 'chore', 'skip-release-notes',
              'release-major', 'release-minor', 'release-patch')


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
    # A warning hidden in an HTML comment is not visible to readers.
    mutation('README.md', lambda t: t.replace('> **Beta', '<!--\n> **Beta').replace('> host is proven yet. Do not rely on it for a tool people depend on.', '> host is proven yet. Do not rely on it for a tool people depend on.\n-->'), 'README beta notice is required')
    mutation('README.md', lambda t: t + '\nIssue ' + chr(35) + '7\n', 'issue or pull request number')
    mutation('README.md', lambda t: t + '\nowner/repo' + chr(35) + '7\n', 'issue or pull request number')
    mutation('README.md', lambda t: t + '\nhttps://github.com/example/tool/pull/' + '12345\n', 'issue or pull request number')
    mutation('README.md', lambda t: t + '\nCo-' + 'Authored-By: Example\n', 'attribution or session link')
    mutation('README.md', lambda t: t + '\nGenerated ' + 'by Codex\n', 'attribution or session link')
    mutation('README.md', lambda t: t + '\nA sentence' + chr(0x2014) + 'with a dash.\n', 'em or en dash')
    mutation('README.md', lambda t: t.replace('| `/go-live` |', '| `/publish` |'), 'command list does not match')
    mutation('.agents/skills/host-fit/resources/recipes/azure/capabilities.json', lambda t: t + '\n', 'adapter drift')
    mutation('.claude/commands/check-live.md', lambda t: t + '\nStale.\n', 'adapter drift')
    mutation('.agents/tools/kit-inventory.txt', lambda t: t + 'command fifth\n', 'exactly the four hosting commands')
    mutation('release-manifest.txt', lambda t: t + '.agents/maintainer-skills|\n', 'maintainer or undeclared material')
    mutation('.claude-plugin/plugin.json', lambda t: t.replace('"0.0.1"', '"0.0.2"'), 'version markers disagree')
    mutation('.agents/skills/recipes/coolify-hetzner/scripts/mcp.py', lambda t: t.replace("KIT_VERSION = '0.0.1'", "KIT_VERSION = '0.0.2'"), 'version markers disagree')
    mutation('.agents/skills/recipes/coolify-hetzner/scripts/mcp.py', lambda t: t.replace("KIT_VERSION = '0.0.1'", "VERSION = '0.0.1'"), 'expected exactly one KIT_VERSION line')
    mutation('.ai-host-kit-version', lambda t: 'v0.0.2\n', 'version markers disagree')
    # Installs follow the stable branch; any other source would publish main or a fork.
    for source in ('"./"', '{"source": "github", "repo": "gwpicard/ai-host-kit"}',
                   '{"source": "github", "repo": "gwpicard/ai-host-kit", "ref": "main"}',
                   '{"source": "github", "repo": "someone/ai-host-kit", "ref": "stable"}'):
        mutation('.claude-plugin/marketplace.json',
                 lambda t, s=source: json.dumps(dict(json.loads(t), plugins=[dict(json.loads(t)['plugins'][0], source=json.loads(s))])),
                 'marketplace must install the plugin from gwpicard/ai-host-kit at the stable branch')
    mutation('.claude-plugin/marketplace.json',
             lambda t: json.dumps(dict(json.loads(t), plugins=[dict(json.loads(t)['plugins'][0], version='9.9.9')])),
             'without its own version')
    mutation('.agents/tools/validate-kit.sh',
             lambda t: t + '\nfor ((i=0; i<1; i++)); do :; done\n',
             'script and configuration syntax')
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
    sys.path.insert(0, str(ROOT / '.agents/tools'))
    import kit
    for version in ('0.9.9', '1.0.0'):
        beta = snapshot(work / ('beta-' + version))
        for name, text in kit.stamp_versions(lambda name: (beta / name).read_text(), version).items():
            (beta / name).write_text(text)
        p = beta / 'README.md'
        p.write_text('\n'.join(s for s in p.read_text().splitlines() if not s.startswith('>')) + '\n')
        if version.startswith('0'):
            refused(validator, beta, 'README beta notice is required')
        else:
            run(validator, cwd=beta)
    print('Source mutations failed for their intended rules; stable-version notice boundary passed.')


def release_builder(work):
    sys.path.insert(0, str(ROOT / '.agents/tools'))
    from record_validation import dependencies
    if dependencies() is None:
        print('could-not-run: schema packages are missing')
        sys.exit(2)
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
    # Every shipped copy of the MCP client reports the release version.
    for name in ('.agents/skills', 'agent-plugin/skills'):
        client = (pack / name / 'host-fit/resources/recipes/coolify-hetzner/scripts/mcp.py').read_text()
        assert "KIT_VERSION = '0.0.2'" in client and '0.0.1' not in client
    for name in COMMANDS:
        source = (ROOT / f'.agents/skills/{name}/SKILL.md').read_bytes()
        assert (pack / f'.agents/skills/{name}/SKILL.md').read_bytes() == source
        assert (pack / f'agent-plugin/skills/{name}/SKILL.md').read_bytes() == source
    for forbidden in ('AGENTS.md', '.agents/tools', '.agents/tests', '.agents/maintainer-skills', '.githooks', '.github/workflows', 'docs/MAINTAINING.md', 'release-manifest.txt'):
        assert not (pack / forbidden).exists(), f'maintainer material shipped: {forbidden}'
    # Use each packaged skill's documented command from a separate project.
    # A plugin root is resolved once from the skill's installed location.
    spec = importlib.util.spec_from_file_location('replay', ROOT / '.agents/tools/replay-host-choice.py')
    replay = importlib.util.module_from_spec(spec); spec.loader.exec_module(replay)
    project = work / 'plugin project'; (project / 'hosting').mkdir(parents=True)
    shutil.copy2(ROOT / '.agents/tests/fixtures/contracts/handover/valid.json',
                 project / 'hosting/handover.json')
    for route, plugin, location in (
        ('Claude Code plugin', pack, '.agents/skills'),
        ('Agent Plugins package', pack / 'agent-plugin', 'skills'),
    ):
        prefix = replay.skill_command(plugin / location / 'host-fit/SKILL.md', route)
        command = shlex.split(prefix.replace('<plugin-root>', str(plugin)))
        assert json.loads(run(command + ['menu'], cwd=project).stdout) == []
        run(command + ['check-recipes'], cwd=project)
        output = run(command + ['questions', '--handover', 'hosting/handover.json'], cwd=project)
        assert [q['id'] for q in json.loads(output.stdout)] == ['cloud', 'care']
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


def stable_release(work):
    """Prepare releases in a disposable clone whose origin is a local bare repository."""
    origin = work / 'origin.git'
    run(['git', 'init', '-q', '--bare', '-b', 'main', origin])
    tree = snapshot(work / 'maintainer')
    git = ['git', '-c', 'user.name=Guillaume Picard', '-c', 'user.email=rehearsal@example.invalid']
    def save(message):
        run(git + ['commit', '-q', '-m', message], cwd=tree)
        return run(['git', 'rev-parse', 'HEAD'], cwd=tree).stdout.strip()
    run(['git', 'config', 'user.email', 'rehearsal@example.invalid'], cwd=tree)
    run(['git', 'checkout', '-q', '-b', 'main'], cwd=tree)
    first = save('Source')
    run(['git', 'remote', 'add', 'origin', origin], cwd=tree)
    run(['git', 'push', '-q', 'origin', 'main'], cwd=tree)
    run(['git', 'fetch', '-q', 'origin'], cwd=tree)
    prepare = ['./.agents/tools/prepare-stable.sh']
    sys.path.insert(0, str(ROOT / '.agents/tools'))
    import kit
    def versions(commit):
        return kit.read_versions(lambda name: run(['git', 'show', f'{commit}:{name}'], cwd=tree).stdout)
    def refs(repo):
        return run(['git', 'for-each-ref', '--format=%(refname) %(objectname)'], cwd=repo).stdout
    assert set(versions(first).values()) == {'0.0.1'}
    # Refusals leave no branch, tag or commit behind.
    before = refs(tree)
    for args, reason in ((['0.1.0'], 'usage:'), (['v0.1'], 'usage:'),
                         (['v0.0.1'], 'not newer than v0.0.1 (the source commit)'),
                         (['v0.0.1-rc.1'], 'not newer than v0.0.1'),
                         (['v0.1.0', 'no-such-commit'], 'no such commit')):
        refused(prepare + args, tree, reason)
    assert refs(tree) == before, 'a refusal left a ref behind'
    (tree / 'README.md').write_text((tree / 'README.md').read_text() + '\nUnsaved.\n')
    refused(prepare + ['v0.1.0'], tree, 'unsaved or untracked changes')
    run(['git', 'checkout', '-q', '--', 'README.md'], cwd=tree)
    (tree / 'stray.txt').write_text('Untracked.\n')
    refused(prepare + ['v0.1.0'], tree, 'unsaved or untracked changes')
    (tree / 'stray.txt').unlink()
    run(['git', 'checkout', '-q', '-b', 'topic'], cwd=tree)
    (tree / 'NOTICES').write_text((tree / 'NOTICES').read_text() + '\nUnmerged.\n')
    run(['git', 'add', 'NOTICES'], cwd=tree)
    unmerged = save('Not on main')
    refused(prepare + ['v0.1.0'], tree, 'must already be on origin/main')
    run(['git', 'checkout', '-q', 'main'], cwd=tree)
    p = tree / 'agent-plugin/plugin.json'
    original = p.read_text()
    p.write_text(original.replace('"0.0.1"', '"0.0.2"'))
    run(['git', 'add', '-A'], cwd=tree)
    save('Disagreeing versions')
    run(['git', 'push', '-q', 'origin', 'main'], cwd=tree)
    run(['git', 'fetch', '-q', 'origin'], cwd=tree)
    refused(prepare + ['v0.1.0'], tree, 'version markers disagree')
    p.write_text(original)
    run(['git', 'add', '-A'], cwd=tree)
    source = save('Agreeing versions')
    run(['git', 'push', '-q', 'origin', 'main'], cwd=tree)
    run(['git', 'fetch', '-q', 'origin'], cwd=tree)
    pushed = refs(origin)

    # The first release: one parent, every marker stamped, nothing else changed or pushed.
    result = run(prepare + ['v0.1.0'], cwd=tree)
    commit = run(['git', 'rev-parse', 'release/v0.1.0'], cwd=tree).stdout.strip()
    assert run(['git', 'rev-parse', 'v0.1.0^{commit}'], cwd=tree).stdout.strip() == commit
    assert run(['git', 'cat-file', '-t', 'v0.1.0'], cwd=tree).stdout.strip() == 'tag'
    assert run(['git', 'rev-parse', 'HEAD'], cwd=tree).stdout.strip() == source
    assert not run(['git', 'status', '--porcelain'], cwd=tree).stdout
    assert refs(origin) == pushed, 'the tool pushed'
    assert run(['git', 'log', '-1', '--format=%P %an', commit], cwd=tree).stdout.split() == [source, 'Guillaume', 'Picard']
    assert set(versions(commit).values()) == {'0.1.0'}
    changed = set(run(['git', 'diff', '--name-only', source, commit], cwd=tree).stdout.split())
    assert changed == set(kit.VERSION_FILES), changed
    for name in ('.agents/tools/prepare-stable.sh', '.agents/tools/validate-kit.sh'):
        assert run(['git', 'ls-tree', commit, name], cwd=tree).stdout.startswith('100755 ')
    for line in (f'git push origin {commit}:refs/heads/stable', 'git push origin refs/tags/v0.1.0'):
        assert line in result.stdout, result.stdout
    # The real validator accepts the stamped tree, so the release agrees with itself.
    checkout = work / 'release-checkout'
    run(['git', 'worktree', 'add', '-q', checkout, 'release/v0.1.0'], cwd=tree)
    run(['./.agents/tools/validate-kit.sh'], cwd=checkout)
    run(['git', 'worktree', 'remove', checkout], cwd=tree)
    refused(prepare + ['v0.1.0'], tree, 'not newer than v0.1.0 (tag v0.1.0)')
    for line in result.stdout.splitlines():
        if line.strip().startswith('git push origin'):
            run(shlex.split(line), cwd=tree)
    run(['git', 'fetch', '-q', 'origin'], cwd=tree)
    assert run(['git', 'rev-parse', 'origin/stable'], cwd=tree).stdout.strip() == commit

    # Without the local tag, the stable branch still records the last release.
    run(['git', 'tag', '-d', 'v0.1.0'], cwd=tree)
    refused(prepare + ['v0.1.0'], tree, 'not newer than v0.1.0 (origin/stable)')
    refused(prepare + ['v0.0.9'], tree, 'not newer than v0.1.0')
    run(['git', 'fetch', '-q', 'origin', '--tags'], cwd=tree)

    # The next release keeps stable a fast-forward although main never received the stamp.
    (tree / 'NOTICES').write_text((tree / 'NOTICES').read_text() + '\nLater work.\n')
    run(['git', 'add', 'NOTICES'], cwd=tree)
    later = save('Later work')
    run(['git', 'push', '-q', 'origin', 'main'], cwd=tree)
    run(['git', 'fetch', '-q', 'origin'], cwd=tree)
    refused(prepare + ['v0.1.1', unmerged], tree, 'must already be on origin/main')
    result = run(prepare + ['v0.1.1'], cwd=tree)
    second = run(['git', 'rev-parse', 'release/v0.1.1'], cwd=tree).stdout.strip()
    assert run(['git', 'log', '-1', '--format=%P', second], cwd=tree).stdout.split() == [later, commit]
    assert set(versions(second).values()) == {'0.1.1'}
    assert run(['git', 'show', f'{second}:NOTICES'], cwd=tree).stdout.endswith('Later work.\n')
    for line in result.stdout.splitlines():
        if line.strip().startswith('git push origin'):
            run(shlex.split(line), cwd=tree)  # A plain push refuses anything but a fast-forward.
    # A named older commit on main may be released, but only with a newer version.
    run(['git', 'fetch', '-q', 'origin'], cwd=tree)
    refused(prepare + ['v0.1.1', source], tree, 'not newer than v0.1.1')
    run(prepare + ['v0.2.0-rc.1', source], cwd=tree)
    refused(prepare + ['v0.2.0-beta', source], tree, 'not newer than v0.2.0-rc.1')
    print('Releases are stamped consistently on local commits, never pushed, and keep stable a fast-forward.')


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
    summary = work / 'summary.md'
    for value in CATEGORIES + ('area:release\nbug', 'release-major\nrelease-patch'):
        summary.write_text('')
        result = run([label], input=value + '\n', env={'GITHUB_STEP_SUMMARY': str(summary)})
        assert '::notice' not in result.stdout and summary.read_text() == '', result.stdout
    # A missing category passes with a notice; the release step enforces it.
    for value in ('', 'area:release\n', 'not-chore\n', 'chore; echo unsafe\n'):
        summary.write_text('')
        result = run([label], input=value, env={'GITHUB_STEP_SUMMARY': str(summary)})
        assert result.stdout.startswith('::notice'), result.stdout
        assert all(name in summary.read_text() for name in CATEGORIES)
    # The accepted list comes from one file shared with the opener and the release step.
    tools = snapshot(work / 'tools')
    categories = tools / '.agents/tools/release-categories.txt'
    categories.write_text(categories.read_text().replace('\nchore ', '\nhousekeeping '))
    copied = tools / '.agents/tools/check-release-label.sh'
    assert run([copied], input='chore\n').stdout.startswith('::notice')
    assert '::notice' not in run([copied], input='housekeeping\n').stdout
    opener = ROOT / '.agents/tools/open-pull-request.sh'
    repo = work / 'repo'; repo.mkdir()
    run(['git', 'init', '-q', '-b', 'chore/sample'], cwd=repo)
    (repo / '.agents/tools').mkdir(parents=True)
    for name in ('open-pull-request.sh', 'release-categories.txt'):
        shutil.copy2(ROOT / '.agents/tools' / name, repo / '.agents/tools' / name)
    stub = work / 'bin'; stub.mkdir()
    record = work / 'gh-arguments'
    (stub / 'gh').write_text('#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done > "$GH_RECORD"\n')
    (stub / 'gh').chmod(0o755)
    gh_env = {'PATH': f"{stub}{os.pathsep}{os.environ['PATH']}", 'GH_RECORD': str(record)}
    copy = repo / '.agents/tools/open-pull-request.sh'
    run([copy, 'chore', '--title', 'Sample', '--label', 'area:release'], cwd=repo, env=gh_env)
    assert record.read_text().splitlines() == ['pr', 'create', '--base', 'main', '--head', 'chore/sample',
                                               '--label', 'chore', '--title', 'Sample', '--label', 'area:release']
    for arguments in ([], ['housekeeping'], ['area:release'], ['chore; echo unsafe'], ['--title'],
                      ['chore', '--base', 'stable'], ['chore', '-Bstable'], ['chore', '--head=other']):
        record.unlink(missing_ok=True)
        result = run([copy, *arguments], cwd=repo, env=gh_env, expected=2)
        assert not record.exists(), f'gh ran for {arguments}'
        assert 'chore' in result.stdout and 'release-patch' in result.stdout
    run(['git', 'checkout', '-q', '-b', 'main'], cwd=repo)
    run([copy, 'chore'], cwd=repo, env=gh_env, expected=2)
    assert not record.exists(), 'gh ran from main'
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
    print('Missing categories pass with a notice; the opener refuses unknown categories; every base except main refused; workflow wiring passed.')


def release_categories(work):
    check = ROOT / '.agents/tools/check-release-categories.py'
    N = chr(35)  # Written this way so the source rule against reference numbers does not match.
    def merged(number, labels, when='2026-02-01T00:00:00Z'):
        return {'number': number, 'title': f'Change {number}', 'mergedAt': when,
                'labels': [{'name': name} for name in labels]}
    labelled = [merged(n, [c, 'area:release']) for n, c in enumerate(CATEGORIES, start=1)]
    result = run([sys.executable, check, '--input', '-'], input=json.dumps(labelled))
    assert all(f'{N}{n} ' in result.stdout for n in range(1, len(CATEGORIES) + 1)), result.stdout
    unlabelled = labelled + [merged(40, ['area:release']), merged(41, [])]
    result = run([sys.executable, check, '--input', '-'], input=json.dumps(unlabelled), expected=1)
    assert N + '40 Change 40' in result.stdout and N + '41 Change 41' in result.stdout, result.stdout
    assert N + '1 ' not in result.stdout and 'gh pr edit 40 --add-label' in result.stdout
    # Only pull requests merged after the last release count.
    before = [merged(1, ['bug']), merged(2, [], '2025-12-31T23:59:59Z')]
    path = work / 'merged.json'; path.write_text(json.dumps(before))
    run([sys.executable, check, '--input', path, '--since', '2026-01-01T00:00:00Z'])
    run([sys.executable, check, '--input', path], expected=1)
    for broken in ('{"number": 1}', 'not json', '[{"labels": 7}]'):
        run([sys.executable, check, '--input', '-'], input=broken, expected=2)
    # Without --input it asks gh; a stub stands in so no test reaches GitHub.
    stub = work / 'bin'; stub.mkdir()
    (stub / 'gh').write_text('#!/bin/sh\necho "$*" >> "$GH_RECORD"\ncase "$1" in\n'
                             '  release) echo \'[{"tagName":"v0.0.1","publishedAt":"2026-01-01T00:00:00Z"}]\' ;;\n'
                             '  pr) cat "$GH_PULLS" ;;\nesac\n')
    (stub / 'gh').chmod(0o755)
    record = work / 'gh-record'
    env = {'PATH': f"{stub}{os.pathsep}{os.environ['PATH']}", 'GH_RECORD': str(record), 'GH_PULLS': str(path)}
    result = run([sys.executable, check], env=env)
    assert 'v0.0.1' in result.stdout and N + '2 ' not in result.stdout, result.stdout
    calls = record.read_text()
    assert 'pr list --state merged --base main' in calls and 'release list' in calls, calls
    path.write_text(json.dumps(before + [merged(3, [], '2026-03-01T00:00:00Z')]))
    result = run([sys.executable, check], env=env, expected=1)
    assert N + '3 Change 3' in result.stdout and N + '2 ' not in result.stdout, result.stdout
    (stub / 'gh').write_text('#!/bin/sh\necho "not signed in" >&2\nexit 4\n')
    run([sys.executable, check], env=env, expected=2)
    print('The release step refuses unlabelled merged pull requests, lists them, and proceeds when all have categories.')


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
    print('A real disposable commit kept the prose and removed the Claude attribution block and separator.')


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
    for missing in ('python3', 'git', 'ruby'):
        folder = suite('missing-' + missing, {'source-rules.sh': 'echo group-ran\n'})
        tools = folder / 'bin'; tools.mkdir()
        for tool in ('sh', 'dirname', 'basename', 'mktemp', 'rm', 'tee', 'cat', 'sed',
                     'python3', 'git', 'ruby'):
            if tool != missing:
                target = shutil.which(tool)
                if target:
                    (tools / tool).symlink_to(target)
        result = run(['/bin/sh', '.agents/tests/run-all.sh'], cwd=folder,
                     env={'PATH': str(tools), 'GITHUB_ACTIONS': 'false'})
        assert 'group-ran' not in result.stdout
        assert '0 of 1 rehearsals passed' in result.stdout
        assert '0 failed; 1 could not run' in result.stdout
        assert missing + ' is not on PATH' in result.stdout
    folder = suite('missing-tofu', {'approval-gate.sh': 'exec ' + shlex.join([sys.executable, str(ROOT / '.agents/tests/lib/approval_gate_checks.py')]) + '\n'})
    result = run(['/bin/sh', '.agents/tests/run-all.sh'], cwd=folder,
                 env={'PATH': str(tools), 'GITHUB_ACTIONS': 'false'})
    assert 'could not run: approval-gate' in result.stdout
    assert '0 of 1 rehearsals passed' in result.stdout
    assert '0 failed; 1 could not run' in result.stdout
    assert 'OpenTofu' in result.stdout
    stopped = suite('terminated', {'a-stop.sh':'kill -TERM "$(cat runner.pid)"\n',
                                    'b-later.sh':'touch later-ran\n'})
    scratch = stopped / 'scratch'; scratch.mkdir()
    result = run(['/bin/sh', '-c', 'echo $$ > runner.pid; exec .agents/tests/run-all.sh'],
                 cwd=stopped, expected=143, env={'TMPDIR': str(scratch)})
    assert not (stopped / 'later-ran').exists(), result.stdout
    assert not list(scratch.iterdir()), 'Termination left scratch files behind'
    print('Missing OpenTofu reported as could not run by the real approval group.')
    print('Missing Python, Git and Ruby reported as could not run before the group started.')
    print('Runner continued after failure and never counted an incomplete or crashed check as passed.')


if __name__ == '__main__':
    actions = {'source-rules': source_rules, 'release-builder': release_builder,
               'pull-request-checks': pull_request_checks, 'commit-hook': commit_hook,
               'release-categories': release_categories, 'stable-release': stable_release,
               'rehearsal-runner': rehearsal_runner}
    with tempfile.TemporaryDirectory(prefix='ahk-check-') as folder:
        actions[sys.argv[1]](Path(folder))
