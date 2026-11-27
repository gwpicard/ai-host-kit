#!/usr/bin/env sh
# check-release-label.sh: report whether a pull request carries a release category.
# Adapted from AI Build Kit; see docs/SOURCES.md.
#
# A missing category does not fail this check. The release step,
# check-release-categories.py, refuses a release while any merged pull request
# lacks one. This check gives early notice so the label can be added in review.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
CATEGORIES="$ROOT/.agents/tools/release-categories.txt"
ACCEPTED=$(sed -n 's/^\([a-z][a-z-]*\).*/\1/p' "$CATEGORIES")
if [ -z "$ACCEPTED" ]; then
  echo "No release categories could be read from $CATEGORIES." >&2
  exit 2
fi

if [ "$#" -gt 0 ]; then
  found=$(printf '%s\n' "$@")
else
  found=$(cat)
fi

matched=""
for label in $ACCEPTED; do
  printf '%s\n' "$found" | grep -qxF "$label" && matched="$label"
done

if [ -n "$matched" ]; then
  echo "This pull request carries '$matched', so the release number is somebody's decision."
  exit 0
fi

found_list=$(printf '%s\n' "$found" | sed '/^$/d' | paste -sd ',' - | sed 's/,/, /g')
choices=$(grep -v '^#' "$CATEGORIES" | sed 's/^/  /')

# GitHub shows this line as an annotation on the pull request's checks.
echo "::notice title=No release category yet::This pull request has no release category label. The release will refuse to proceed until it has one. Add one with: gh pr edit <number> --add-label <category>"

explain() {
  cat <<MESSAGE
This pull request has no label saying what kind of change it is. This check
still passes, but the release step refuses to proceed while any merged pull
request lacks a category, so the version number is somebody's decision.

Add one of these before or after merging:

$choices

With the GitHub CLI: gh pr edit <number> --add-label <category>
Labels found on this pull request: ${found_list:-none}
MESSAGE
}
explain

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    printf '## No release category yet\n\n```\n'
    explain
    printf '```\n'
  } >> "$GITHUB_STEP_SUMMARY"
fi
exit 0
