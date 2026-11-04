#!/usr/bin/env sh
# pull-request-checks.sh: refuse missing release labels and every pull request base except main.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/checks.py" pull-request-checks
