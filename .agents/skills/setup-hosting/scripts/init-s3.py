"""Initialise reviewed Hetzner S3 backend settings with hidden, memory-only keys."""
import json
import os
from pathlib import Path
import sys
import tempfile
import approval_gate as gate


def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError('Supply a public backend settings JSON file, without credentials.')
        if any(k in gate.S3_REDIRECT_ENV or k.startswith(('AWS_', 'TOFU_')) or (k.startswith('TF_') and not k.startswith(('TF_VAR_', 'TF_LOG'))
               and k not in ('TF_INPUT','TF_IN_AUTOMATION','TF_CLI_CONFIG_FILE')) for k in os.environ):
            raise ValueError('Unset inherited storage and workspace overrides before initialising.')
        settings = gate.records.read_json(sys.argv[1])
        gate.s3_settings(settings)
        gate.require_encryption()
        gate.check_version()
        gate.storage_credentials()
        with tempfile.TemporaryDirectory(prefix='ai-host-kit-backend-') as folder:
            path=Path(folder)/'backend.json'
            path.write_text(json.dumps(settings))
            result=gate.tofu('init','-input=false','-backend-config='+str(path))
        if result.returncode:
            raise ValueError('Initialisation failed. Inspect configuration privately; raw diagnostics are withheld.')
        gate.target_identity()
        print('Initialised the reviewed storage destination. No storage key was saved by the kit.')
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print('Refused: backend settings, tools or terminal input failed. Values are withheld.', file=sys.stderr)
        return 1


if __name__ == '__main__': sys.exit(main())
