#!/usr/bin/env sh
# rehearsal-runner.sh: continue after a failure and distinguish incomplete checks from passes.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/checks.py" rehearsal-runner
