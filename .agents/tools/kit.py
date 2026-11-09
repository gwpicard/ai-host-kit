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


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def tracked():
    return [s.decode() for s in git('ls-files', '-z').split(b'\0') if s]


def error(message):
    raise ValueError(message)


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
        if path.is_file() and '.terraform' not in path.parts and path.suffix in ('.json', '.md', '.py', '.sh', '.tf', '.hcl'):
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
    # Parse both manifests before creating the destination.
    manifests = {}
    for name in ('.claude-plugin/plugin.json', 'agent-plugin/plugin.json'):
        manifests[name] = load_json(ROOT / packing[name])
        if not isinstance(manifests[name].get('version'), str):
            error(f'{name}: missing version field')
        manifests[name]['version'] = version[1:]
    output.mkdir(mode=0o755)
    for destination, source in packing.items():
        path = output / destination
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source, path)
    for name, content in manifests.items():
        (output / name).write_text(json.dumps(content, indent=2) + '\n')
    (output / '.ai-host-kit-version').write_text(version + '\n')
    print(f'Built AI Host Kit {version} at {output}')


def beta_notice(readme):
    readme = re.sub(r'<!--.*?(?:-->|\Z)', '', readme, flags=re.S)
    blocks = re.findall(r'^>.*(?:\n>.*)*', readme, re.M)
    for block in blocks:
        words = ' '.join(re.sub(r'^> ?', '', block, flags=re.M).split())
        if all(phrase in words for phrase in ('Beta and experimental.', 'no host is proven yet', 'Do not rely on it')):
            return True
    return False


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                error(f'{path.relative_to(ROOT)}: duplicate JSON key')
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)


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
        require(market['plugins'][0].get('name') == 'ai-host-kit' and market['plugins'][0].get('source') == './', 'marketplace must load the local plugin')
        version = claude.get('version', '')
        require(re.fullmatch(VERSION_RE, version) is not None, 'plugin version is not a version number')
        require(agent.get('version') == version and (ROOT / '.ai-host-kit-version').read_text().strip() == 'v' + version, 'version markers disagree')
        if int(version.split('.')[0]) < 1:
            readme = (ROOT / 'README.md').read_text()
            require(beta_notice(readme), 'README beta notice is required below 1.0')
    check('plugin metadata, versions and required beta notice', metadata)
    def syntax():
        for name in files:
            p = ROOT / name
            if p.suffix == '.sh' or name == '.githooks/commit-msg':
                subprocess.run(['sh', '-n', str(p)], check=True)
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
        actions = {'build-adapters': build_adapters, 'validate-kit': validate, 'build-release': build_release}
        if action not in actions:
            error('unknown kit tool')
        actions[action](sys.argv[2:])
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        sys.exit(1)
