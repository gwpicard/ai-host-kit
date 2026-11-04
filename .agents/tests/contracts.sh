#!/usr/bin/env sh
# contracts.sh: reject invalid records by field and distinguish vendor drift from an unavailable source.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/contracts.py"
