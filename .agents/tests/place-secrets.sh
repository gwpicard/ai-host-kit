#!/usr/bin/env sh
# place-secrets.sh: guard protected inputs, safe terminal pastes and attempt boundaries through Place commands.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
for tool in python3 git tofu; do
  command -v "$tool" >/dev/null 2>&1 || {
    printf 'could-not-run: %s is not on PATH\n' "$tool"
    exit 2
  }
done
exec python3 "$ROOT/.agents/tests/lib/place_secrets_checks.py"
