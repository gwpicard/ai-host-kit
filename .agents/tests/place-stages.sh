#!/usr/bin/env sh
# place-stages.sh: guard real API reply shapes, delayed readiness and reviewed recovery through setup commands.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/place_stage_checks.py" "$@"
