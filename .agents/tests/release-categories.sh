#!/usr/bin/env sh
# release-categories.sh: refuse a release while a pull request merged since the last one lacks a release category.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/checks.py" release-categories
