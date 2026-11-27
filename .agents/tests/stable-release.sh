#!/usr/bin/env sh
# stable-release.sh: prepare a stable release offline with every version marker in agreement, never pushing, keeping stable a fast-forward.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/checks.py" stable-release
