#!/usr/bin/env python3
"""Rehearse both real installers in disposable projects, without a model or host."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = {'setup-hosting', 'go-live', 'check-live', 'change-live'}
SHARED = COMMANDS - {'setup-hosting'}
INSTALLER = 'skills@1.7.6'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def tracked_copy(source, destination):
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=source).decode().split('\0')
    destination.mkdir()
    for name in filter(None, names):
        path = source / name
        require(path.is_file() and not path.is_symlink(), 'tracked source must be a regular file')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def contents(folder):
    return {str(p.relative_to(folder)): p.read_bytes()
            for p in folder.rglob('*') if p.is_file()}


def rehearsal(build, output):
    for tool in ('git', 'node', 'npm', 'npx', 'claude'):
        if not shutil.which(tool):
            print('INCOMPLETE: missing ' + tool, file=sys.stderr)
            return 77
    require(build != ROOT, 'supply an AI Build Kit checkout')
    require(not output.exists(), 'output folder must be new')
    for source in (ROOT, build):
        require(output != source and source not in output.parents,
                'output must be outside both source repositories')
    require((build / '.agents/skills/setup-hosting/SKILL.md').is_file(),
            'use a Build Kit checkout that still has setup-hosting')
    output.mkdir(parents=True)
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(output / 'claude-config'),
               npm_config_cache=str(output / 'npm-cache'),
               DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
    logs = output / 'logs'; logs.mkdir()

    def run(name, args, cwd):
        print('Running ' + name, flush=True)
        with (logs / (name + '.log')).open('w') as log:
            result = subprocess.run([str(a) for a in args], cwd=cwd, env=env,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=240)
        require(result.returncode == 0, name + ' failed; inspect its log')
        return (logs / (name + '.log')).read_text()

    sources = {}
    for name, source in (('ai-build-kit', build), ('ai-host-kit', ROOT)):
        sources[name] = output / (name + '-source')
        tracked_copy(source, sources[name])

    evidence = {'installer': INSTALLER, 'commands': {}, 'source_revisions': {}}
    for name, source in (('ai-build-kit', build), ('ai-host-kit', ROOT)):
        evidence['source_revisions'][name] = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=source).decode().strip()
    evidence['source_note'] = 'Tracked files are copied from disk; save the tree before a final rehearsal.'

    project = output / 'plugin-project'; project.mkdir()
    run('plugin-project-init', ['git', 'init', '-q'], project)
    run('claude-version', ['claude', '--version'], project)
    sentinel = project / 'AGENTS.md'; sentinel.write_text('Project instructions stay here.\n')
    app = project / 'app.txt'; app.write_text('Application code stays here.\n')
    unchanged = {p: p.read_bytes() for p in (sentinel, app)}

    def plugin_install(name):
        run(name + '-marketplace', ['claude', 'plugin', 'marketplace', 'add', sources[name],
                                   '--scope', 'local'], project)
        run(name + '-plugin', ['claude', 'plugin', 'install', name + '@' + name,
                              '--scope', 'local'], project)

    def installed(name, log):
        entries = json.loads(run(log, ['claude', 'plugin', 'list', '--json'], project))
        matches = [e for e in entries if e['id'] == name + '@' + name]
        require(len(matches) == 1 and matches[0]['enabled'], name + ' plugin is not enabled')
        if name == 'ai-host-kit':
            require(any(e['id'] == 'ai-build-kit@ai-build-kit' and e['enabled'] for e in entries),
                    'Build Kit plugin is no longer enabled')
        entry = matches[0]
        # Local marketplaces may load directly from their source folder.
        folder = Path(entry.get('readFromFolder') or entry['installPath'])
        require(output in folder.resolve().parents, 'plugin escaped the disposable folder')
        return folder

    def commands(folder):
        manifest = json.loads((folder / '.claude-plugin/plugin.json').read_text())
        paths = manifest['commands']
        require(all((folder / p).is_file() for p in paths), 'plugin command file is missing')
        require(len(paths) == len(set(paths)), 'plugin has duplicate command entries')
        return {Path(p).stem for p in paths}

    plugin_install('ai-build-kit')
    build_plugin = installed('ai-build-kit', 'plugin-before')
    before = contents(build_plugin)
    build_commands = commands(build_plugin)
    require('setup-hosting' in build_commands, 'Build Kit plugin lacks setup-hosting')
    plugin_install('ai-host-kit')
    host_plugin = installed('ai-host-kit', 'plugin-after')
    require(commands(host_plugin) == COMMANDS, 'Host Kit plugin must list four commands')
    require(contents(build_plugin) == before, 'Build Kit plugin changed')
    prefixed_host = {'ai-host-kit:' + n for n in commands(host_plugin)}
    prefixed_build = {'ai-build-kit:' + n for n in build_commands}
    require(not prefixed_host & prefixed_build, 'plugin command clash')
    require(all(p.read_bytes() == data for p, data in unchanged.items()), 'project files changed')
    evidence['commands']['plugin'] = sorted(prefixed_host)
    evidence['plugin_build_kit_unchanged'] = True
    print('PASS: plugin lists four prefixed commands; Build Kit is unchanged.', flush=True)

    project = output / 'shared-project'; project.mkdir()
    sentinel = project / 'AGENTS.md'; sentinel.write_text('Project instructions stay here.\n')
    app = project / 'app.txt'; app.write_text('Application code stays here.\n')
    unchanged = {p: p.read_bytes() for p in (sentinel, app)}
    installer = ['npx', '--yes', INSTALLER, 'add']
    agents = ['--agent', 'codex', 'claude-code', 'cursor', 'gemini-cli', 'github-copilot', '--yes']
    run('shared-build-kit', installer + [sources['ai-build-kit'], '--skill', '*'] + agents, project)
    folders = [project / '.agents/skills', project / '.claude/skills']
    before = {folder: contents(folder) for folder in folders}
    names_before = {p.name for p in folders[0].iterdir()}
    for folder in folders:
        require((folder / 'setup-hosting/SKILL.md').is_file(), 'Build Kit setup-hosting is missing')
    lock = project / 'skills-lock.json'
    lock_before = json.loads(lock.read_text())['skills'] if lock.exists() else None
    run('shared-host-kit', installer + [sources['ai-host-kit'], '--skill'] + sorted(SHARED) + agents, project)
    for folder in folders:
        after = contents(folder)
        require(all(after.get(name) == data for name, data in before[folder].items()),
                'installed Build Kit files changed')
        for name in SHARED:
            require((folder / name / 'SKILL.md').read_bytes() ==
                    (sources['ai-host-kit'] / '.agents/skills' / name / 'SKILL.md').read_bytes(),
                    'Host Kit skill differs from source: ' + name)
    names_after = {p.name for p in folders[0].iterdir()}
    require(names_after - names_before == SHARED, 'shared route must add exactly three skills')
    if lock_before is not None:
        lock_after = json.loads(lock.read_text())['skills']
        require(all(lock_after.get(name) == data for name, data in lock_before.items()),
                'Build Kit source records changed')
    listing = json.loads(run('shared-list', ['npx', '--yes', INSTALLER, 'list', '--json'], project))
    for name in COMMANDS:
        matches = [s for s in listing if s['name'] == name and s['scope'] == 'project']
        require(len(matches) == 1, 'shared installer must list one skill named ' + name)
        owner = 'ai-build-kit' if name == 'setup-hosting' else 'ai-host-kit'
        require(matches[0]['source'] == str(sources[owner]), 'shared skill has the wrong source')
        require({'Codex', 'Claude Code', 'Cursor', 'Gemini CLI', 'GitHub Copilot'} <=
                set(matches[0]['agents']), 'shared skill is missing a selected coding agent')
    require(all(p.read_bytes() == data for p, data in unchanged.items()), 'project files changed')
    evidence['commands']['shared'] = sorted(SHARED)
    evidence['shared_build_kit_unchanged'] = True
    (output / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS: shared route adds three skills; Build Kit setup-hosting and other skills are unchanged.')
    print('Evidence and installer logs: ' + str(output))
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build_kit', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        sys.exit(rehearsal(args.build_kit.resolve(), args.output.resolve()))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('FAIL or INCOMPLETE: ' + str(exc), file=sys.stderr)
        sys.exit(1)
