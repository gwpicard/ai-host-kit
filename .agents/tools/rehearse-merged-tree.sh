#!/usr/bin/env sh
# rehearse-merged-tree.sh: validate and test tracked files in a clean repository.
# Adapted from AI Build Kit; see docs/SOURCES.md.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)

command -v git >/dev/null 2>&1 || { echo "error: git is needed" >&2; exit 1; }

ALLOW_DIRTY=0
if [ "${1:-}" = "--allow-dirty" ]; then
  ALLOW_DIRTY=1
  shift
fi

KEEP=0
if [ "$#" -gt 1 ]; then
  echo "usage: $0 [folder]" >&2
  exit 2
elif [ "$#" -eq 1 ]; then
  KEEP=1
  [ ! -e "$1" ] || { echo "error: $1 already exists" >&2; exit 1; }
  parent=$(dirname -- "$1")
  [ -d "$parent" ] || { echo "error: no such folder: $parent" >&2; exit 1; }
  TREE=$(CDPATH= cd -- "$parent" && pwd -P)/$(basename -- "$1")
  case "$TREE" in
    "$ROOT" | "$ROOT"/*)
      echo "error: build the merged tree outside this repository" >&2
      exit 1
      ;;
  esac
else
  SCRATCH=$(mktemp -d)
  TREE="$SCRATCH/merged"
  trap 'rm -rf "$SCRATCH"' EXIT INT TERM
fi

if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
  if [ "$ALLOW_DIRTY" -eq 0 ]; then
    echo "error: this working tree has unsaved changes." >&2
    echo "       The rehearsal copies what is on disk while a cutover reads the" >&2
    echo "       commit, so a green result here would not be about the tree that" >&2
    echo "       gets pushed. Save the work, or pass --allow-dirty on purpose." >&2
    echo >&2
    git -C "$ROOT" status --short >&2
    exit 1
  fi
  echo "note: rehearsing unsaved work, because --allow-dirty was passed. This is"
  echo "      not the tree a cutover would push."
  echo
fi

echo "Assembling the merged tree at $TREE"
mkdir -p "$TREE"
git -C "$ROOT" -c core.quotePath=false ls-files > "$TREE/.tracked-files"
while IFS= read -r tracked; do
  [ -n "$tracked" ] || continue
  mkdir -p "$TREE/$(dirname -- "$tracked")"
  cp -Pp "$ROOT/$tracked" "$TREE/$tracked"
done < "$TREE/.tracked-files"
rm -f "$TREE/.tracked-files"

git -C "$TREE" init --quiet
git -C "$TREE" add -A
git -C "$TREE" \
  -c user.name="Guillaume Picard" \
  -c user.email="rehearsal@example.invalid" \
  commit --quiet -m "The end state, as one commit"

echo "Committed $(git -C "$TREE" ls-files | wc -l | tr -d ' ') files."

# Each step is an independent opinion, so one failure must not hide another and
# the run carries on to the end.
failed=""
for step in \
  ".agents/tools/build-adapters.sh --check" \
  ".agents/tools/validate-kit.sh" \
  ".agents/tests/run-all.sh"; do
  name=${step%% *}
  printf '\n########## %s ##########\n' "$name"
  if (cd "$TREE" && sh -c "$step"); then
    printf '  passed: %s\n' "$name"
  else
    printf '  FAILED: %s\n' "$name"
    failed="$failed $name"
  fi
done

printf '\n===================================\n'
if [ -n "$failed" ]; then
  printf 'The merged tree is not green. These steps failed:\n'
  for name in $failed; do
    printf -- '  - %s\n' "$name"
  done
  [ "$KEEP" -eq 1 ] && printf '\nThe tree is at %s\n' "$TREE"
  exit 1
fi

printf 'The merged tree is green: all three steps passed.\n'
[ "$KEEP" -eq 1 ] && printf 'The tree is at %s\n' "$TREE"
exit 0
