#!/usr/bin/env sh
# build-adapters.sh: generate command adapters from the canonical skills.
# Adapted from AI Build Kit; see docs/SOURCES.md.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tools/kit.py" build-adapters "$@"
