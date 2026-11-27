#!/usr/bin/env sh
# open-pull-request.sh: open a pull request against main with a release category.
#
# Usage: open-pull-request.sh <category> [extra gh pr create arguments...]
# The category must be listed in release-categories.txt. The branch must
# already be on GitHub: this tool names it as the head so gh never pushes, and
# it never merges.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
CATEGORIES="$ROOT/.agents/tools/release-categories.txt"
ACCEPTED=$(sed -n 's/^\([a-z][a-z-]*\).*/\1/p' "$CATEGORIES")

usage() {
  {
    printf '%s\n\n' "$1"
    printf 'Usage: .agents/tools/open-pull-request.sh <category> [gh pr create arguments...]\n\n'
    printf 'Choose the category that says what kind of change this is:\n\n'
    grep -v '^#' "$CATEGORIES" | sed 's/^/  /'
  } >&2
  exit 2
}

[ "$#" -gt 0 ] || usage 'No release category was given.'
category=$1
shift
printf '%s\n' "$ACCEPTED" | grep -qxF -- "$category" \
  || usage "'$category' is not a release category."

for argument in "$@"; do
  case "$argument" in
    -B | -B* | --base | --base=*)
      usage 'Pull requests always target main; remove the base argument.' ;;
    -H | -H* | --head | --head=*)
      usage 'The head is the current branch; switch to the branch instead of naming it.' ;;
  esac
done

branch=$(git -C "$ROOT" branch --show-current)
[ -n "$branch" ] || usage 'No branch is checked out, so there is nothing to open a pull request from.'
[ "$branch" != main ] || usage 'The current branch is main; start a branch from origin/main first.'

exec gh pr create --base main --head "$branch" --label "$category" "$@"
