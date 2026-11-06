#!/usr/bin/env sh
# plan.sh: save a plan with its destination identity.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec python3 "$HERE/approval_gate.py" plan "$@"
