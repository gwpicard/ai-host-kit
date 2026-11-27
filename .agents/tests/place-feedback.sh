#!/usr/bin/env sh
# place-feedback.sh: guard safe and fixed refusal reasons ahead of guidance, withheld library errors, HTTP statuses, one-day key order and ID, named plans folders, named missing values and the public proxy through Place commands.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/place_feedback_checks.py" "$@"
