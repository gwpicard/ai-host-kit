"""Validate record structure without reading a host or printing record values."""
import argparse
from collections import Counter
from datetime import datetime
import ipaddress
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = {
    'plan-identity': 'contracts/plan-identity.schema.json',
    'approval-record': 'contracts/approval-record.schema.json',
    'capabilities': 'contracts/capabilities.schema.json',
    'handover': 'contracts/provisional-ai-build-kit/handover.schema.json',
    'host-record': 'contracts/host-record.schema.json',
    'place-record': 'contracts/place-record.schema.json',
}


def field_path(parts):
    result = ''
    for part in parts:
        if isinstance(part, int):
            result += f'[{part}]'
        else:
            # Unknown keys are input too. Do not print arbitrary strings as field names.
            safe = part if not list(secret_fields(part)) and (part in ('host-tick', 'in-app', '*') or re.fullmatch(r'[a-z][a-z0-9_]{0,47}(?:\.(?:[a-z][a-z0-9_]{0,47}|\*))*', part)) else '<unknown field>'
            result += ('.' if result else '') + safe
    return result or '$'


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(field_path([key]) + ': duplicate field')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('$: expected JSON; non-finite numbers are not allowed')
    try:
        return json.loads(Path(path).read_text(), object_pairs_hook=unique,
                          parse_constant=invalid_constant)
    except (OSError, UnicodeError):
        raise ValueError('$: could not read the JSON file') from None
    except json.JSONDecodeError as exc:
        raise ValueError(f'$: invalid JSON at line {exc.lineno}, column {exc.colno}') from None


def dependencies():
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        print('could not check: install .agents/tools/schema-requirements.txt in the active Python environment')
        return None
    formats = FormatChecker()

    @formats.checks('date-time', raises=ValueError)
    def timestamp(value):
        if not isinstance(value, str):
            return True
        if not re.fullmatch(r'\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)', value):
            return False
        datetime.fromisoformat(value.upper().replace('Z', '+00:00'))
        return True

    @formats.checks('cidr', raises=ValueError)
    def cidr(value):
        if not isinstance(value, str):
            return True
        if '/' not in value:
            return False
        ipaddress.ip_network(value, strict=True)
        return True

    return Draft202012Validator, formats


def error_fields(error):
    path = list(error.absolute_path)
    if error.validator == 'required' and isinstance(error.instance, dict):
        return [(path + [name], 'required field is missing') for name in error.validator_value
                if name not in error.instance]
    if error.validator == 'additionalProperties' and isinstance(error.instance, dict):
        return [(path + [name], 'field is not allowed') for name in error.instance
                if name not in error.schema.get('properties', {})]
    if error.context:
        return [item for child in error.context for item in error_fields(child)]
    reasons = {
        'type': 'has the wrong type', 'enum': 'choose a supported option',
        'const': 'does not meet the required rule', 'pattern': 'has the wrong form',
        'format': 'has the wrong form', 'minimum': 'is below the minimum',
        'exclusiveMinimum': 'must be above the minimum', 'maximum': 'is above the maximum',
        'minLength': 'must not be empty', 'minItems': 'needs at least one entry',
        'uniqueItems': 'must not contain duplicates',
    }
    return [(path, reasons.get(error.validator, 'does not meet the schema rule'))]


def unknown_fields(value, schema, path=()):
    if isinstance(value, dict):
        # Nullable object declarations use anyOf. Their object branch owns the fields.
        for branch in schema.get('anyOf', []):
            if branch.get('type') == 'object':
                yield from unknown_fields(value, branch, path)
                return
        properties = schema.get('properties', {})
        for name, child in value.items():
            current = path + (name,)
            if name not in properties:
                yield current
            elif isinstance(properties[name], dict):
                yield from unknown_fields(child, properties[name], current)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from unknown_fields(child, schema.get('items', {}), path + (index,))


def secret_fields(value, path=()):
    """Find obvious secret content without returning or printing the content."""
    if isinstance(value, dict):
        for name, child in value.items():
            yield from secret_fields(child, path + (name,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from secret_fields(child, path + (index,))
    elif isinstance(value, str):
        if (path == ('plan_sha256',) or (len(path) == 2 and path[0] == 'target' and
                path[1] in {'project_sha256', 'configuration_sha256', 'state_sha256'})) and re.fullmatch(r'[0-9a-f]{64}', value):
            return
        if (len(path) == 3 and path[0] == 'rollback_targets' and
                isinstance(path[1], int) and path[2] == 'image'):
            # The schema checks digest syntax; a digest is public image metadata.
            value = re.sub(r'@sha256:[0-9a-f]{64}$', '', value)
        if re.search(r'(?i)(?:^|[^a-z0-9])(?:key|token|sig|password)\s*[:=]', value) or re.search(r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----', value):
            yield path
            return
        for run in re.findall(r'[A-Za-z0-9+/_=-]{32,}', value):
            entropy = -sum((count / len(run)) * math.log2(count / len(run))
                           for count in Counter(run).values())
            threshold = 3.5 if re.fullmatch(r'[0-9a-fA-F]{40,}', run) else 4.0
            if entropy >= threshold:
                yield path
                return


def validate(kind, path):
    loaded = dependencies()
    if loaded is None:
        return 2
    validator_type, formats = loaded
    value = read_json(path)
    if isinstance(value, dict):
        version = value.get('schema_version')
        if isinstance(version, str) and re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
            if version.split('.')[0] != '1':
                print('schema_version: this major version is not supported. Stop and update AI Host Kit to a version that supports this record.')
                return 1
    schema = read_json(ROOT / SCHEMAS[kind])
    validator_type.check_schema(schema)
    errors = set()
    for error in validator_type(schema, format_checker=formats).iter_errors(value):
        for parts, reason in error_fields(error):
            errors.add((field_path(parts), reason))
    if kind in ('host-record', 'place-record', 'capabilities', 'approval-record', 'plan-identity'):
        for parts in secret_fields(value):
            errors.add((field_path(parts), 'contains possible secret content; use a name or reference'))
    if errors:
        for name, reason in sorted(errors):
            print(f'{name}: {reason}')
        return 1
    if kind == 'handover':
        for parts in unknown_fields(value, schema):
            print(f'{field_path(parts)}: unknown optional field; ignored')
        print('valid: handover matches the provisional draft; upstream agreement is not checked')
    else:
        print(f'valid: {kind} structure; live behaviour is not checked')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=SCHEMAS)
    parser.add_argument('file')
    args = parser.parse_args()
    try:
        return validate(args.kind, args.file)
    except ValueError as exc:
        print(str(exc))
        return 1


if __name__ == '__main__':
    sys.exit(main())
