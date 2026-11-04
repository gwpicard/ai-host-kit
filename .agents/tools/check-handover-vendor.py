"""Compare a vendored schema with a local copy from an AI Build Kit release."""
import argparse
from pathlib import Path
import sys

from record_validation import ROOT, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--published', type=Path, help='schema file obtained from an AI Build Kit release')
    parser.add_argument('--vendored', type=Path,
                        default=ROOT / 'contracts/provisional-ai-build-kit/handover.schema.json')
    args = parser.parse_args()
    if args.published is None:
        print('could not check: AI Build Kit has not published a schema for this draft. Supply its published copy with --published when it is available.')
        return 2
    try:
        published = args.published.read_bytes()
    except OSError:
        print('could not check: the published AI Build Kit schema could not be read')
        return 2
    try:
        vendored = args.vendored.read_bytes()
        # Empty files or non-schema JSON must not produce a match.
        for path in (args.published, args.vendored):
            schema = read_json(path)
            if not isinstance(schema, dict) or schema.get('$schema') != 'https://json-schema.org/draft/2020-12/schema' or schema.get('type') != 'object':
                raise ValueError('not a handover schema')
    except (OSError, ValueError):
        print('failed: a schema copy is missing or is not a JSON Schema object')
        return 1
    if vendored != published:
        print('failed: the vendored handover schema differs from the supplied published copy')
        return 1
    print('passed: the vendored handover schema matches the supplied published copy byte for byte')
    return 0


if __name__ == '__main__':
    sys.exit(main())
