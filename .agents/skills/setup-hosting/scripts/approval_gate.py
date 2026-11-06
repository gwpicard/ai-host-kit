"""Save a plan with its identity, summarise it, record approval and apply its bytes."""
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
S3_CREDENTIALS = None
S3_REDIRECT_ENV = {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy','SSL_CERT_FILE','SSL_CERT_DIR'}
S3_ENDPOINTS = {f'https://{region}.your-objectstorage.com': region for region in ('fsn1', 'nbg1', 'hel1')}
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
NETWORK = re.compile(r'ip|address|cidr|range|source|port|protocol|public|nat|ingress|egress|firewall|security_group|acl|network|internet', re.IGNORECASE)
ACCESS = re.compile(r'key|user|role|policy|permission|member|principal|identity|application|directory|registration|firewall|security_group|source|cidr|ingress|acl')
PORTS = {'port', 'ports', 'from_port', 'to_port', 'source_port_range',
         'source_port_ranges', 'destination_port_range', 'destination_port_ranges'}
SOURCES = {'source_ips', 'destination_ips', 'cidr_blocks', 'ipv6_cidr_blocks',
           'cidr_ipv4', 'cidr_ipv6', 'source_address_prefix', 'source_address_prefixes',
           'public_ip', 'public_ip_address', 'public_ipv4', 'public_ipv6',
           'public_ipv4_address', 'public_ipv6_address', 'public_ips', 'public_ip_addresses',
           'ip_address', 'ipv4_address', 'ipv6_address', 'ipv6_addresses',
           'address', 'nat_ip', 'external_ipv6', 'source_ranges'}


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
    if len(value) > 200 or list(records.secret_fields(value, field_name=True)):
        return '<name withheld>'
    identifier = r'[a-zA-Z_][a-zA-Z0-9_-]*'
    index = r'(?:\[(?:[0-9]+|instance name withheld)\])?'
    if re.fullmatch(identifier + index + r'(?:\.' + identifier + index + r')*', value):
        return value
    return '<name withheld>'


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
                              sensitive_before.get(key, False) if isinstance(sensitive_before, dict) else False,
                              sensitive_after.get(key, False) if isinstance(sensitive_after, dict) else False,
                              unknown.get(key, False) if isinstance(unknown, dict) else False, path + (key,))
    elif arrays:
        for key in range(max(map(len, arrays))):
            yield from leaves(before[key] if isinstance(before, list) and key < len(before) else None,
                              after[key] if isinstance(after, list) and key < len(after) else None,
                              sensitive_before[key] if isinstance(sensitive_before, list) and key < len(sensitive_before) else False,
                              sensitive_after[key] if isinstance(sensitive_after, list) and key < len(sensitive_after) else False,
                              unknown[key] if isinstance(unknown, list) and key < len(unknown) else False, path + (key,))
    else:
        yield path, before, after, False


def all_ports_context(value, path, *masks):
    # Infer port scope only from an unmasked protocol in the same rule.
    field = next((i for i in range(len(path) - 1, -1, -1) if isinstance(path[i], str)), 0)
    for key in path[:field]:
        value = (value.get(key) if isinstance(value, dict) else
                 value[key] if isinstance(value, list) and isinstance(key, int) and key < len(value) else None)
        masks = [(mask.get(key, False) if isinstance(mask, dict) else
                  mask[key] if isinstance(mask, list) and isinstance(key, int) and key < len(mask) else False)
                 for mask in masks]
    if not isinstance(value, dict):
        return False
    for name in ('protocol', 'ip_protocol'):
        if any(mask is True or (isinstance(mask, dict) and mask.get(name)) for mask in masks):
            continue
        protocol = value.get(name)
        if isinstance(protocol, (str, int)) and str(protocol).lower() in ('-1', 'all', '*'):
            return True
    return False


def display_value(value, path, protected, all_ports=False):
    if protected:
        return 'withheld (sensitive or unknown)'
    name = next((x for x in reversed(path) if isinstance(x, str)), '')
    # Only narrow network primitives may be shown. All free text stays withheld.
    if name in PORTS:
        if type(value) is int and -1 <= value <= 65535:
            return 'all ports' if value == 0 and all_ports else ('all ports' if value == -1 else str(value))
        if isinstance(value, str) and re.fullmatch(r'\d{1,5}(?:[-:]\d{1,5})?', value):
            if all(int(x) <= 65535 for x in re.split('[-:]', value)):
                return 'all ports' if value == '0' and all_ports else value
        if value in ('*', 'any'):
            return 'all ports'
    if name in SOURCES and isinstance(value, str):
        if value.lower() in ('*', 'any', 'internet'):
            return 'all sources (' + value + ')'
        try:
            address = ipaddress.ip_network(value, strict=False) if '/' in value else ipaddress.ip_address(value)
            if isinstance(address, (ipaddress.IPv4Network, ipaddress.IPv6Network)) and address.prefixlen == 0:
                return 'all sources (' + str(address) + ')'
            return str(address)
        except ValueError:
            pass
    if name in {'protocol', 'ip_protocol'} and type(value) in (str, int):
        protocol = str(value).lower()
        if protocol in ('all', '-1', '*'):
            return 'all protocols and all ports'
        if protocol in ('tcp', 'udp', 'icmp', 'icmpv6', 'gre', 'esp', 'ah', 'sctp'):
            return protocol
        if re.fullmatch(r'[0-9]{1,3}', protocol) and int(protocol) <= 255:
            return protocol
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
        if (kind == 'hcloud_firewall' and isinstance(change.get('after'), dict)
                and change['after'].get('rule') == []
                and all(mask is not True and not (isinstance(mask, dict) and mask.get('rule'))
                        for mask in (change.get('after_sensitive'), change.get('after_unknown')))):
            result['internet'].append(f'{name}: no public inbound ports are opened by these firewall rules.')
        if isinstance(kind, str) and ACCESS.search(kind):
            result['access'].append(f'{name}: access, identity or directory registration changes; check who gains or loses access.')
        for path, before, after, protected in leaves(change.get('before'), change.get('after'),
                change.get('before_sensitive'), change.get('after_sensitive'), change.get('after_unknown')):
            safe_path = tuple('<name withheld>' if isinstance(key, str) and
                              (protected and i == len(path) - 1 and len(path) > 1)
                              else key for i, key in enumerate(path))
            field = records.field_path(safe_path)
            # Include unchanged rule fields too: a source-only change can open an existing port.
            masks = [change.get(key) for key in ('before_sensitive', 'after_sensitive', 'after_unknown')]
            before_all = all_ports_context(change.get('before'), path, *masks)
            after_all = all_ports_context(change.get('after'), path, *masks)
            line = f'{name}: {field}: {display_value(before, path, protected, before_all)} -> {display_value(after, path, protected, after_all)}.'
            if not protected and any(isinstance(x, (dict, list)) and not x for x in (before, after)) and before != after:
                line = f'{name}: {field}: structural change (empty container added, removed or changed); values withheld.'
            result['changes'].append(line)
            match_path = '.'.join(x for x in path if isinstance(x, str))
            if NETWORK.search(match_path):
                result['internet'].append(line + ' Possibly affects who can reach the tool. Treat new or wider sources as possible internet access; unknown sources need review.')
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
                      'Workspace: ' + target['workspace'],
                      'State storage: ' + target['backend_type']])
        lines.extend(key + ': ' + str(value) for key, value in target['backend_settings'].items())
    for key, heading in HEADINGS.items():
        lines.extend(['', heading] + ['- ' + line for line in summary[key]])
    return '\n'.join(lines) + '\n'


def storage_credentials():
    global S3_CREDENTIALS
    if S3_CREDENTIALS is None:
        with terminal() as tty:
            access = typed(tty, 'Storage access key (hidden): ')
            secret = typed(tty, 'Storage secret key (hidden): ')
        if not access or not secret:
            refuse('Both storage key fields are required. Values are withheld.')
        S3_CREDENTIALS = (access, secret)
    return S3_CREDENTIALS


def s3_settings(settings):
    # Permit only a narrow, explicit Hetzner destination with no credential chain.
    if not isinstance(settings, dict):
        refuse('Backend settings must be an object.')
    fixed = dict(use_path_style=True, skip_credentials_validation=True,
                 skip_region_validation=True, skip_requesting_account_id=True,
                 skip_metadata_api_check=True, skip_s3_checksum=True,
                 shared_credentials_files=['/dev/null'], shared_config_files=['/dev/null'],
                 use_lockfile=True)
    allowed = set(fixed) | {'bucket', 'key', 'region', 'endpoints', 'workspace_key_prefix', 'max_retries'}
    effective = {k: v for k, v in settings.items() if v is not None}
    if set(effective) - allowed or any(effective.get(k) != v for k, v in fixed.items()):
        refuse('Unsupported S3 settings or credential source. Use the documented Hetzner backend fragment.')
    endpoints = effective.get('endpoints', {})
    if not isinstance(endpoints, dict):
        refuse('Backend endpoints must be an object.')
    active = {k: v for k, v in endpoints.items() if v is not None}
    endpoint = active.get('s3')
    if set(active) != {'s3'} or S3_ENDPOINTS.get(endpoint) != effective.get('region'):
        refuse('The S3 endpoint and region must name the same supported Hetzner location.')
    bucket, key = effective.get('bucket'), effective.get('key')
    prefix = effective.get('workspace_key_prefix')
    if (not isinstance(bucket, str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket)
            or not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', key)
            or any(x in ('', '.', '..') for x in key.split('/'))
            or not isinstance(prefix, str) or not re.fullmatch(r'[A-Za-z0-9_/-]+', prefix)
            or any(x in ('', '.', '..') for x in prefix.split('/'))):
        refuse('Set an explicit bucket, safe state key and workspace prefix.')
    return dict(endpoint=endpoint, bucket=bucket, key=key, region=effective['region'], workspace_key_prefix=prefix)


def environment():
    # Raw OpenTofu logs can contain secrets, even when the command fails.
    child = {key: value for key, value in os.environ.items()
             if not key.startswith(('TF_LOG', 'TF_CLI_ARGS', 'TOFU_LOG', 'AWS_'))}
    if S3_CREDENTIALS is not None:
        child.update(AWS_ACCESS_KEY_ID=S3_CREDENTIALS[0], AWS_SECRET_ACCESS_KEY=S3_CREDENTIALS[1],
                     AWS_SHARED_CONFIG_FILE='/dev/null', AWS_SHARED_CREDENTIALS_FILE='/dev/null',
                     AWS_EC2_METADATA_DISABLED='true')
    return child


def tofu(*args):
    try:
        return subprocess.run(['tofu', *map(str, args)], env=environment(), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError:
        refuse('OpenTofu could not start. Install the pinned version and try again.')


def safe_destination(value):
    if list(records.secret_fields(value)) or any(ord(c) < 32 for c in value) or re.search(r'[@?#%\\]', value):
        return '<destination path withheld>'
    return value


def target_identity():
    # Hash configuration and complete backend metadata; show only safe local paths.
    # The absolute root binds even the first plan, before a state lineage exists.
    root = Path.cwd().resolve()
    configuration = [(p.name, str(p.resolve()), digest(p.read_bytes())) for p in sorted(root.iterdir())
                     if p.is_file() and p.name.endswith(('.tf', '.tf.json'))]
    data_dir = Path('.terraform').resolve()
    metadata = (data_dir / 'terraform.tfstate').resolve()
    backend_record = records.read_json(metadata)['backend'] if metadata.exists() else dict(
        type='local', config=dict(path='terraform.tfstate', workspace_dir='terraform.tfstate.d'))
    backend = digest(json.dumps(backend_record, sort_keys=True).encode())
    if backend_record['type'] not in ('local', 's3'):
        refuse('This state backend is not supported. Use local state storage, then save and approve a new plan.')
    redirecting = {key for key in os.environ if
                   (key.startswith('TF_') and not key.startswith(('TF_VAR_', 'TF_LOG'))
                    and key not in ('TF_INPUT', 'TF_IN_AUTOMATION', 'TF_CLI_CONFIG_FILE'))
                   or (backend_record['type'] == 's3' and key in S3_REDIRECT_ENV)
                   or key == 'TOFU_ENCRYPTION' or (key.startswith(('AWS_', 'TOFU_')) and not key.startswith('TOFU_LOG'))}
    if redirecting:
        refuse('A state or workspace override environment variable is set. Unset it, then save and approve a new plan.')
    settings = backend_record['config']
    if backend_record['type'] == 'local' and (not isinstance(settings, dict) or set(settings) - {'path', 'workspace_dir'}
            or not isinstance(settings.get('path'), str) or not settings['path']
            or (settings.get('workspace_dir') is not None and
                (not isinstance(settings['workspace_dir'], str) or not settings['workspace_dir']))):
        refuse('The local backend destination is missing or unsupported. Set an explicit state path, then save and approve a new plan.')
    if backend_record['type'] == 's3':
        backend_settings = s3_settings(settings)
        credentials_sha = digest(json.dumps(storage_credentials()).encode())
    else:
        credentials_sha = ''
        backend_settings = dict(path=str((root / settings['path']).resolve()),
                            workspace_dir=str((root / (settings.get('workspace_dir') or 'terraform.tfstate.d')).resolve()))
    redirecting = {}
    selected = tofu('workspace', 'show')
    if selected.returncode:
        refuse('The target workspace could not be read. Initialise the configuration and review the plan again. Raw diagnostics are withheld.')
    workspace = selected.stdout.decode().strip()
    if not workspace:
        refuse('The target workspace is empty. Select a workspace and review the plan again.')
    state_path = ((root / settings['path'] if workspace == 'default' else
                  root / (settings.get('workspace_dir') or 'terraform.tfstate.d') / workspace / 'terraform.tfstate').resolve()
                  if backend_record['type'] != 's3' else
                  (settings['key'] if workspace == 'default' else settings['workspace_key_prefix'] + '/' + workspace + '/' + settings['key']))
    settings_sha = digest(json.dumps([backend_settings, str(state_path)], sort_keys=True).encode())
    backend_settings = {key: safe_destination(value) for key, value in backend_settings.items()}
    configuration_sha = digest(json.dumps(configuration).encode())
    state_sha = digest(json.dumps([str(root), str(data_dir), backend, settings_sha, workspace, configuration_sha,
                                  str(metadata), credentials_sha]).encode())
    root_text = str(root)
    if list(records.secret_fields(root_text)) or any(ord(c) < 32 for c in root_text) or re.search(r'[@?#%\\]', root_text):
        root_text = '<project path withheld>'
    return dict(project_root=root_text, project_sha256=digest(str(root).encode()),
                configuration_sha256=configuration_sha, state_sha256=state_sha,
                workspace=label(workspace), backend_type=backend_record['type'],
                backend_settings=backend_settings, environment=redirecting)


def identity_path(path):
    return Path(str(path) + '.identity.json')


def check_version():
    version = tofu('version', '-json')
    if version.returncode or json.loads(version.stdout).get('terraform_version') != VERSION:
        refuse('The OpenTofu version differs from the pin. Install OpenTofu ' + VERSION + ' and save a new plan.')


def require_encryption():
    fragment = (RESOURCES / 'encryption.tf').read_bytes()
    if not any(p.is_file() and p.read_bytes() == fragment for p in Path.cwd().glob('*.tf')):
        refuse('The bundled encryption fragment is missing. Include it, then save and approve a new plan.')


def plan(path, destroy=False):
    path = Path(path).resolve()
    record_path = identity_path(path)
    if path.exists() or record_path.exists():
        refuse('The plan or identity record already exists. Choose a new plan path.')
    check_version()
    require_encryption()
    before = target_identity()
    try:
        result = tofu('plan', *(['-destroy'] if destroy else []), '-input=false', '-out', path)
        if result.returncode:
            refuse('OpenTofu could not save the plan. Check the configuration privately, then save and approve a new plan. Raw diagnostics are withheld.')
        after = target_identity()
        if before != after:
            refuse('The target changed during planning. Save and approve a new plan.')
        record = dict(schema_version='1.0', plan_sha256=digest(path.read_bytes()), target=before)
        with os.fdopen(os.open(record_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
            json.dump(record, output, indent=2)
            output.write('\n')
    except (OSError, ValueError, KeyError, TypeError):
        path.unlink(missing_ok=True)
        raise
    print('Saved the plan and its plan-time identity record. Review the summary before approval.')


def planned_identity(path, sha):
    message = 'The plan-time identity record is missing, malformed or does not match this plan or target. Save and approve a new plan.'
    try:
        record_path = identity_path(path)
        with redirect_stdout(io.StringIO()):
            status = records.validate('plan-identity', record_path)
        if status:
            refuse(message)
        record = records.read_json(record_path)
        if record['plan_sha256'] != sha or record['target'] != target_identity():
            refuse(message)
        return record['target']
    except (OSError, ValueError, KeyError, TypeError):
        refuse(message)


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
    check_version()
    require_encryption()
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
        target = planned_identity(path, sha)
        summary = read_plan(snapshot)
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
        match_target(record, planned_identity(path, sha))
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
        match_target(record, planned_identity(path, sha))
        summary = read_plan(snapshot)
        match_record(record, sha, summary)
        unchanged(path, sha)
        if digest(snapshot.read_bytes()) != sha:
            refuse('The private plan copy changed. Save a new plan, review it and run approve again.')
        check_version()
        require_encryption()
        match_target(record, planned_identity(path, sha))
        applied = tofu('apply', snapshot)
        if applied.returncode:
            refuse('OpenTofu could not apply the approved plan. Check the state privately and save a fresh plan before approving again. Raw diagnostics are withheld.')
        print('Applied the exact approved plan. Raw output is withheld to protect values.')


class Arguments(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Use plan/summary <plan>, or approve/apply <plan> <record>. Unexpected argument values are withheld.\n')


def effect_sha(effect):
    if (not isinstance(effect, dict) or effect.get('action') not in ('set-lane', 'register-docktail', 'claim-admin')
            or not isinstance(effect.get('effect'), str) or not effect['effect']
            or not re.fullmatch(r'[0-9a-f]{64}', effect.get('place_sha256', ''))
            or list(records.secret_fields({k:v for k,v in effect.items() if k != 'place_sha256'}))):
        refuse('The effect is missing, unsupported or contains unsafe text. Values are withheld.')
    return digest(json.dumps(effect, sort_keys=True, separators=(',', ':')).encode())


def safe_words(words):
    return (isinstance(words, str) and bool(words.strip()) and len(words) <= 2000
            and not list(records.secret_fields(words)) and not any(ord(c) < 32 for c in words)
            and not re.search(r'[A-Za-z][A-Za-z0-9+.-]*://[^\s]*[@?#%\\\\]', words))


def approve_effect(effect, destination):
    sha = effect_sha(effect)
    with terminal() as tty:
        print(effect['effect'])
        print('Effect checksum: ' + short_hash(sha), flush=True)
        termios.tcflush(tty.fileno(), termios.TCIFLUSH)
        if typed(tty, 'Type approve followed by the checksum: ') != 'approve ' + short_hash(sha):
            refuse('The effect confirmation did not match.')
        words = typed(tty, 'Your words: ')
        if not safe_words(words):
            refuse('Approval words are empty or unsafe. Values are withheld.')
    record = dict(effect_sha256=sha, effect=effect['effect'], words=words,
                  approved_at=datetime.now(timezone.utc).isoformat(), method='foreground-terminal')
    with os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
        json.dump(record, out, indent=2)
        out.write('\n')


def match_effect(effect, path):
    if not Path(path).is_file():
        refuse('No effect approval exists. The person must review and approve this effect.')
    record = records.read_json(path)
    if (set(record) != {'effect_sha256', 'effect', 'words', 'approved_at', 'method'}
            or record['method'] != 'foreground-terminal' or not safe_words(record['words'])
            or record['effect_sha256'] != effect_sha(effect) or record['effect'] != effect['effect']
            or list(records.secret_fields(record['words']))):
        refuse('Effect approval differs or is malformed. Review and approve the current effect.')
    try:
        if datetime.fromisoformat(record['approved_at'].replace('Z', '+00:00')).tzinfo is None:
            refuse('Effect approval must include a timezone.')
    except (TypeError, ValueError):
        refuse('Effect approval time is malformed.')


def main():
    parser = Arguments(description=__doc__)
    parser.add_argument('command', choices=('plan', 'plan-destroy', 'summary', 'approve', 'apply', 'approve-effect'))
    parser.add_argument('plan')
    parser.add_argument('record', nargs='?')
    args = parser.parse_args()
    try:
        if args.command == 'approve-effect':
            if not args.record:
                refuse('Supply a new effect approval path.')
            approve_effect(records.read_json(args.plan), args.record)
        elif args.command in ('plan', 'plan-destroy'):
            if args.record:
                refuse('Plan accepts only a new saved plan path.')
            plan(args.plan, destroy=args.command == 'plan-destroy')
        elif args.command == 'summary':
            if args.record:
                refuse('Summary accepts only a saved plan path.')
            with saved_plan(args.plan) as (snapshot, sha):
                target = planned_identity(args.plan, sha)
                summary = read_plan(snapshot, require_complete=False)
                unchanged(args.plan, sha)
                print(render(sha, summary, target), end='')
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
