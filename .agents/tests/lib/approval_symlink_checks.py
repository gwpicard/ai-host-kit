"""Refuse retargeted symlinks without changing saved plans or identity records."""
import json
from pathlib import Path
import shutil
import sys
import tempfile


def probe(checks, skill, work, case):
    project = Path(tempfile.mkdtemp(prefix=case + '-', dir=work))
    gate = checks.load(skill)
    config = project / 'main.tf'
    config.write_text('terraform {\n  backend "local" {}\n}\nresource "terraform_data" "fixture" { input = "before" }\n')
    shutil.copy2(checks.ROOT / 'tofu/encryption.tf', project / 'encryption.tf')
    checks.tofu(project, 'init', '-input=false', '-backend-config=path=terraform.tfstate')
    if case in ('workspace-folder', 'workspace-file'):
        checks.tofu(project, 'workspace', 'new', 'alternate')
    checks.tofu(project, 'plan', '-input=false', '-out=seed.plan')
    checks.tofu(project, 'apply', 'seed.plan')
    config.write_text(config.read_text().replace('"before"', '"after"'))
    state = (project / 'terraform.tfstate' if case not in ('workspace-folder', 'workspace-file') else
             project / 'terraform.tfstate.d/alternate/terraform.tfstate')
    link = {'workspace-folder': state.parent, 'workspace-file': state,
            'default-file': state, 'configuration': config,
            'metadata': project / '.terraform/terraform.tfstate'}[case]
    old = link.with_name(link.name + '.old')
    new = link.with_name(link.name + '.new')
    link.rename(old)
    if old.is_dir():
        shutil.copytree(old, new)
    else:
        shutil.copy2(old, new)
    # A second link makes resolution through the whole chain part of the probe.
    intermediate = link.with_name(link.name + '.link')
    intermediate.symlink_to(old.name, target_is_directory=old.is_dir())
    link.symlink_to(intermediate.name, target_is_directory=old.is_dir())
    plan = project / 'first.plan'
    with checks.directory(project):
        gate.plan(plan)
    approval = project / 'approval.json'
    status, text = checks.terminal_run(skill, project, approval)
    assert status == 0, text
    original_state = state.read_bytes()
    intermediate.unlink()
    intermediate.symlink_to(new.name, target_is_directory=new.is_dir())
    refused = project / 'refused.json'
    status, text = checks.terminal_run(skill, project, refused)
    assert status != 0 and not refused.exists(), case + ': retargeted symlink accepted at approval'
    assert 'Save and approve a new plan' in text and 'Traceback' not in text, text
    cli = [sys.executable, skill / 'scripts/approval_gate.py', 'apply', plan, approval]
    result = checks.run(cli, cwd=project, env=checks.ENV, expected=None)
    assert result.returncode != 0, case + ': retargeted symlink accepted at apply'
    assert 'differs from the approval' in result.stdout and 'Traceback' not in result.stdout, result.stdout
    assert state.read_bytes() == original_state, case + ': refused apply changed state'
    intermediate.unlink()
    intermediate.symlink_to(old.name, target_is_directory=old.is_dir())
    checks.run(cli, cwd=project, env=checks.ENV)
    shown = json.loads(checks.tofu(project, 'show', '-json').stdout)
    assert shown['values']['root_module']['resources'][0]['values']['input'] == 'after'
    if case in ('workspace-folder', 'workspace-file', 'default-file'):
        redirected = new / 'terraform.tfstate' if new.is_dir() else new
        assert redirected.read_bytes() == original_state, case + ': redirected state changed'
    print('Symlink regression passed: ' + case + '; approval and apply refused, restored target applied')


def run_checks(checks, work):
    work.mkdir()
    for case in ('workspace-folder', 'workspace-file', 'default-file', 'configuration', 'metadata'):
        probe(checks, checks.SKILL, work, case)
    scratch = work / 'mutated-skill'
    shutil.copytree(checks.SKILL, scratch)
    script = scratch / 'scripts/approval_gate.py'
    original = script.read_text()
    try:
        script.write_text(checks.mutate_text(original, '[backend_settings, str(state_path)]',
                                            '[backend_settings]', 'effective workspace state path'))
        try:
            probe(checks, scratch, work, 'workspace-folder')
        except AssertionError as error:
            assert 'retargeted symlink accepted at approval' in str(error), str(error)
            print('Protection removal detected: effective workspace state path; ' + str(error))
        else:
            raise AssertionError('effective workspace state path removal escaped its check')
    finally:
        script.write_text(original)
    probe(checks, scratch, work, 'workspace-folder')
    print('Restored protection passed: effective workspace state path')
