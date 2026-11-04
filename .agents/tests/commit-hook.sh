#!/usr/bin/env sh
# commit-hook.sh: remove attribution from an actual commit without deleting ordinary prose.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/checks.py" commit-hook
