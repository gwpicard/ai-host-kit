#!/usr/bin/env sh
# place-retirement.sh: guard that a completed retirement lets a new create start cleanly and an applied place refuses one.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/place_retirement_checks.py" "$@"
