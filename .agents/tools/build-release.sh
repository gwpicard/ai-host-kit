#!/usr/bin/env sh
# build-release.sh: assemble the public kit in a new folder outside the source.
# Adapted from AI Build Kit; see docs/SOURCES.md.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tools/kit.py" build-release "$@"
