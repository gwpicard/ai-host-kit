#!/usr/bin/env sh
# plan-summary.sh: show the saved plan without exposing values.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec python3 "$HERE/approval_gate.py" summary "$@"
