"""Regressions for target binding and complete, redacted approval summaries."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

# Synthetic input deliberately recognised by the shared scanner.
MAP_KEY = 'ghp_' + '0123456789abcdefghijklmnopqrstuvwxyz'


def summary_cases(checks, gate, case):
    plans = json.loads((checks.FIXTURES / 'review.show.json').read_text())
    summary = gate.summarise(plans[case])
    internet = '\n'.join(summary['internet'])
    changes = '\n'.join(summary['changes'])
    if case == 'public_server':
        assert 'ipv4_address: not set -> 198.51.100.10' in internet
        assert 'ipv6_address: not set -> 2001:db8::10' in internet
        for field in ('public_ip', 'public_ip_address', 'public_ipv4_address', 'public_ipv6_address'):
            plan = copy.deepcopy(plans[case])
            plan['resource_changes'][0]['change']['after'] = {field: '198.51.100.10'}
            assert field + ': not set -> 198.51.100.10' in '\n'.join(gate.summarise(plan)['internet'])
    elif case == 'public_server_unknown':
        for field in ('ipv4_address', 'ipv6_address'):
            assert field + ': withheld (sensitive or unknown)' in internet
    elif case == 'all_protocols':
        assert 'protocol: not set -> all protocols and all ports' in internet
        for field in ('from_port', 'to_port'):
            assert field + ': not set -> all ports' in internet
        for value in ('all', '-1', '*'):
            plan = copy.deepcopy(plans[case])
            plan['resource_changes'][0]['change']['after'] = {'rules': [{'protocol': value}]}
            assert 'protocol: not set -> all protocols and all ports' in '\n'.join(gate.summarise(plan)['internet'])
    elif case == 'wildcard_sources':
        for source in ('*', 'any', 'Internet', '0.0.0.0/0', '::/0'):
            plan = copy.deepcopy(plans[case])
            change = plan['resource_changes'][0]['change']
            change['after']['source_address_prefix'] = source
            for section in ('internet', 'access'):
                text = '\n'.join(gate.summarise(plan)[section])
                assert '10.0.0.0/8 -> all sources (' + source + ')' in text
            for mask in ('after_sensitive', 'after_unknown'):
                masked = copy.deepcopy(plan)
                masked['resource_changes'][0]['change'][mask] = {'source_address_prefix': True}
                text = '\n'.join(gate.summarise(masked)['internet'])
                assert 'all sources' not in text and 'sensitive or unknown' in text
    elif case == 'empty_nested_block':
        assert 'input.synthetic_nested_block: structural change' in changes
        for before, after in ((None, []), ([], None), ({}, {'a': 1}), ({'a': 1}, {}),
                              (None, {'a': [[]]}), ({'a': {}}, None), ({}, [])):
            plan = copy.deepcopy(plans[case])
            plan['resource_changes'][0]['change'].update(before={'input': before}, after={'input': after})
            assert any('input' in line and 'structural change' in line for line in gate.summarise(plan)['changes'])
    elif case in ('output_create', 'output_delete'):
        expected = 'created' if case == 'output_create' else 'removed'
        assert 'Output endpoint: ' + expected + '; value withheld' in changes
        assert 'https://example.invalid' not in changes
        plan = copy.deepcopy(plans[case])
        plan['output_changes']['endpoint']['actions'] = ['update']
        assert 'Output endpoint: changed; value withheld' in '\n'.join(gate.summarise(plan)['changes'])
    return summary


def key_masks(gate):
    assert list(gate.records.secret_fields(MAP_KEY))
    for mask in ('before_sensitive', 'after_sensitive', 'after_unknown'):
        plan = dict(format_version='1.2', resource_changes=[dict(address='terraform_data.map', type='terraform_data',
                    change=dict(actions=['update'], before={'input': {MAP_KEY: 'old'}},
                                after={'input': {MAP_KEY: 'new'}}))])
        assert MAP_KEY not in gate.render('a' * 64, gate.summarise(plan)), 'secret map key appeared in summary'
        change = plan['resource_changes'][0]['change']
        change['after'] = {'input': {'ordinary_private_key': {'hidden_child': 'new'}}}
        change['before'] = None
        change[mask] = {'input': True}
        text = gate.render('a' * 64, gate.summarise(plan))
        assert 'ordinary_private_key' not in text and 'hidden_child' not in text
        change[mask] = {'input': {'ordinary_private_key': True}}
        assert 'ordinary_private_key' not in gate.render('a' * 64, gate.summarise(plan))


def local_project(checks, work, name, source):
    project = work / name
    project.mkdir()
    (project / 'main.tf').write_text(source)
    shutil.copy2(checks.ROOT / 'tofu/encryption.tf', project / 'encryption.tf')
    checks.tofu(project, 'init', '-input=false')
    checks.tofu(project, 'plan', '-out=first.plan', '-input=false')
    return project


def secret_plan(checks, skill, project, work):
    gate = checks.load(skill)
    key_masks(gate)
    cli = [sys.executable, skill / 'scripts/approval_gate.py']
    summary = checks.run(cli + ['summary', 'first.plan'], cwd=project, env=checks.ENV, expected=None)
    assert summary.returncode == 0 and MAP_KEY not in summary.stdout, 'secret map key appeared in command summary'
    record = work / 'secret-approval.json'
    record.unlink(missing_ok=True)
    status, output = checks.terminal_run(skill, project, record)
    assert MAP_KEY not in output, 'secret map key appeared in approval prompt'
    assert status == 0 and record.exists(), 'redacted map plan could not be approved'
    assert MAP_KEY not in record.read_text(), 'secret map key entered record'
    with checks.directory(project):
        actual = gate.tofu
        calls = []
        def observe(*args):
            if args[0] == 'apply':
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, b'', b'')
            return actual(*args)
        with patch.object(gate, 'tofu', side_effect=observe):
            error, output = checks.capture(lambda: gate.apply(project / 'first.plan', record))
        assert not error and len(calls) == 1 and MAP_KEY not in output
    # Refusal paths, including a duplicate record key, must not disclose the key.
    bad = work / 'duplicate-record.json'
    bad.write_text('{' + json.dumps(MAP_KEY) + ':1,' + json.dumps(MAP_KEY) + ':2}')
    refusal = checks.run(cli + ['apply', 'first.plan', bad], cwd=project, env=checks.ENV, expected=None)
    assert refusal.returncode != 0 and MAP_KEY not in refusal.stdout, 'secret key appeared in error'
    status, output = checks.terminal_run(skill, project, work / 'declined.json', wrong=True)
    assert status != 0 and MAP_KEY not in output
    return dict(summary_exit=summary.returncode, approve_status=0, approval_written=True,
                synthetic_secret_in_summary=False, synthetic_secret_in_terminal=False,
                synthetic_secret_in_record=False, synthetic_secret_in_apply=False,
                shared_secret_scanner_recognises_marker=True)


def target_refusal(checks, gate, project, approval):
    identity_path = gate.identity_path(project / 'first.plan')
    saved_identity = identity_path.read_bytes()
    identity = json.loads(saved_identity)
    with checks.directory(project): identity['target'] = gate.target_identity()
    identity_path.write_text(json.dumps(identity))
    actual = gate.tofu
    calls = []
    def observe(*args):
        if args[0] == 'apply':
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, b'', b'')
        return actual(*args)
    with checks.directory(project), patch.object(gate, 'tofu', side_effect=observe):
        error, output = checks.capture(lambda: gate.apply(project / 'first.plan', approval))
    identity_path.write_bytes(saved_identity)
    assert error and 'target' in error and not calls, 'copied approval reached apply in a different target'


def run_regressions(checks, work):
    work.mkdir()
    gate = checks.load()
    results = {}
    cases = ('public_server', 'public_server_unknown', 'all_protocols', 'wildcard_sources',
             'empty_nested_block', 'output_create', 'output_delete')
    for case in cases:
        results[case] = summary_cases(checks, gate, case)
        print('Review regression passed: ' + case)
    project = local_project(checks, work, 'secret-map',
                            'resource "terraform_data" "map" { input = { ' + json.dumps(MAP_KEY) + ' = "ordinary fixture value" } }\n')
    results['secret_map_key'] = secret_plan(checks, checks.SKILL, project, work)
    print('Review regression passed: secret_map_key through summary, approve, record, apply and refusals')
    # Apply the real secret-key plan once; all output remains captured.
    cli = [sys.executable, checks.SKILL / 'scripts/approval_gate.py']
    checks.run(cli + ['apply', 'first.plan', work / 'secret-approval.json'], cwd=project, env=checks.ENV)
    empty = local_project(checks, work, 'empty-container', 'resource "terraform_data" "nested" {}\n')
    checks.tofu(empty, 'apply', 'first.plan')
    (empty / 'main.tf').write_text('resource "terraform_data" "nested" { input = { synthetic_nested_block = {} } }\n')
    checks.tofu(empty, 'plan', '-input=false', '-out=empty.plan')
    shown = json.loads(checks.tofu(empty, 'show', '-json', 'empty.plan').stdout)
    def empty_check(module):
        summary = module.summarise(shown)
        assert any('input.synthetic_nested_block: structural change' in line for line in summary['changes'])
        return summary
    results['real_empty_container'] = empty_check(gate)
    print('Review regression passed: real_empty_container')
    original = local_project(checks, work, 'target', 'resource "terraform_data" "target" { input = "synthetic" }\n')
    approval = work / 'target-approval.json'
    status, output = checks.terminal_run(checks.SKILL, original, approval)
    assert status == 0
    record = json.loads(approval.read_text())
    assert record['target']['project_sha256'] == gate.digest(str(original.resolve()).encode())
    for field in ('project_root', 'project_sha256', 'configuration_sha256', 'state_sha256', 'workspace'):
        assert record['target'][field] in output, 'target identity missing from displayed approval'
    assert 'State storage: local' in output
    for value in record['target']['backend_settings'].values():
        assert value in output, 'recorded state destination missing from approval'
    assert record['target']['project_sha256'] in checks.run(cli + ['summary', 'first.plan'], cwd=original, env=checks.ENV).stdout
    other = work / 'other-target'; shutil.copytree(original, other)
    copied = other / 'copied-approval.json'; shutil.copy2(approval, copied)
    checks.tofu(other, 'init', '-input=false')
    target_refusal(checks, gate, other, copied)
    # Changing root configuration, workspace or backend metadata also invalidates approval.
    with checks.directory(original):
        initial = gate.target_identity()
        config = original / 'main.tf'; saved = config.read_text()
        config.write_text(saved + '\n# synthetic configuration change\n')
        target_refusal(checks, gate, original, approval)
        config.write_text(saved)
        checks.tofu(original, 'workspace', 'new', 'alternate')
        target_refusal(checks, gate, original, approval)
        checks.tofu(original, 'workspace', 'select', 'default')
        assert gate.target_identity() == initial
        config.write_text(saved + '\nterraform {\n  backend "local" {}\n}\n')
        checks.tofu(original, 'init', '-reconfigure', '-input=false', '-backend-config=path=one.tfstate')
        original_plan = (original / 'first.plan').read_bytes()
        original_identity = gate.identity_path(original / 'first.plan').read_bytes()
        checks.tofu(original, 'plan', '-input=false', '-out=first.plan')
        backend_record = checks.record_for(gate, original / 'first.plan')
        backend_approval = work / 'backend-approval.json'; backend_approval.write_text(json.dumps(backend_record))
        checks.tofu(original, 'init', '-reconfigure', '-input=false', '-backend-config=path=two.tfstate')
        target_refusal(checks, gate, original, backend_approval)
        config.write_text(saved)
        (original / 'first.plan').write_bytes(original_plan)
        gate.identity_path(original / 'first.plan').write_bytes(original_identity)
        shutil.rmtree(original / '.terraform')
        checks.tofu(original, 'init', '-input=false')
        assert gate.target_identity() == initial
    runs = []
    for cwd, item in ((other, copied), (original, approval)):
        result = checks.run(cli + ['apply', 'first.plan', item], cwd=cwd, env=checks.ENV, expected=None)
        runs.append(dict(project=cwd.name, returncode=result.returncode, output=result.stdout,
                         state_exists=(cwd / 'terraform.tfstate').exists()))
    assert runs[0]['returncode'] == 1 and not runs[0]['state_exists']
    assert runs[1]['returncode'] == 0 and runs[1]['state_exists']
    results['terminal_approval_reused_in_two_projects'] = dict(terminal_approve_status=status, applies=runs)
    print('Review regression passed: terminal_approval_reused_in_two_projects; copied target refused, original applied')
    scratch = work / 'mutated-skill'; shutil.copytree(checks.SKILL, scratch)
    script = scratch / 'scripts/approval_gate.py'
    reader = scratch / 'resources/record_validation.py'
    # Each removal runs the corresponding outcome assertion and restores the copy.
    mutations = [
        ('secret map keys', reader, 'not list(secret_fields(part, field_name=True)) and ', '',
         lambda module: secret_plan(checks, scratch, project, work)),
        ('protected map keys', script, '(protected and i == len(path) - 1 and len(path) > 1)', 'False', key_masks),
        ('target binding', script, "if record['target'] != target:", 'if False:',
         lambda module: target_refusal(checks, module, other, copied)),
        ('network fields', script, 'if NETWORK.search(match_path):', 'if False:',
         lambda module: summary_cases(checks, module, 'public_server')),
        ('all protocols', script, "if protocol in ('all', '-1', '*'):", 'if False:',
         lambda module: summary_cases(checks, module, 'all_protocols')),
        ('wildcard sources', script, "if value.lower() in ('*', 'any', 'internet'):", 'if False:',
         lambda module: summary_cases(checks, module, 'wildcard_sources')),
        ('empty structures', script, '        yield path, before, after, False\n    if objects:', '        pass\n    if objects:', empty_check),
        ('output actions', script, "Output {label(name)}: {action}; value withheld", "Output {label(name)}: value withheld",
         lambda module: summary_cases(checks, module, 'output_create')),
    ]
    results['protection_removals'] = []
    for name, path, old, new, check in mutations:
        saved = path.read_text()
        mutated = checks.mutate_text(saved, old, new, name)
        try:
            path.write_text(mutated)
            try:
                check(checks.load(scratch))
            except AssertionError:
                print('Protection removal detected: ' + name)
            else:
                raise AssertionError('protection removal escaped regression: ' + name)
        finally:
            path.write_text(saved)
        check(checks.load(scratch))
        results['protection_removals'].append(dict(name=name, detected=True, restored_pass=True))
        print('Restored protection passed: ' + name)
    return results
