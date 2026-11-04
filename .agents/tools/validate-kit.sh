#!/usr/bin/env sh
# validate-kit.sh: check the hosting kit source and distribution boundaries.
# Adapted from AI Build Kit; see docs/SOURCES.md.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tools/kit.py" validate-kit "$@"
