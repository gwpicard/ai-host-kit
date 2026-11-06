"""Saved destination, conservative network reporting and individual recheck outcomes."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch


def plan(after, kind='terraform_data', **masks):
    return dict(format_version='1.2', resource_changes=[dict(type=kind, address=kind + '.fixture',
                change=dict(actions=['create'], before=None, after=after, **masks))])


def internet(gate, after, kind='terraform_data', **masks):
    return '\n'.join(gate.summarise(plan(after, kind, **masks))['internet'])


def network_checks(gate):
    for kind, field, value in (
        ('azurerm_public_ip', 'ip_address', '198.51.100.10'),
        ('google_compute_address', 'address', '198.51.100.10'),
        ('google_compute_instance', 'nat_ip', '198.51.100.10'),
        ('google_compute_instance', 'external_ipv6', '2001:db8::10'),
        ('aws_instance', 'ipv6_addresses', ['2001:db8::10']),
    ):
        text = internet(gate, {field: value}, kind)
        assert field in text and (value[0] if isinstance(value, list) else value) in text, field
        for mask in ('after_sensitive', 'after_unknown'):
            text = internet(gate, {field: value}, kind, **{mask: {field: True}})
            assert '198.51.100.10' not in text and '2001:db8::10' not in text
            assert field in text and 'sensitive or unknown' in text
    # These names have no special renderer. The conservative rule must still list them.
    for hint in ('ip', 'address', 'cidr', 'range', 'source', 'port', 'protocol', 'public', 'nat', 'ingress'):
        field = 'custom_' + hint + '_setting'
        text = internet(gate, {field: 'synthetic-private-value'})
        assert field in text and 'Possibly affects who can reach the tool' in text, field
        assert 'synthetic-private-value' not in text
    for field in ('protocol', 'ip_protocol'):
        for value, shown in (('Tcp', 'tcp'), ('6', '6'), (6, '6'), ('gre', 'gre')):
            text = internet(gate, {field: value})
            assert field + ': not set -> ' + shown + '.' in text, (field, value)


def wildcard_checks(gate):
    for source in ('0.0.0.0/0', '0.0.0.0/00', '0.0.0.0/0.0.0.0', '192.0.2.1/0',
                   '::/0', '0::0/0', '0000:0000:0000:0000:0000:0000:0000:0000/0'):
        text = internet(gate, {'source_ranges': [source, '10.0.0.0/8']}, 'google_compute_firewall')
        canonical = '::/0' if ':' in source else '0.0.0.0/0'
        assert 'all sources (' + canonical + ')' in text and '10.0.0.0/8' in text, source
        for mask in ('after_sensitive', 'after_unknown'):
            text = internet(gate, {'source_ranges': [source]}, **{mask: {'source_ranges': True}})
            assert 'all sources' not in text and 'sensitive or unknown' in text


def zero_checks(gate):
    for protocol in ('tcp', 'Tcp', '6', 6, None):
        for zero in (0, '0'):
            text = internet(gate, {'protocol': protocol, 'from_port': zero, 'to_port': zero}, 'aws_security_group_rule')
            assert 'from_port: not set -> 0.' in text and 'to_port: not set -> 0.' in text
            assert 'all ports' not in text and 'all protocols' not in text
    for protocol in ('-1', -1, 'all', '*'):
        for field in ('protocol', 'ip_protocol'):
            rule = {field: protocol, 'from_port': 0, 'to_port': 0}
            text = internet(gate, {'rules': [rule]})
            assert field + ': not set -> all protocols and all ports' in text
            assert 'from_port: not set -> all ports' in text and 'to_port: not set -> all ports' in text
            for mask in ('before_sensitive', 'after_sensitive', 'after_unknown'):
                text = internet(gate, {'rules': [rule]}, **{mask: {'rules': [{field: True}]}})
                assert 'all ports' not in text and 'from_port: not set -> 0.' in text
    # Before and after have independent protocol context.
    fixture = plan({'protocol': 'tcp', 'from_port': 0})
    fixture['resource_changes'][0]['change'].update(actions=['update'], before={'protocol': '-1', 'from_port': 0})
    assert 'from_port: all ports -> 0.' in '\n'.join(gate.summarise(fixture)['internet'])


def backend_refusal(checks, skill, project, work):
    gate = checks.load(skill)
    destination = work / 'drift-approval.json'
    destination.unlink(missing_ok=True)
    status, text = checks.terminal_run(skill, project, destination)
    assert status != 0 and not destination.exists() and 'plan-time identity record' in text, 'backend_changed_before_approval was accepted'
    # Forge only the current target on the otherwise valid fixture record. Apply must
    # independently compare the plan-time identity, not trust this approval record.
    forged = json.loads((work / 'original-approval.json').read_text())
    with checks.directory(project):
        forged['target'] = gate.target_identity()
    record = work / 'forged-current-target.json'; record.write_text(json.dumps(forged))
    calls = []
    actual = gate.tofu
    def observe(*args):
        if args[0] == 'apply':
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, b'', b'')
        return actual(*args)
    with checks.directory(project), patch.object(gate, 'tofu', side_effect=observe):
        error, output = checks.capture(lambda: gate.apply(project / 'first.plan', record))
    assert error and 'plan-time identity record' in error and not calls
    assert not (project / 'old.tfstate').exists() and not (project / 'new.tfstate').exists()


def approval_recheck(checks, skill, project, work):
    destination = work / 'race-approval.json'; destination.unlink(missing_ok=True)
    config = project / 'main.tf'; original = config.read_text()
    changed = []
    def change_after_summary():
        changed.append(True)
        config.write_text(original + '\n# synthetic change during terminal confirmation\n')
    try:
        status, text = checks.terminal_run(skill, project, destination, before_words=change_after_summary)
        assert changed and status != 0 and 'target' in text and not destination.exists(), 'post-confirmation target recheck did not refuse'
    finally:
        config.write_text(original)
        destination.unlink(missing_ok=True)


def apply_recheck(checks, gate, project, approval):
    actual_read = gate.read_plan
    actual_tofu = gate.tofu
    config = project / 'main.tf'; original = config.read_text()
    calls = []; changed = []
    def read_then_change(*args, **kwargs):
        result = actual_read(*args, **kwargs)
        config.write_text(original + '\n# synthetic change after reading the saved plan\n')
        changed.append(True)
        return result
    def observe(*args):
        if args[0] == 'apply':
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, b'', b'')
        return actual_tofu(*args)
    try:
        with checks.directory(project), patch.object(gate, 'read_plan', side_effect=read_then_change), patch.object(gate, 'tofu', side_effect=observe):
            error, output = checks.capture(lambda: gate.apply(project / 'first.plan', approval))
        assert changed and error and 'target' in error and not calls, 'final apply target recheck did not refuse'
    finally:
        config.write_text(original)


def harness_errors(checks):
    assert checks.mutate_text('original text', 'original', 'changed', 'valid') == 'changed text'
    try:
        checks.mutate_text('original text', 'deliberately absent replacement text', '', 'missing replacement')
    except checks.MutationHarnessError:
        return
    raise AssertionError('missing replacement was not a harness error')


def run_checks(checks, work):
    work.mkdir()
    gate = checks.load()
    for name, check in [('conservative network vocabulary', network_checks), ('equivalent wildcard sources', wildcard_checks), ('zero port context', zero_checks)]:
        check(gate); print('Destination regression passed: ' + name)
    project = work / 'backend'; project.mkdir()
    (project / 'main.tf').write_text('terraform {\n  backend "local" {}\n}\nresource "terraform_data" "fixture" { input = "synthetic" }\n')
    shutil.copy2(checks.ROOT / 'tofu/encryption.tf', project / 'encryption.tf')
    checks.tofu(project, 'init', '-input=false', '-backend-config=path=old.tfstate')
    checks.tofu(project, 'plan', '-input=false', '-out=first.plan')
    shown = json.loads(checks.tofu(project, 'show', '-json', 'first.plan').stdout)
    assert 'backend' not in shown and 'backend' not in shown['configuration']
    approval = work / 'original-approval.json'
    status, text = checks.terminal_run(checks.SKILL, project, approval); assert status == 0
    checks.tofu(project, 'init', '-reconfigure', '-input=false', '-backend-config=path=new.tfstate')
    backend_refusal(checks, checks.SKILL, project, work)
    print('Destination regression passed: backend_changed_before_approval; approval and apply refused, neither state written')
    checks.tofu(project, 'init', '-reconfigure', '-input=false', '-backend-config=path=old.tfstate')
    checks.tofu(project, 'workspace', 'new', 'alternate')
    backend_refusal(checks, checks.SKILL, project, work)
    checks.tofu(project, 'plan', '-input=false', '-out=workspace.plan')
    assert gate.records.read_json(gate.identity_path(project / 'workspace.plan'))['target']['workspace'] == 'alternate'
    checks.tofu(project, 'workspace', 'select', 'default')
    print('Destination regression passed: workspace_changed_before_approval and saved non-default workspace')
    approval_recheck(checks, checks.SKILL, project, work)
    apply_recheck(checks, gate, project, approval)
    print('Destination regression passed: post-confirmation and final apply target rechecks')
    # Every outcome check above runs before constructing its protection removal.
    scratch = work / 'mutated-skill'; shutil.copytree(checks.SKILL, scratch)
    script = scratch / 'scripts/approval_gate.py'
    checks.tofu(project, 'init', '-reconfigure', '-input=false', '-backend-config=path=new.tfstate')
    mutations = [
        ('plan-time destination comparison', "record['target'] != target_identity()", 'False', lambda module: backend_refusal(checks, scratch, project, work)),
        ('conservative network classification', 'if NETWORK.search(match_path):', 'if False:', network_checks),
        ('equivalent all-address ranges', 'and address.prefixlen == 0:', 'and False:', wildcard_checks),
        ('zero port context', 'if value == 0 and all_ports', 'if value == 0', zero_checks),
        ('ip_protocol classification', "if name in {'protocol', 'ip_protocol'} and type(value)", "if name in {'protocol'} and type(value)", network_checks),
    ]
    def remove(name, old, new, check):
        original = script.read_text()
        mutated = checks.mutate_text(original, old, new, name)
        try:
            script.write_text(mutated)
            try:
                check(checks.load(scratch))
            except AssertionError:
                print('Protection removal detected by outcome assertion: ' + name)
            else:
                raise AssertionError('protection removal escaped outcome assertion: ' + name)
        finally:
            script.write_text(original)
        check(checks.load(scratch))
        print('Restored protection passed: ' + name)
    for mutation in mutations:
        remove(*mutation)
    checks.tofu(project, 'init', '-reconfigure', '-input=false', '-backend-config=path=old.tfstate')
    remove('post-confirmation target recheck', '        match_target(record, planned_identity(path, sha))\n        unchanged(path, sha)', '        unchanged(path, sha)',
           lambda module: approval_recheck(checks, scratch, project, work))
    remove('final apply target recheck', "        check_version()\n        require_encryption()\n        match_target(record, planned_identity(path, sha))\n        applied = tofu('apply', snapshot)", "        applied = tofu('apply', snapshot)",
           lambda module: apply_recheck(checks, module, project, approval))
    harness_errors(checks)
    harness = work / 'mutated_harness.py'
    source = Path(checks.__file__).read_text()
    old = 'if old not in text or old == new:'
    harness.write_text(checks.mutate_text(source, old, 'if False:', 'missing replacement guard'))
    spec = importlib.util.spec_from_file_location('mutated_harness', harness)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    try:
        harness_errors(module)
    except AssertionError:
        print('Protection removal detected by outcome assertion: missing replacement harness error')
    else:
        raise AssertionError('missing replacement guard removal escaped its outcome check')
    finally:
        harness.write_text(source)
    spec.loader.exec_module(module)
    harness_errors(module)
    print('Restored protection passed: missing replacement harness error')
    cli = [sys.executable, checks.SKILL / 'scripts/approval_gate.py']
    checks.run(cli + ['apply', 'first.plan', approval], cwd=project, env=checks.ENV)
    assert (project / 'old.tfstate').exists() and not (project / 'new.tfstate').exists()
    print('Destination regression passed: unchanged backend applied to old.tfstate')
