#!/usr/bin/env sh
# approve.sh: read a person's approval from the controlling terminal.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec python3 "$HERE/approval_gate.py" approve "$@"
