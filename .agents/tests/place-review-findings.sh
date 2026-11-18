#!/usr/bin/env sh
# place-review-findings.sh: guard complete inventories, terminal ordering, opened secrets, child environments and init refusals.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/place_review_findings.py" "$@"
