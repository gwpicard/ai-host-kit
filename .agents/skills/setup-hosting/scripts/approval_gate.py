"""Summarise, record terminal approval and apply the exact approved plan bytes."""
import argparse
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import termios
from types import SimpleNamespace

sys.dont_write_bytecode = True
RESOURCES = Path(__file__).resolve().parents[1] / 'resources'
sys.path.insert(0, str(RESOURCES))
import record_validation as records
records.ROOT = RESOURCES

VERSION = '1.13.2'
HEADINGS = {
    'changes': 'What will be destroyed, created or changed',
    'internet': 'What will become reachable from the internet',
    'access': 'What changes who can get in',
    'irreversible': 'What cannot be undone',
}
KEY_WARNING = 'A lost passphrase means the state cannot be read. Keep it in your password manager; the kit keeps no copy.'
KNOWN_TYPES = {'terraform_data', 'hcloud_firewall', 'hcloud_server', 'hcloud_ssh_key',
               'hcloud_volume', 'aws_security_group', 'aws_security_group_rule',
               'aws_vpc_security_group_ingress_rule', 'aws_s3_bucket',
               'aws_s3_bucket_acl', 'aws_s3_bucket_public_access_block',
               'aws_iam_user', 'aws_iam_role', 'aws_iam_policy', 'aws_key_pair',
               'aws_eip', 'aws_ebs_volume', 'azurerm_network_security_rule',
               'azurerm_public_ip', 'azuread_application', 'azuread_service_principal'}
ACTIONS = {('create',): 'Create', ('update',): 'Change', ('delete',): 'Destroy',
           ('delete', 'create'): 'Destroy and replace',
           ('create', 'delete'): 'Replace and destroy the old resource',
           ('read',): 'Read', ('no-op',): 'Keep', ('forget',): 'Stop managing',
           ('create', 'forget'): 'Create and stop managing the old resource'}
NETWORK = re.compile(r'port|ingress|egress|firewall|security_group|cidr|source|public|acl|network|internet|ipv4_address|ipv6_address|(?:^|\.)protocol$|ip_protocol')
ACCESS = re.compile(r'key|user|role|policy|permission|member|principal|identity|application|directory|registration|firewall|security_group|source|cidr|ingress|acl')
PORTS = {'port', 'ports', 'from_port', 'to_port', 'source_port_range',
         'source_port_ranges', 'destination_port_range', 'destination_port_ranges'}
SOURCES = {'source_ips', 'destination_ips', 'cidr_blocks', 'ipv6_cidr_blocks',
           'cidr_ipv4', 'cidr_ipv6', 'source_address_prefix', 'source_address_prefixes',
           'public_ip', 'public_ip_address', 'public_ipv4', 'public_ipv6',
           'public_ipv4_address', 'public_ipv6_address', 'public_ips', 'public_ip_addresses',
           'ip_address', 'ipv4_address', 'ipv6_address'}


def refuse(message):
    raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def short_hash(sha):
    return '-'.join(sha[n:n+4] for n in (0, 4, 8))


def label(value):
    # Instance keys can be secrets; keep the surrounding module and resource names.
    if not isinstance(value, str):
        return '<name withheld>'
    value = re.sub(r'\["(?:[^"\\]|\\.)*"\]', '[instance name withheld]', value)
    if len(value) > 200 or list(records.secret_fields(value)):
        return '<name withheld>'
    identifier = r'[a-zA-Z_][a-zA-Z0-9_-]*'
    index = r'(?:\[(?:[0-9]+|instance name withheld)\])?'
    if re.fullmatch(identifier + index + r'(?:\.' + identifier + index + r')*', value):
        return value
    return '<name withheld>'


def child(mask, key):
    if mask is True:
        return True
    if isinstance(mask, dict):
        return mask.get(key, False)
    if isinstance(mask, list) and isinstance(key, int) and key < len(mask):
        return mask[key]
    return False


def leaves(before, after, sensitive_before=False, sensitive_after=False, unknown=False, path=()):
    if sensitive_before is True or sensitive_after is True or unknown is True:
        yield path, before, after, True
        return
    objects = [x for x in (before, after, sensitive_before, sensitive_after, unknown) if isinstance(x, dict)]
    arrays = [x for x in (before, after, sensitive_before, sensitive_after, unknown) if isinstance(x, list)]
    if before != after and any(isinstance(x, (dict, list)) and not x for x in (before, after)):
        yield path, before, after, False
    if objects:
        for key in sorted(set().union(*(x.keys() for x in objects))):
            yield from leaves(before.get(key) if isinstance(before, dict) else None,
                              after.get(key) if isinstance(after, dict) else None,
                              child(sensitive_before, key), child(sensitive_after, key),
                              child(unknown, key), path + (key,))
    elif arrays:
        for key in range(max(map(len, arrays))):
            yield from leaves(before[key] if isinstance(before, list) and key < len(before) else None,
                              after[key] if isinstance(after, list) and key < len(after) else None,
                              child(sensitive_before, key), child(sensitive_after, key),
                              child(unknown, key), path + (key,))
    else:
        yield path, before, after, False


def display_value(value, path, protected):
    if protected:
        return 'withheld (sensitive or unknown)'
    name = next((x for x in reversed(path) if isinstance(x, str)), '')
    # Only narrow network primitives may be shown. All free text stays withheld.
    if name in PORTS:
        if type(value) is int and -1 <= value <= 65535:
            return 'all protocols and all ports' if value == 0 else ('all ports' if value == -1 else str(value))
        if isinstance(value, str) and re.fullmatch(r'\d{1,5}(?:[-:]\d{1,5})?', value):
            if all(int(x) <= 65535 for x in re.split('[-:]', value)):
                return 'all protocols and all ports' if value == '0' else value
        if value in ('*', 'any'):
            return 'all ports'
    if name in SOURCES and isinstance(value, str):
        if value in ('*', 'any', 'Internet', '0.0.0.0/0', '::/0'):
            return 'all sources (' + value + ')'
        try:
            return str(ipaddress.ip_network(value, strict=False) if '/' in value else ipaddress.ip_address(value))
        except ValueError:
            pass
    if name in {'protocol', 'ip_protocol'} and value in ('tcp', 'udp', 'icmp', 'icmpv6', 'all', '-1', '*', -1):
        return 'all protocols and all ports' if value in ('all', '-1', '*', -1) else value
    if name in {'direction', 'access'} and value in ('in', 'out', 'Allow', 'Deny'):
        return value
    if name == 'acl' and value in ('private', 'public-read', 'public-read-write', 'authenticated-read'):
        return value
    if (name.startswith('public_') or name in {'block_public_acls', 'ignore_public_acls',
            'block_public_policy', 'restrict_public_buckets', 'associate_public_ip_address'}) and type(value) is bool:
        return 'enabled' if value else 'disabled'
    return 'not set' if value is None else 'value withheld'


def summarise(plan):
    if not isinstance(plan, dict) or plan.get('format_version') != '1.2' or plan.get('errored') is True:
        refuse('The plan JSON format is unsupported or the plan failed. Save a complete plan with the pinned OpenTofu version.')
    changes = plan.get('resource_changes', [])
    if not isinstance(changes, list):
        refuse('The plan changes are malformed. Save a new plan and review it.')
    result = {key: [] for key in HEADINGS}
    def order(resource):
        actions = resource.get('change', {}).get('actions', [])
        return (0 if 'delete' in actions else 1, label(resource.get('address')))
    if any(not isinstance(x, dict) or not isinstance(x.get('change'), dict) for x in changes):
        refuse('A resource change is malformed. Save a new plan and review it.')
    for index, resource in enumerate(sorted(changes, key=order), 1):
        change = resource['change']
        actions = change.get('actions')
        if not isinstance(actions, list) or not all(isinstance(x, str) for x in actions):
            refuse('A resource action is malformed. Save a new plan and review it.')
        name = label(resource.get('address'))
        if 'withheld' in name:
            name += f' (resource {index})'
        kind = resource.get('type', '')
        unknown_action = 'Destroy as part of an unrecognised change' if 'delete' in actions else 'Unrecognised change; review its effect before approving'
        verb = ACTIONS.get(tuple(actions), unknown_action)
        result['changes'].append(f'{verb}: {name}.')
        unrecognised = kind not in KNOWN_TYPES or tuple(actions) not in ACTIONS
        if kind not in KNOWN_TYPES:
            result['changes'].append(f'Unrecognised resource type {label(kind)}: {name}; its effects need review.')
        if change.get('importing') is not None or resource.get('previous_address'):
            result['changes'].append(f'{name}: import or address move; review the ownership change.')
        if 'delete' in actions:
            result['irreversible'].append(f'{name}: destruction can lose data, including any stored volumes or bucket contents. Recovery needs a separate tested backup.')
        if actions != ['no-op'] and isinstance(kind, str) and re.search(r'bucket|volume|disk|database|db_instance', kind):
            result['irreversible'].append(f'{name}: storage changes may lose data. Confirm retention and a tested backup before approval.')
        if 'forget' in actions or unrecognised:
            result['irreversible'].append(f'{name}: the kit cannot establish what can be recovered from this change.')
        if actions == ['no-op'] and not change.get('importing') and not resource.get('previous_address'):
            continue
        if unrecognised:
            result['internet'].append(f'{name}: internet exposure is not established for this resource or change; review it.')
            result['access'].append(f'{name}: who can get in is not established for this resource or change; review it.')
        if isinstance(kind, str) and NETWORK.search(kind):
            result['internet'].append(f'{name}: network or public-access change; check the ports, addresses and source ranges below.')
        if isinstance(kind, str) and ACCESS.search(kind):
            result['access'].append(f'{name}: access, identity or directory registration changes; check who gains or loses access.')
        for path, before, after, protected in leaves(change.get('before'), change.get('after'),
                change.get('before_sensitive'), change.get('after_sensitive'), change.get('after_unknown')):
            safe_path = tuple('<name withheld>' if isinstance(key, str) and
                              (protected and i == len(path) - 1 and len(path) > 1)
                              else key for i, key in enumerate(path))
            field = records.field_path(safe_path)
            # Include unchanged rule fields too: a source-only change can open an existing port.
            line = f'{name}: {field}: {display_value(before, path, protected)} -> {display_value(after, path, protected)}.'
            if not protected and any(isinstance(x, (dict, list)) and not x for x in (before, after)) and before != after:
                line = f'{name}: {field}: structural change (empty container added, removed or changed); values withheld.'
            result['changes'].append(line)
            match_path = '.'.join(x for x in path if isinstance(x, str))
            if NETWORK.search(match_path):
                result['internet'].append(line + ' Treat new or wider sources as possible internet access; unknown sources need review.')
            if ACCESS.search(match_path):
                result['access'].append(line)
    for name, change in plan.get('output_changes', {}).items():
        action = {('create',): 'created', ('update',): 'changed', ('delete',): 'removed',
                  ('no-op',): 'unchanged'}.get(tuple(change.get('actions', [])), 'has an unrecognised change')
        result['changes'].append(f'Output {label(name)}: {action}; value withheld; output changes do not create resources.')
    for key, prefix in (('resource_drift', 'Observed drift'), ('deferred_changes', 'Deferred change')):
        for item in plan.get(key, []):
            resource = item.get('resource_change', item)
            nested = summarise({'format_version': '1.2', 'resource_changes': [resource]})
            for section in result:
                result[section].extend(prefix + ': ' + line for line in nested[section]
                                       if line != KEY_WARNING and not line.startswith('No changes identified'))
    # Do not silently accept future top-level effects.
    known = {'format_version', 'terraform_version', 'variables', 'planned_values', 'prior_state',
             'resource_changes', 'output_changes', 'configuration', 'timestamp', 'checks',
             'errored', 'applyable', 'complete', 'relevant_attributes', 'resource_drift', 'deferred_changes'}
    for name in sorted(set(plan) - known):
        result['changes'].append(f'Unrecognised plan field {label(name)}: value withheld; review its effect.')
    result['irreversible'].append(KEY_WARNING)
    for key in result:
        if not result[key]:
            result[key].append('No changes identified in this section. This is not a check of the live host.')
    return result


def render(sha, summary, target=None):
    lines = [f'Plan SHA-256: {sha}', f'Read-back checksum: {short_hash(sha)}']
    if target is not None:
        lines.extend(['Target project: ' + target['project_root'],
                      'Project SHA-256: ' + target['project_sha256'],
                      'Configuration SHA-256: ' + target['configuration_sha256'],
                      'State target SHA-256: ' + target['state_sha256'],
                      'Workspace: ' + target['workspace']])
    for key, heading in HEADINGS.items():
        lines.extend(['', heading] + ['- ' + line for line in summary[key]])
    return '\n'.join(lines) + '\n'


def environment():
    # Raw OpenTofu logs can contain secrets, even when the command fails.
    return {key: value for key, value in os.environ.items()
            if not key.startswith(('TF_LOG', 'TF_CLI_ARGS', 'TOFU_LOG'))}


def tofu(*args):
    try:
        return subprocess.run(['tofu', *map(str, args)], env=environment(), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError:
        refuse('OpenTofu could not start. Install the pinned version and try again.')


def target_identity():
    # Hash configuration and backend metadata without rendering their contents.
    # The absolute root binds even the first plan, before a state lineage exists.
    root = Path.cwd().resolve()
    configuration = [(p.name, digest(p.read_bytes())) for p in sorted(root.iterdir())
                     if p.is_file() and p.name.endswith(('.tf', '.tf.json'))]
    data_dir = Path(os.environ.get('TF_DATA_DIR', '.terraform')).resolve()
    metadata = data_dir / 'terraform.tfstate'
    backend = digest(metadata.read_bytes()) if metadata.exists() else 'default local backend'
    selected = tofu('workspace', 'show')
    if selected.returncode:
        refuse('The target workspace could not be read. Initialise the configuration and review the plan again. Raw diagnostics are withheld.')
    workspace = selected.stdout.decode().strip()
    if not workspace:
        refuse('The target workspace is empty. Select a workspace and review the plan again.')
    configuration_sha = digest(json.dumps(configuration).encode())
    state_sha = digest(json.dumps([str(root), str(data_dir), backend, workspace, configuration_sha]).encode())
    root_text = str(root)
    if list(records.secret_fields(root_text)) or any(ord(c) < 32 for c in root_text) or re.search(r'[@?#%\\]', root_text):
        root_text = '<project path withheld>'
    return dict(project_root=root_text, project_sha256=digest(str(root).encode()),
                configuration_sha256=configuration_sha, state_sha256=state_sha,
                workspace=label(workspace))


def match_target(record, target):
    if record['target'] != target:
        refuse('The target project, configuration or state workspace differs from the approval. Return to the approved project or save a new plan and approve its target.')


@contextmanager
def saved_plan(path):
    data = Path(path).read_bytes()
    # Refuse plaintext saved plans. OpenTofu verifies and decrypts the envelope later.
    try:
        envelope = json.loads(data)
    except (ValueError, UnicodeError):
        envelope = {}
    if not isinstance(envelope, dict) or envelope.get('encryption_version') != 'v0' or not envelope.get('encrypted_data'):
        refuse('The saved plan is not encrypted. Include the encryption fragment and save a new plan.')
    sha = digest(data)
    with tempfile.TemporaryDirectory(prefix='ai-host-kit-approved-') as directory:
        snapshot = Path(directory) / 'approved.plan'
        snapshot.write_bytes(data)
        snapshot.chmod(0o400)
        yield snapshot, sha


def read_plan(snapshot, require_complete=True):
    version = tofu('version', '-json')
    if version.returncode or json.loads(version.stdout).get('terraform_version') != VERSION:
        refuse('The OpenTofu version differs from the pin. Install OpenTofu ' + VERSION + ' and save a new plan.')
    shown = tofu('show', '-json', snapshot)
    if shown.returncode:
        refuse('OpenTofu could not read the saved plan. Check the encryption passphrase and configuration, then save and review a new plan. Raw diagnostics are withheld.')
    plan = json.loads(shown.stdout)
    summary = summarise(plan)
    if require_complete and (plan.get('deferred_changes') or plan.get('complete') is False):
        refuse('The plan is incomplete or has deferred changes. Resolve them, save a complete plan and review it before approval.')
    return summary


def validate_record(path):
    # The reader prints only field paths, but keep the command refusal concise.
    with redirect_stdout(io.StringIO()):
        status = records.validate('approval-record', path)
    if status:
        refuse('The approval record is malformed or contains unsafe text. Run approve again from your terminal after reviewing the summary.')
    return records.read_json(path)


def match_record(record, sha, summary):
    if record['plan_sha256'] != sha:
        refuse('The plan checksum differs from the approval. Review the current plan and run approve again.')
    if record['confirmation'] != 'approve ' + short_hash(sha):
        refuse('The checksum confirmation does not match. Review the plan and run approve again.')
    if record['summary'] != summary:
        refuse('The summary differs from the approval record. Review the current summary and run approve again.')


def unchanged(path, sha):
    if digest(Path(path).read_bytes()) != sha:
        refuse('The plan changed during this command. Review the new plan and run approve again.')


@contextmanager
def terminal():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        refuse('Approval needs your terminal. Run approve yourself without a pipe or redirected input or output.')
    try:
        reader = open('/dev/tty', 'r')
        writer = open('/dev/tty', 'w')
    except OSError:
        refuse('Approval needs a controlling terminal. Run approve yourself in your terminal.')
    with reader, writer:
        tty = SimpleNamespace(readline=reader.readline, write=writer.write,
                              flush=writer.flush, fileno=reader.fileno)
        if os.tcgetpgrp(tty.fileno()) != os.getpgrp():
            refuse('Approval must run in the foreground of your terminal. Run approve yourself again.')
        yield tty


def typed(tty, prompt):
    # Do not echo words that might accidentally contain a secret.
    old = termios.tcgetattr(tty.fileno())
    new = old.copy()
    new[3] &= ~termios.ECHO
    termios.tcsetattr(tty.fileno(), termios.TCSANOW, new)
    tty.write(prompt)
    tty.flush()
    try:
        answer = tty.readline(502).rstrip('\r\n')
    finally:
        termios.tcsetattr(tty.fileno(), termios.TCSANOW, old)
        tty.write('\n')
        tty.flush()
    return answer


def approve(path, destination):
    with terminal() as tty, saved_plan(path) as (snapshot, sha):
        summary = read_plan(snapshot)
        target = target_identity()
        tty.write(render(sha, summary, target))
        tty.flush()
        # Discard pre-fed terminal input: confirmation follows the displayed summary.
        termios.tcflush(tty.fileno(), termios.TCIFLUSH)
        confirmation = typed(tty, 'Type approve followed by the read-back checksum: ')
        if confirmation != 'approve ' + short_hash(sha):
            refuse('The typed checksum does not match. Read the summary and run approve again.')
        words = typed(tty, 'In your own words, what do you approve? Input is hidden: ')
        record = dict(schema_version='1.0', plan_sha256=sha,
                      approved_at=datetime.now(timezone.utc).isoformat(), words=words,
                      confirmation=confirmation, method='terminal-checksum', summary=summary, target=target)
        # Validate before creating the requested file. Temporary record contains only
        # the redacted summary and words; reject unsafe words before writing anything.
        loaded = records.dependencies()
        if loaded is None:
            refuse('Install the bundled schema requirements before recording approval.')
        validator, formats = loaded
        schema = records.read_json(RESOURCES / 'contracts/approval-record.schema.json')
        if list(validator(schema, format_checker=formats).iter_errors(record)) or list(records.secret_fields(record)):
            refuse('The approval text is empty, malformed or may contain a secret. Run approve again using plain words without secrets or signed links.')
        match_target(record, target_identity())
        unchanged(path, sha)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump(record, output, indent=2)
            output.write('\n')
        print('Approval recorded for checksum ' + short_hash(sha) + '.')


def apply(path, record_path):
    if not Path(record_path).is_file():
        refuse('No approval record exists. Review the plan and run approve yourself from your terminal.')
    record = validate_record(record_path)
    target = target_identity()
    match_target(record, target)
    with saved_plan(path) as (snapshot, sha):
        summary = read_plan(snapshot)
        match_record(record, sha, summary)
        unchanged(path, sha)
        if digest(snapshot.read_bytes()) != sha:
            refuse('The private plan copy changed. Save a new plan, review it and run approve again.')
        match_target(record, target_identity())
        applied = tofu('apply', snapshot)
        if applied.returncode:
            refuse('OpenTofu could not apply the approved plan. Check the state privately and save a fresh plan before approving again. Raw diagnostics are withheld.')
        print('Applied the exact approved plan. Raw output is withheld to protect values.')


class Arguments(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Use summary <plan>, or approve/apply <plan> <record>. Unexpected argument values are withheld.\n')


def main():
    parser = Arguments(description=__doc__)
    parser.add_argument('command', choices=('summary', 'approve', 'apply'))
    parser.add_argument('plan')
    parser.add_argument('record', nargs='?')
    args = parser.parse_args()
    try:
        if args.command == 'summary':
            if args.record:
                refuse('Summary accepts only a saved plan path.')
            with saved_plan(args.plan) as (snapshot, sha):
                summary = read_plan(snapshot, require_complete=False)
                unchanged(args.plan, sha)
                print(render(sha, summary, target_identity()), end='')
        elif not args.record:
            refuse('Supply the approval record path after the saved plan path.')
        elif args.command == 'approve':
            approve(args.plan, args.record)
        else:
            apply(args.plan, args.record)
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, termios.error):
        print('Refused: a plan, record or terminal could not be read, or the destination already exists. Check the paths and configuration, then review the plan and run approve with a new record path. Values are withheld.', file=sys.stderr)
        return 1
    except ValueError as exc:
        print('Refused: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
