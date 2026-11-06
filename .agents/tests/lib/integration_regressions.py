"""Check withheld field names and controlled failures for malformed vendor pins."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from checks import ROOT, run, snapshot


def load(path):
    sys.modules.pop('record_validation', None)
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RENDERERS = ('canonical', 'host-fit', 'setup-hosting', 'host-fit-report', 'approval-gate')


def name_checks(renderer, work):
    skills = ROOT / '.agents/skills'
    fixtures = ROOT / '.agents/tests/fixtures/contracts'
    readers = {
        'canonical': ROOT / '.agents/tools/record_validation.py',
        'host-fit': skills / 'host-fit/resources/record_validation.py',
        'setup-hosting': skills / 'setup-hosting/resources/record_validation.py',
    }
    if renderer in readers:
        module = load(readers[renderer])
        module.ROOT = ROOT if renderer == 'canonical' else readers[renderer].parent
    elif renderer == 'host-fit-report':
        module = load(skills / 'host-fit/scripts/host_fit.py')
    else:
        module = load(skills / 'setup-hosting/scripts/approval_gate.py')
    markers = ('AKIA' + 'X' * 16, 'ASIA' + 'X' * 16,
               'gh' + 'p_' + 'X' * 20, 'github_' + 'pat_' + 'X' * 20,
               'sk' + '-' + 'X' * 20)
    for marker in markers:
        if renderer in readers:
            assert marker not in module.field_path(('tool', marker)), 'field name was disclosed'
            # The published handover probe and Host Kit's closed records must
            # still fail; the renderer must withhold the offending name.
            kind = 'approval-record' if renderer == 'setup-hosting' else 'handover'
            value = json.loads((fixtures / kind / 'valid.json').read_text())
            if kind == 'handover':
                value['tool'][marker] = 'synthetic'
            else:
                value[marker] = 'synthetic'
            sample = work / 'sample.json'
            sample.write_text(json.dumps(value))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = module.validate(kind, sample)
            assert status == 1 and marker not in output.getvalue(), 'validation disclosed a field name'
            # Duplicate-field errors also use the same renderer.
            sample.write_text(json.dumps({marker: 1})[:-1] + ',' + json.dumps(marker) + ':2}')
            try:
                module.read_json(sample)
                raise AssertionError('duplicate field was accepted')
            except ValueError as exc:
                assert marker not in str(exc), 'duplicate-field error disclosed a name'
            assert module.field_path(('APP_SETTING', 'a' * 64)) == 'APP_SETTING.' + 'a' * 64
        elif renderer == 'host-fit-report':
            assert marker not in module.need_path(('tool', marker)), 'fit path disclosed a name'
            value = json.loads((fixtures / 'handover/valid.json').read_text())
            value['tool'][marker] = 'synthetic'
            try:
                module.checked('handover', value)
                raise AssertionError('invalid handover was accepted')
            except ValueError as exc:
                assert marker not in str(exc), 'host fit disclosed a field name'
        else:
            plan = {'format_version': '1.2', 'terraform_version': '1.13.2',
                    'resource_changes': [{'address': 'terraform_data.fixture',
                    'type': 'terraform_data', 'change': {'actions': ['update'],
                    'before': {marker: 'before'}, 'after': {marker: 'after'}}}]}
            assert marker not in json.dumps(module.summarise(plan)), 'approval summary disclosed a name'
            assert marker not in module.label(marker), 'approval label disclosed a name'
    print('Credential-shaped names withheld: ' + renderer)


def pin_checks():
    vendor = load(ROOT / '.agents/tools/check-handover-vendor.py')
    pin = json.loads((ROOT / vendor.PIN).read_text())
    confirmed = vendor.confirmed_upstream
    for control in ('\u0000', '\n', '\t', '\u001f', '\u007f', '\u0085', '\u009f'):
        candidate = dict(pin, path='hosting/' + control + 'handover.schema.json')
        output = io.StringIO()
        # Invalid paths must be refused before Git receives an argument.
        with patch.object(vendor, 'saved_pin', return_value=candidate), \
             patch.object(vendor, 'git', side_effect=AssertionError('control character reached Git')), \
             patch.object(vendor, 'confirmed_upstream', side_effect=lambda p: confirmed(p, _test_repository=ROOT)), \
             patch.object(sys, 'argv', ['check-handover-vendor.py']), contextlib.redirect_stdout(output):
            status = vendor.main()
        assert status == 2 and 'could not check:' in output.getvalue()
    for error in (ValueError('synthetic argument'), TypeError('synthetic argument'),
                  OSError('synthetic subprocess'), subprocess.SubprocessError('synthetic subprocess')):
        with patch.object(vendor.subprocess, 'run', side_effect=error):
            try:
                vendor.git(ROOT, 'status')
                raise AssertionError('subprocess argument failure escaped translation')
            except vendor.CouldNotCheck:
                pass
        output = io.StringIO()
        with patch.object(vendor, 'saved_pin', return_value=pin), \
             patch.object(vendor, 'confirmed_upstream', side_effect=error), \
             patch.object(sys, 'argv', ['check-handover-vendor.py']), contextlib.redirect_stdout(output):
            assert vendor.main() == 2
        assert 'could not check:' in output.getvalue() and 'synthetic' not in output.getvalue()
    print('Malformed pins and confirmation argument or subprocess failures return could not check with status 2.')


def mutation_checks(work):
    tree = snapshot(work / 'integration-mutations')
    script = tree / '.agents/tests/lib/integration_regressions.py'
    readers = [tree / '.agents/tools/record_validation.py'] + [
        tree / '.agents/skills' / skill / 'resources/record_validation.py'
        for skill in ('host-fit', 'setup-hosting')]
    originals = {p: p.read_text() for p in readers}
    try:
        for path, text in originals.items():
            assert 'if field_name and re.search(' in text
            path.write_text(text.replace('if field_name and re.search(', 'if False and re.search('))
        for renderer in RENDERERS:
            result = run([sys.executable, script, renderer], cwd=tree, expected=1)
            assert 'disclosed' in result.stdout, 'name mutation failed for an unrelated reason'
            print('Mutation caught: provider-name scan removed from ' + renderer)
    finally:
        for path, text in originals.items():
            path.write_text(text)
    for renderer in RENDERERS:
        run([sys.executable, script, renderer], cwd=tree)
    path = tree / '.agents/tools/check-handover-vendor.py'
    original = path.read_text()
    try:
        changed = original.replace("any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in pin['path'])", 'False')
        changed = changed.replace('(OSError, ValueError, TypeError, subprocess.SubprocessError)', '(OSError, subprocess.SubprocessError)')
        assert changed != original
        path.write_text(changed)
        result = run([sys.executable, script, 'pin'], cwd=tree, expected=1)
        assert 'control character reached Git' in result.stdout
        print('Mutation caught: malformed-pin protections removed')
    finally:
        path.write_text(original)
    run([sys.executable, script, 'pin'], cwd=tree)
    print('Both fixes restored and their regression checks passed in the throwaway copy.')


def checks(work):
    for renderer in RENDERERS:
        run([sys.executable, Path(__file__), renderer])
        print('Credential-shaped name regression passed: ' + renderer)
    pin_checks()
    mutation_checks(work)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='ahk-integration-') as folder:
        if sys.argv[1] == 'pin':
            pin_checks()
        else:
            name_checks(sys.argv[1], Path(folder))
