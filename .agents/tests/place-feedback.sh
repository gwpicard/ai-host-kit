#!/usr/bin/env sh
# place-feedback.sh: guard safe and fixed refusal reasons ahead of guidance, withheld library errors, HTTP statuses and one-day key guidance through Place commands.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/place_feedback_checks.py" "$@"
