#!/usr/bin/env sh
# approval-gate.sh: bind terminal approval to encrypted saved plans and detect removed protections.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/approval_gate_checks.py"
