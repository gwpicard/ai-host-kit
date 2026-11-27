#!/usr/bin/env sh
# place-prerequisites.sh: guard preflight refusals and their named causes, read OAuth scopes, console guidance and verified local installation.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/place_prerequisite_checks.py" "$@"
