#!/usr/bin/env sh
# pull-request-checks.sh: pass missing release labels with a notice, refuse unknown categories when opening, and refuse every base except main.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/checks.py" pull-request-checks
