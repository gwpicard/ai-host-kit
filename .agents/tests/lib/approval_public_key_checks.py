"""Carry provider-mocked fresh-place summaries through terminal approval and apply."""
import copy
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch


def fresh_place(checks, skill, project, work):
    gate = checks.load(skill)
    fixture = checks.ROOT / '.agents/tests/fixtures/place'
    plan = json.loads((fixture / 'fresh.show.json').read_text())
    expected = json.loads((fixture / 'fresh.summary.json').read_text())
    assert gate.summarise(plan) == expected
    for prefix in ('', 'module.place.'):
        shown = copy.deepcopy(plan)
        for resource in shown['resource_changes']:
            resource['address'] = prefix + resource['address']
        summary = gate.summarise(shown)
        assert prefix + 'hcloud_ssh_key.place: public_key: not set -> value withheld.' in summary['changes']
        destination = work / ('fresh-' + ('root' if prefix else 'module') + '-approval.json')
        destination.unlink(missing_ok=True)
        status, output = checks.terminal_run(skill, project, destination, show_plan=shown)
        assert status == 0 and destination.exists(), 'Fresh-place terminal approval failed: ' + output
        assert not list(gate.records.secret_fields(summary)), 'Fresh-place summary was flagged as secret'
        record = json.loads(destination.read_text())
        assert record['summary'] == summary, 'Approval omitted fresh-place summary lines'
        assert not list(gate.records.secret_fields(record))
        assert checks.capture(lambda: gate.validate_record(destination))[0] is None
        applied = []
        actual = gate.tofu
        def stand_in(*args):
            if args[0] == 'show':
                return subprocess.CompletedProcess(args, 0, json.dumps(shown).encode(), b'')
            if args[0] == 'apply':
                applied.append(Path(args[1]).read_bytes())
                return subprocess.CompletedProcess(args, 0, b'', b'')
            return actual(*args)
        with checks.directory(project), patch.object(gate, 'tofu', side_effect=stand_in):
            error, output = checks.capture(lambda: gate.apply(project / 'first.plan', destination))
        assert not error and applied == [(project / 'first.plan').read_bytes()], 'Fresh-place approval did not reach exact-plan apply'


def assignments(checks, gate, work):
    record = json.loads((checks.ROOT / '.agents/tests/fixtures/contracts/approval-record/valid.json').read_text())
    destination = work / 'assignment-record.json'
    placeholders = ('not set', 'value withheld', 'withheld (sensitive or unknown)')
    assert tuple(gate.display_value(value, ('public_key',), protected)
                 for value, protected in ((None, False), ('synthetic', False), (None, True))) == placeholders
    for before in placeholders:
        for after in placeholders:
            assert not list(gate.records.secret_fields('public_key: ' + before + ' -> ' + after + '.'))
    structural = 'public_key: structural change (empty container added, removed or changed); values withheld.'
    assert not list(gate.records.secret_fields(structural))
    unsafe = ['public_key: ssh-ed25519 AAAA-synthetic-only', 'api_key=abc123',
              'token: abc', 'password=x', 'sig=synthetic-only',
              'key:', 'token: value withheld-extra', 'password=not set synthetic-only',
              'api_key=withheld (sensitive or unknown) synthetic-only',
              'public_key: not set -> ssh-ed25519 AAAA-synthetic-only',
              'public_key: value withheld. Extra synthetic value',
              'public_key: not set -> value withheld. token: abc']
    for text in unsafe:
        for field in ('words', *record['summary']):
            bad = copy.deepcopy(record)
            if field == 'words':
                bad[field] = 'Synthetic approval with ' + text
            else:
                bad['summary'][field] = ['Synthetic resource: ' + text]
            destination.write_text(json.dumps(bad))
            assert list(gate.records.secret_fields(bad)), 'Assignment escaped the shared scanner'
            assert checks.capture(lambda: gate.validate_record(destination))[0], 'Unsafe assignment entered an approval record'


def run_checks(checks, project, work):
    work.mkdir()
    assignments(checks, checks.load(), work)
    fresh_place(checks, checks.SKILL, project, work)
    print('Fresh-place fixture passed schema, secret scan, synthetic terminal approve and stand-in apply, including module.place.public_key.')
    scratch = work / 'mutated-skill'
    shutil.copytree(checks.SKILL, scratch)
    reader = scratch / 'resources/record_validation.py'
    saved = reader.read_text()
    old = 'any(not withheld_assignment(value[match.end():]) for match in assignments)'
    try:
        reader.write_text(checks.mutate_text(saved, old, 'any(True for match in assignments)', 'withheld assignment exception'))
        try:
            fresh_place(checks, scratch, project, work)
        except AssertionError as error:
            assert 'Fresh-place terminal approval failed:' in str(error), str(error)
            assert 'The approval text is empty, malformed or may contain a secret' in str(error), str(error)
            print('Fix removal detected: terminal approve refused the fresh-place summary as possible secret content.')
        else:
            raise AssertionError('Fix removal escaped the fresh-place regression')
    finally:
        reader.write_text(saved)
    fresh_place(checks, scratch, project, work)
    print('Restored fix passed: fresh-place terminal approve and stand-in apply.')
