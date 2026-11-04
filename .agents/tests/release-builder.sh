#!/usr/bin/env sh
# release-builder.sh: keep the public kit complete, repeatable and free of maintainer files.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/checks.py" release-builder
