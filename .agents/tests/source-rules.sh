#!/usr/bin/env sh
# source-rules.sh: prove source rules reject planted violations, including a missing beta notice.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/checks.py" source-rules
