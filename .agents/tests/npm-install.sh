#!/usr/bin/env sh
# npm-install.sh: guard real offline npm config isolation, disabled lifecycle scripts and lock integrity.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/place_prerequisite_checks.py" --case real_npm
