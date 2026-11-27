#!/usr/bin/env sh
# prepare-stable.sh: stamp a release version on a local commit for the stable branch; never pushes.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tools/kit.py" prepare-stable "$@"
