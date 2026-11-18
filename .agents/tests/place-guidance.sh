#!/usr/bin/env sh
# place-guidance.sh: guard reviewable summaries, terminal decisions, private plan paths and bootstrap discovery.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/place_guidance_checks.py" "$@"
