#!/usr/bin/env sh
# check-release-label.sh: require a deliberate release category.
# Adapted from AI Build Kit; see docs/SOURCES.md.
set -eu

ACCEPTED="feature
enhancement
bug
documentation
chore
skip-release-notes
release-major
release-minor
release-patch"

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

# The message is read by a person looking at a red check, so it says what to do
# rather than what went wrong.
cat >&2 <<MESSAGE
This pull request has no label saying what kind of change it is, so the release
number would be chosen by default rather than by anybody.

Add one of these, then this check passes:

  feature, enhancement   a new thing people using the kit can do   (minor)
  bug                    a repair                                   (patch)
  documentation          a change to what the kit says              (patch)
  chore                  maintenance, nothing for a reader          (patch)
  skip-release-notes     never shows in the notes, such as a
                         version stamp or maintainer-only material

  release-major, release-minor, release-patch
                         force the version, whatever else is present

Labels found on this pull request: ${found:-none}
MESSAGE
exit 1
