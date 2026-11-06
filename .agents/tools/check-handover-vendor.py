"""Verify the handover copy against the saved AI Build Kit commit pin."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

from record_validation import ROOT, read_json

PIN = 'contracts/ai-build-kit/upstream.json'
VENDORED = ROOT / 'contracts/ai-build-kit/handover.schema.json'
REPOSITORY = 'https://github.com/gwpicard/ai-build-kit.git'


class CouldNotCheck(Exception):
    pass


def git(folder, *args):
    # Ignore caller Git configuration, URL rewrites and repository overrides.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='')
    try:
        return subprocess.run(['git', '-c', 'credential.helper=', '-c', 'core.askPass=', '-C', str(folder), *args], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              check=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        raise CouldNotCheck('the upstream file or pinned commit could not be obtained or confirmed') from None


def saved_pin():
    try:
        saved = git(ROOT, 'show', 'HEAD:' + PIN)
    except CouldNotCheck:
        raise CouldNotCheck('the upstream pin is absent from the saved tree') from None
    try:
        if saved != (ROOT / PIN).read_bytes():
            raise CouldNotCheck('the upstream pin has unsaved changes')
        return json.loads(saved)
    except (OSError, ValueError):
        raise CouldNotCheck('the saved upstream pin could not be read') from None


def confirmed_upstream(pin, *, _test_repository=None):
    """Return confirmed bytes. Only tests may replace transport with a local repo.

    The override is an internal Python argument, never a pin field, CLI option
    or environment variable. The pin always names the allowed upstream repo.
    """
    if pin is None:
        raise CouldNotCheck('no published AI Build Kit schema is pinned')
    fields = {'repository', 'ref', 'commit', 'path', 'blob', 'sha256'}
    if not isinstance(pin, dict) or set(pin) != fields or not all(isinstance(v, str) for v in pin.values()):
        raise CouldNotCheck('the upstream pin is incomplete or has unsupported fields')
    if pin['repository'] != REPOSITORY:
        raise CouldNotCheck('the pin must name the AI Build Kit repository')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', pin['ref']):
        raise CouldNotCheck('the pinned branch ref has the wrong form')
    if not all(re.fullmatch(r'[0-9a-f]{40}', pin[key]) for key in ('commit', 'blob')) or not re.fullmatch(r'[0-9a-f]{64}', pin['sha256']):
        raise CouldNotCheck('the pinned commit, blob or SHA-256 has the wrong form')
    path = PurePosixPath(pin['path'])
    if not pin['path'] or path.is_absolute() or '..' in path.parts or str(path) != pin['path']:
        raise CouldNotCheck('the pinned schema path has the wrong form')
    with tempfile.TemporaryDirectory(prefix='ahk-upstream-') as folder:
        git(folder, 'init', '--bare', '-q')
        git(folder, 'check-ref-format', 'refs/heads/' + pin['ref'])
        repository = REPOSITORY
        protocol = 'https'
        if _test_repository is not None:
            repository = str(Path(_test_repository).resolve())
            protocol = 'file'
        transport = ('-c', 'protocol.allow=never', '-c', f'protocol.{protocol}.allow=always')
        git(folder, *transport, 'fetch', '--no-tags', repository,
            pin['commit'], 'refs/heads/' + pin['ref'] + ':refs/heads/confirmed')
        commit = git(folder, 'rev-parse', pin['commit'] + '^{commit}').decode().strip()
        if commit != pin['commit']:
            raise CouldNotCheck('the pinned commit could not be confirmed')
        try:
            git(folder, 'merge-base', '--is-ancestor', commit, 'refs/heads/confirmed')
        except CouldNotCheck:
            raise CouldNotCheck('the pinned commit is not reachable from the named ref') from None
        target = commit + ':' + pin['path']
        if git(folder, 'cat-file', '-t', target).strip() != b'blob':
            raise CouldNotCheck('the pinned path is not a file')
        blob = git(folder, 'rev-parse', target).decode().strip()
        if blob != pin['blob']:
            raise CouldNotCheck('the upstream file does not match the pinned blob')
        published = git(folder, 'show', target)
    if hashlib.sha256(published).hexdigest() != pin['sha256']:
        raise CouldNotCheck('the upstream file does not match the pinned SHA-256')
    return published


def same_bytes(left, right):
    """Compare bytes without making any claim about their origin."""
    return left == right


def main():
    # No caller-supplied file or pin can establish publication.
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        pin = saved_pin()
        published = confirmed_upstream(pin)
    except CouldNotCheck as exc:
        print('could not check: ' + str(exc))
        return 2
    try:
        vendored = VENDORED.read_bytes()
        schema = read_json(VENDORED)
        if not isinstance(schema, dict) or schema.get('$schema') != 'https://json-schema.org/draft/2020-12/schema' or schema.get('type') != 'object':
            raise ValueError('not a handover schema')
    except (OSError, ValueError):
        print('failed: the vendored copy is missing or is not a JSON Schema object')
        return 1
    if not same_bytes(vendored, published):
        print('failed: the vendored handover schema differs from the confirmed upstream file')
        return 1
    print('passed: the vendored handover schema matches the published copy byte for byte at commit ' + pin['commit'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
