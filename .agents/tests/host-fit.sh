#!/usr/bin/env sh
# host-fit.sh: guard fit lines, choices, unknowns, acceptance, recipe boundaries and replay inputs with mutations.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/host_fit_checks.py"
