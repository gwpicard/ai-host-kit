"""AI Host Kit source checks and packaging, adapted from AI Build Kit.

See docs/SOURCES.md. The public manifest is an allowlist, never a directory dump.
"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = {'setup-hosting', 'go-live', 'check-live', 'change-live'}
BACKGROUNDS = {'host-fit'}
ADAPTER_DIRS = ('.claude/commands', '.cursor/commands', '.gemini/commands')
PUBLIC_FILES = {'README.md', 'LICENSE', 'NOTICES', 'CONTRIBUTING.md', 'SECURITY.md',
                '.ai-host-kit-version', 'docs/PHILOSOPHY.md', 'docs/PROMISES.md',
                'docs/SOURCES.md', 'docs/COMPATIBILITY.md',
                '.claude-plugin/plugin.json', '.claude-plugin/marketplace.json',
                'agent-plugin/plugin.json', '.claude/settings.json'}
VERSION_RE = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?'
# Every file that carries the kit version. The canonical MCP client and its
# generated host-fit copy are stamped alike, so the adapter check still matches.
VERSION_JSON = ('.claude-plugin/plugin.json', 'agent-plugin/plugin.json')
VERSION_TEXT = '.ai-host-kit-version'
VERSION_CODE = ('.agents/skills/recipes/coolify-hetzner/scripts/mcp.py',
                '.agents/skills/host-fit/resources/recipes/coolify-hetzner/scripts/mcp.py')
VERSION_FILES = VERSION_JSON + (VERSION_TEXT,) + VERSION_CODE
CODE_VERSION_RE = re.compile(r"^KIT_VERSION = '([^'\n]*)'$", re.M)
# Users install the plugin from this branch; main is the working branch.
STABLE_BRANCH = 'stable'
MAINTAINER = 'Guillaume Picard'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def tracked():
    return [s.decode() for s in git('ls-files', '-z').split(b'\0') if s]


def error(message):
    raise ValueError(message)


def posix_shell():
    """Require a shell whose parser rejects Bash arithmetic loops on every platform."""
    for name in ('dash', 'posh'):
        shell = shutil.which(name)
        if shell and subprocess.run(
                [shell, '-n', '-c', 'for ((i=0; i<1; i++)); do :; done'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            return shell
    error('strict POSIX shell unavailable: install dash or posh to check shell syntax')


def safe_path(value):
    if not value or '\\' in value or any(c.isspace() for c in value):
        error('manifest path must be a plain relative path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')):
        error('manifest path must stay inside the release')
    return path


def public(path):
    if path in PUBLIC_FILES:
        return True
    for name in COMMANDS | BACKGROUNDS:
        if path.startswith(f'.agents/skills/{name}/') or path.startswith(f'agent-plugin/skills/{name}/'):
            return True
        for directory, ext in zip(ADAPTER_DIRS, ('.md', '.md', '.toml')):
            if path == f'{directory}/{name}{ext}':
                return True
    return False


def packing_list():
    """Resolve tracked source files before writing any output."""
    files = set(tracked())
    result = {}
    for number, line in enumerate((ROOT / 'release-manifest.txt').read_text().splitlines(), 1):
        if not line or line.startswith('#'):
            continue
        fields = line.split('|')
        if len(fields) != 2:
            error(f'release-manifest.txt:{number}: expected source|destination')
        source, destination = fields
        destination = destination or source
        safe_path(source)
        safe_path(destination)
        sources = sorted(f for f in files if f == source or f.startswith(source + '/'))
        if not sources:
            error(f'release-manifest.txt:{number}: source has no tracked files')
        for f in sources:
            current = ROOT
            for part in PurePosixPath(f).parts:
                current = current / part
                if current.is_symlink():
                    error(f'release source is a symlink: {f}')
            if not current.is_file():
                error(f'tracked release source is missing: {f}')
            target = destination + f[len(source):]
            safe_path(target)
            if not public(f) or not public(target):
                error(f'maintainer or undeclared material in release: {f}')
            if target in result or any(target.startswith(p + '/') or p.startswith(target + '/') for p in result):
                error(f'overlapping release destination: {target}')
            result[target] = f
    # Missing entries are as dangerous as leaks: every offered command needs its body.
    required = PUBLIC_FILES | {f'{d}/{n}{e}' for d, e in zip(ADAPTER_DIRS, ('.md', '.md', '.toml')) for n in COMMANDS}
    required |= {f'{d}/{n}/SKILL.md' for d in ('.agents/skills', 'agent-plugin/skills') for n in COMMANDS | BACKGROUNDS}
    if not required <= result.keys():
        error('release manifest is missing required public files: ' + ', '.join(sorted(required - result.keys())))
    return result


def skill_headers():
    inventory = []
    backgrounds = []
    for line in (ROOT / '.agents/tools/kit-inventory.txt').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        fields = line.split()
        if len(fields) != 2 or fields[0] not in ('command', 'background'):
            error('inventory must contain command or background names')
        (inventory if fields[0] == 'command' else backgrounds).append(fields[1])
    if set(inventory) != COMMANDS or len(inventory) != len(COMMANDS):
        error('inventory must list exactly the four hosting commands')
    if set(backgrounds) != BACKGROUNDS or len(backgrounds) != len(BACKGROUNDS):
        error('inventory must list the supported background skills')
    actual = {p.name for p in (ROOT / '.agents/skills').iterdir()}
    if actual != COMMANDS | BACKGROUNDS | {'recipes'}:
        error('installable skill folders do not match the inventory')
    result = {}
    for name in sorted(COMMANDS | BACKGROUNDS):
        path = ROOT / f'.agents/skills/{name}/SKILL.md'
        text = path.read_text()
        match = re.match(r'\A---\nname: ([a-z-]+)\ndescription: ([^\n]+)\n---\n\n(.+)\Z', text, re.S)
        if not match or match[1] != name or ': ' in match[2]:
            error(f'{path.relative_to(ROOT)}: expected name and a plain description in YAML frontmatter')
        if name not in {'setup-hosting'} | BACKGROUNDS and '\n\n' in match[3].strip():
            error(f'{name}: the stub must be one paragraph')
        if name in COMMANDS:
            result[name] = match[2]
    return result


def adapter_files():
    result = {}
    for name, description in skill_headers().items():
        banner = f'<!-- GENERATED from .agents/skills/{name}/. Do not edit; run .agents/tools/build-adapters.sh -->\n\n'
        canonical = f'.agents/skills/{name}/SKILL.md'
        request = "Treat anything after the command as the person's request and pass it through unchanged.\n"
        result[f'.claude/commands/{name}.md'] = (f'---\ndescription: {description}\n---\n' + banner +
            f'Load and follow `${{CLAUDE_PLUGIN_ROOT}}/{canonical}` when installed as a Claude plugin, '
            f'or `{canonical}` otherwise. ' + request)
        result[f'.cursor/commands/{name}.md'] = banner + f'Load and follow `{canonical}`. ' + request
        # JSON strings are also valid TOML basic strings for these descriptions.
        result[f'.gemini/commands/{name}.toml'] = (f'# GENERATED from {canonical}. Do not edit.\n'
            '# Run .agents/tools/build-adapters.sh to regenerate.\n'
            f'description = {json.dumps(description)}\nprompt = """\n'
            f'Load and follow `{canonical}`.\n'
            "Treat the following as the person's request (it may be empty): {{args}}\n" + '"""\n')
    # Bundle dependencies so a skill-only installation has the same reader and data.
    resources = '.agents/skills/host-fit/resources/'
    for name in ('plan-identity.schema.json', 'approval-record.schema.json', 'capabilities.schema.json', 'place-record.schema.json',
                 'host-record.schema.json', 'ai-build-kit/handover.schema.json'):
        result[resources + 'contracts/' + name] = (ROOT / 'contracts' / name).read_text()
    source = ROOT / '.agents/skills/recipes'
    for path in sorted(source.rglob('*')):
        if path.is_file() and '.terraform' not in path.parts and (path.suffix in ('.json', '.md', '.py', '.sh', '.tf', '.hcl') or path.name == 'secrets.example.env'):
            result[resources + 'recipes/' + str(path.relative_to(source))] = path.read_text()
    for name in ('record_validation.py', 'schema-requirements.txt'):
        result[resources + name] = (ROOT / '.agents/tools' / name).read_text()
    resources = '.agents/skills/setup-hosting/resources/'
    for name in ('record_validation.py', 'schema-requirements.txt'):
        result[resources + name] = (ROOT / '.agents/tools' / name).read_text()
    result[resources + 'contracts/plan-identity.schema.json'] = (ROOT / 'contracts/plan-identity.schema.json').read_text()
    result[resources + 'contracts/approval-record.schema.json'] = (ROOT / 'contracts/approval-record.schema.json').read_text()
    result[resources + 'encryption.tf'] = (ROOT / 'tofu/encryption.tf').read_text()
    return result


def build_adapters(args):
    if args not in ([], ['--check']):
        error('usage: build-adapters.sh [--check]')
    expected = adapter_files()
    if args:
        actual = {str(p.relative_to(ROOT)) for d in (*ADAPTER_DIRS, '.agents/skills/host-fit/resources', '.agents/skills/setup-hosting/resources') for p in (ROOT / d).rglob('*') if p.is_file() or p.is_symlink()}
        if actual != expected.keys():
            error('adapter file list has drifted; run build-adapters.sh')
        for path, text in expected.items():
            if (ROOT / path).is_symlink() or (ROOT / path).read_text() != text:
                error(f'adapter drift: {path}; run build-adapters.sh')
        print('adapters match: 4 commands, no drift')
    else:
        for d in (*ADAPTER_DIRS, '.agents/skills/host-fit/resources', '.agents/skills/setup-hosting/resources'):
            folder = ROOT / d
            if folder.is_symlink():
                error(f'adapter directory is a symlink: {d}')
            if folder.exists():
                shutil.rmtree(folder)
        for path, text in expected.items():
            p = ROOT / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            if p.suffix == '.sh':
                p.chmod(0o755)
        print('Generated Claude Code, Cursor and Gemini CLI adapters for 4 commands.')


def build_release(args):
    if len(args) != 2 or not re.fullmatch('v' + VERSION_RE, args[0]):
        error('usage: build-release.sh <vMAJOR.MINOR.PATCH> <new-output-folder>')
    version, raw_output = args
    output = Path(raw_output).absolute()
    if output.name in ('', '.', '..') or not output.parent.is_dir():
        error('output must name a new folder with an existing parent')
    # Resolve existing parents to catch an alias back into the source.
    output = output.parent.resolve() / output.name
    if output == ROOT or ROOT in output.parents:
        error('output must be outside the maintainer source')
    if output.exists() or output.is_symlink():
        error('output already exists')
    if int(version[1:].split('.')[0]) < 1 and not beta_notice((ROOT / 'README.md').read_text()):
        error('README beta notice is required below 1.0')
    packing = packing_list()
    # Stamp every version-bearing source before creating the destination.
    stamped = stamp_versions(lambda name: (ROOT / name).read_text(), version[1:])
    output.mkdir(mode=0o755)
    for destination, source in packing.items():
        path = output / destination
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source, path)
        if source in stamped:
            path.write_text(stamped[source])
    print(f'Built AI Host Kit {version} at {output}')


def read_versions(read):
    """Return the version each version-bearing file carries, without the v prefix."""
    found = {}
    for name in VERSION_JSON:
        value = parse_json(read(name), name).get('version')
        if not isinstance(value, str):
            error(f'{name}: missing version field')
        found[name] = value
    text = read(VERSION_TEXT)
    if not re.fullmatch('v' + VERSION_RE + '\n?', text):
        error(f'{VERSION_TEXT}: expected one line such as v1.2.3')
    found[VERSION_TEXT] = text.strip()[1:]
    for name in VERSION_CODE:
        matches = CODE_VERSION_RE.findall(read(name))
        if len(matches) != 1:
            error(f'{name}: expected exactly one KIT_VERSION line')
        found[name] = matches[0]
    return found


def stamp_versions(read, version):
    """Return the new text of every version-bearing file, carrying version."""
    if not re.fullmatch(VERSION_RE, version):
        error(f'not a version number: {version}')
    read_versions(read)  # Refuse a file whose version cannot be found.
    result = {}
    for name in VERSION_JSON:
        content = parse_json(read(name), name)
        content['version'] = version
        result[name] = json.dumps(content, indent=2) + '\n'
    result[VERSION_TEXT] = 'v' + version + '\n'
    for name in VERSION_CODE:
        result[name] = CODE_VERSION_RE.sub(f"KIT_VERSION = '{version}'", read(name))
    return result


def version_key(version):
    """Order versions by Semantic Versioning precedence; build metadata is not accepted."""
    core, _, pre = version.partition('-')
    numbers = tuple(int(n) for n in core.split('.'))
    if not pre:
        return numbers + (1, ())
    return numbers + (0, tuple((0, int(p), '') if p.isdigit() else (1, 0, p) for p in pre.split('.')))


def prepare_stable(args):
    usage = 'usage: prepare-stable.sh <vMAJOR.MINOR.PATCH> [<commit on origin/main>]'
    if len(args) not in (1, 2) or not re.fullmatch('v' + VERSION_RE, args[0]):
        error(usage)
    tag, version = args[0], args[0][1:]
    def quiet(*command):
        return subprocess.run(['git', '-C', str(ROOT), *command], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True)
    def commit_of(ref):
        result = quiet('rev-parse', '--verify', '--quiet', ref + '^{commit}')
        return result.stdout.strip() if result.returncode == 0 else None
    if git('status', '--porcelain').strip():
        error('the working tree has unsaved or untracked changes; prepare a release from a clean checkout')
    main = commit_of('refs/remotes/origin/main')
    if main is None:
        error('origin/main is not known here; run git fetch origin --tags first')
    source = commit_of(args[1] if len(args) == 2 else 'HEAD')
    if source is None:
        error(f'no such commit: {args[1]}')
    if quiet('merge-base', '--is-ancestor', source, main).returncode != 0:
        error('the release commit must already be on origin/main; fetch, or name a commit on origin/main')
    def read_at(commit):
        return lambda name: git('show', f'{commit}:{name}').decode()
    current = read_versions(read_at(source))
    if len(set(current.values())) != 1:
        error('version markers disagree at the source commit: ' + ', '.join(f'{k}={v}' for k, v in current.items()))
    # The newest known release: the stable branch, any local v tag, or the source's own marker.
    known = [(next(iter(current.values())), 'the source commit')]
    stable = commit_of(f'refs/remotes/origin/{STABLE_BRANCH}')
    for ref, label in ((stable, f'origin/{STABLE_BRANCH}'), (commit_of(f'refs/heads/{STABLE_BRANCH}'), STABLE_BRANCH)):
        if ref:
            known.append((read_at(ref)(VERSION_TEXT).strip()[1:], label))
    for name in git('tag', '--list', 'v*').decode().split():
        if re.fullmatch('v' + VERSION_RE, name):
            known.append((name[1:], 'tag ' + name))
    newest, where = max(known, key=lambda item: version_key(item[0]))
    if version_key(version) <= version_key(newest):
        error(f'{tag} is not newer than v{newest} ({where})')
    branch = f'release/{tag}'
    if quiet('rev-parse', '--verify', '--quiet', f'refs/tags/{tag}').returncode == 0:
        error(f'tag {tag} already exists')
    if commit_of(f'refs/heads/{branch}'):
        error(f'branch {branch} already exists')
    stamped = stamp_versions(read_at(source), version)
    # Build the release tree in a private index; the checkout is never touched.
    with tempfile.TemporaryDirectory(prefix='ahk-stable-') as scratch:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(scratch) / 'index'))
        def indexed(*command, data=None):
            return subprocess.run(['git', '-C', str(ROOT), *command], env=env, input=data,
                                  stdout=subprocess.PIPE, check=True).stdout
        indexed('read-tree', source)
        for name, text in stamped.items():
            mode = git('ls-tree', source, '--', name).decode().split()[0]
            blob = indexed('hash-object', '-w', '--stdin', data=text.encode()).decode().strip()
            indexed('update-index', '--cacheinfo', f'{mode},{blob},{name}')
        tree = indexed('write-tree').decode().strip()
    # A second parent keeps every move of the stable branch a fast-forward.
    parents = ['-p', source]
    if stable and quiet('merge-base', '--is-ancestor', stable, source).returncode != 0:
        parents += ['-p', stable]
    commit = git('-c', f'user.name={MAINTAINER}', 'commit-tree', tree, *parents,
                 '-m', f'Release {tag}').decode().strip()
    git('branch', branch, commit)
    git('-c', f'user.name={MAINTAINER}', 'tag', '-a', tag, '-m', f'AI Host Kit {tag}', commit)
    print(f'Prepared AI Host Kit {tag} as {commit} on {branch}, tagged {tag}.')
    print(f'Source: {source} (origin/main {main}).')
    print('Previous release: ' + (f'v{newest} ({where})'))
    print('Nothing was pushed. Check the release tree, then push both refs:')
    print(f'  git push origin {commit}:refs/heads/{STABLE_BRANCH}')
    print(f'  git push origin refs/tags/{tag}')
    print('To discard it instead:')
    print(f'  git tag -d {tag} && git branch -D {branch}')


def beta_notice(readme):
    readme = re.sub(r'<!--.*?(?:-->|\Z)', '', readme, flags=re.S)
    blocks = re.findall(r'^>.*(?:\n>.*)*', readme, re.M)
    for block in blocks:
        words = ' '.join(re.sub(r'^> ?', '', block, flags=re.M).split())
        if all(phrase in words for phrase in ('Beta and experimental.', 'no host is proven yet', 'Do not rely on it')):
            return True
    return False


def parse_json(text, name):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                error(f'{name}: duplicate JSON key')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def load_json(path):
    return parse_json(path.read_text(), path.relative_to(ROOT))


def validate(args):
    if args:
        error('usage: validate-kit.sh')
    failures = []
    def check(name, action):
        try:
            action()
            print('ok: ' + name)
        except (ValueError, OSError, subprocess.CalledProcessError) as exc:
            failures.append(name)
            print(f'FAIL: {name}: {exc}', file=sys.stderr)
    def require(condition, message):
        if not condition:
            error(message)
    files = tracked()
    def coolify_pin():
        from check_coolify_pin import check as check_pin
        check_pin(ROOT / '.agents/skills/recipes/coolify-hetzner')
    check('Coolify release files and runtime pins agree', coolify_pin)
    def source_rules():
        # Build forbidden samples in parts so the checker never exempts itself.
        attribution = re.compile(r'^\s*co-' + r'authored-by:|^\s*(?:claude|codex|gemini)-session:|'
            r'claude\.ai/code/' + r'session_|noreply@' + r'anthropic\.com|'
            r'^\W*generated (?:with|by) (?:\[)?(?:claude code|codex|chatgpt|gemini)(?:\b)', re.I | re.M)
        references = re.compile(r'\b[\w.-]+/[\w.-]+' + chr(35) + r'\d+\b|'
            r'(?<![\w$}])' + chr(35) + r'\d+\b|/(?:issues|pull)/\d+\b|'
            r'\b(?:issue|pull request|PR)\s+(?:number\s+)?\d+\b', re.I)
        secret = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|'
            r'\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b|\bAKIA[A-Z0-9]{16}\b')
        for name in files:
            p = ROOT / name
            require(p.is_file() and not p.is_symlink(), f'{name}: tracked source must be a regular file')
            require(not re.search(r'(^|/)(?:\.env(?:\.|$)|.*\.(?:pem|key)$)', name), f'{name}: secret file is tracked')
            text = p.read_text()
            require(not secret.search(text), f'{name}: possible secret, value withheld')
            require(not references.search(text), f'{name}: issue or pull request number in tracked text')
            if name != '.githooks/commit-msg':
                require(not attribution.search(text), f'{name}: attribution or session link in tracked text')
    check('tracked files contain no issue references, attribution lines or secret patterns', source_rules)
    check('four commands and frontmatter match the inventory', skill_headers)
    def pointers():
        require((ROOT / 'CLAUDE.md').read_text().strip() == '@AGENTS.md', 'CLAUDE.md must import maintainer instructions')
        require((ROOT / 'GEMINI.md').read_text().strip() == '@./AGENTS.md', 'GEMINI.md must import maintainer instructions')
        require('AGENTS.md' in (ROOT / '.github/copilot-instructions.md').read_text(), 'Copilot must load maintainer instructions')
    check('coding agent pointers load the maintainer instructions', pointers)
    check('generated adapters match canonical commands', lambda: build_adapters(['--check']))
    packing = {}
    def boundary():
        packing.update(packing_list())
        for name in files:
            if 'writing-review' in name:
                require(name.startswith('.agents/maintainer-skills/writing-review/'), 'maintainer skill reached installer discovery')
        require((ROOT / '.agents/maintainer-skills/writing-review/LICENSE').is_file(), 'vendored writing skill licence is missing')
    check('release boundaries exclude maintainer material and keep required files', boundary)
    def prose():
        for name in files:
            # Vendored examples remain unchanged outside the release.
            if name.startswith('.agents/maintainer-skills/'):
                continue
            if Path(name).suffix in ('.md', '.yml', '.yaml', '.toml') or name in packing.values():
                require(not re.search('[\u2013\u2014]', (ROOT / name).read_text()), f'{name}: em or en dash in prose')
        for name in ('README.md', 'docs/COMPATIBILITY.md'):
            found = set(re.findall(r'`/([a-z-]+)`', (ROOT / name).read_text()))
            require(found == COMMANDS, f'{name}: command list does not match inventory')
    check('prose and public command lists follow the house rules', prose)
    manifests = {}
    def metadata():
        for name in ('.claude-plugin/plugin.json', 'agent-plugin/plugin.json'):
            manifests[name] = load_json(ROOT / name)
            require(manifests[name].get('name') == 'ai-host-kit', f'{name}: wrong plugin name')
        claude, agent = manifests.values()
        require(claude.get('commands') == [f'./.claude/commands/{n}.md' for n in sorted(COMMANDS)], 'Claude command list differs from inventory')
        require(not any(k in claude for k in ('skills', 'agents', 'hooks', 'mcpServers')), 'stub plugin must expose only commands')
        allowed = {'$schema', 'name', 'version', 'description', 'author', 'homepage', 'repository', 'license', 'keywords', 'extensions'}
        require(set(agent) <= allowed, 'Agent Plugins manifest has unsupported fields')
        require(agent.get('$schema') == 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json', 'Agent Plugins schema is missing')
        market = load_json(ROOT / '.claude-plugin/marketplace.json')
        require(market.get('name') == 'ai-host-kit' and len(market.get('plugins', [])) == 1, 'marketplace identity differs')
        repository = re.fullmatch(r'https://github\.com/([\w.-]+/[\w.-]+)', str(claude.get('repository', '')))
        require(repository is not None and agent.get('repository') == claude.get('repository'), 'plugin repository must be one GitHub repository')
        # Users receive a change only when the stable branch carries a higher version.
        stable = {'source': 'github', 'repo': repository.group(1), 'ref': STABLE_BRANCH}
        entry = market['plugins'][0]
        require(entry.get('name') == 'ai-host-kit' and entry.get('source') == stable and 'version' not in entry,
                f'marketplace must install the plugin from {repository.group(1)} at the {STABLE_BRANCH} branch, without its own version')
        versions = read_versions(lambda name: (ROOT / name).read_text())
        version = versions['.claude-plugin/plugin.json']
        require(re.fullmatch(VERSION_RE, version) is not None, 'plugin version is not a version number')
        require(len(set(versions.values())) == 1, 'version markers disagree: ' + ', '.join(f'{k}={v}' for k, v in versions.items()))
        if int(version.split('.')[0]) < 1:
            readme = (ROOT / 'README.md').read_text()
            require(beta_notice(readme), 'README beta notice is required below 1.0')
    check('plugin metadata, versions and required beta notice', metadata)
    def syntax():
        shell = posix_shell()
        print(f'Shell syntax checker: {shell}')
        for name in files:
            p = ROOT / name
            if p.suffix == '.sh' or name == '.githooks/commit-msg':
                subprocess.run([shell, '-n', str(p)], check=True)
            elif p.suffix == '.py':
                compile(p.read_text(), name, 'exec')
            elif p.suffix == '.json':
                load_json(p)
            elif p.suffix in ('.yml', '.yaml'):
                # Ruby is supplied by macOS and the Ubuntu Actions image.
                subprocess.run(['ruby', '-ryaml', '-e', 'YAML.load_file(ARGV[0])', str(p)], check=True, stdout=subprocess.DEVNULL)
        for line in git('ls-files', '-s').decode().splitlines():
            mode, _, name = line.partition('\t')
            if name.endswith('.sh') or name == '.githooks/commit-msg':
                require(mode.startswith('100755 '), f'{name}: save the executable bit in Git')
        for p in (ROOT / '.agents/tests').glob('*.sh'):
            require(p.read_text().splitlines()[1].startswith(f'# {p.name}: '), f'{p.name}: second line must state what it guards')
    check('script and configuration syntax, saved modes and test guard lines', syntax)
    if failures:
        error('validate-kit.sh failed: ' + ', '.join(failures))
    print('validate-kit.sh: all checks passed')


if __name__ == '__main__':
    try:
        action = sys.argv[1] if len(sys.argv) > 1 else ''
        actions = {'build-adapters': build_adapters, 'validate-kit': validate, 'build-release': build_release,
                   'prepare-stable': prepare_stable}
        if action not in actions:
            error('unknown kit tool')
        actions[action](sys.argv[2:])
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        sys.exit(1)
