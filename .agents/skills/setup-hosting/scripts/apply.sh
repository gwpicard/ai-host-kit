#!/usr/bin/env sh
# apply.sh: apply only the saved bytes covered by the approval record.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec python3 "$HERE/approval_gate.py" apply "$@"
