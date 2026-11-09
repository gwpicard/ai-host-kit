#!/usr/bin/env sh
# run-all.sh: run every rehearsal, report incomplete checks and collect all failures.
# Adapted from AI Build Kit; see docs/SOURCES.md.
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT" || exit 1

failed=""
failed_count=0
total=0
not_run_count=0
WORK=$(mktemp -d)
trap 'rm -R "$WORK"' EXIT INT TERM
: > "$WORK/not-run"

run_group() {
  group=$1
  script=$2
  required=""
  case "$group" in
    approval-gate | commit-hook | contracts | host-fit | pull-request-checks | rehearsal-runner | release-builder | source-rules)
      required="python3 git" ;;
  esac
  case "$group" in
    pull-request-checks | release-builder | source-rules) required="$required ruby" ;;
  esac
  for tool in $required; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      printf 'could-not-run: %s is not on PATH\n' "$tool"
      return 2
    fi
  done
  "$script"
}

for script in .agents/tests/*.sh; do
  name=$(basename "$script" .sh)
  case "$name" in
    mutate | 'mutate '* | run-all | 'run-all '*) continue ;;
  esac

  total=$((total + 1))
  printf '\n=== %s ===\n' "$name"
  {
    status=0
    run_group "$name" "$script" || status=$?
    printf '%s\n' "$status" > "$WORK/status"
  } 2>&1 | tee "$WORK/output"
  status=$(cat "$WORK/status")
  reasons=$(sed -n 's/^could-not-run: \(..*\)$/\1/p' "$WORK/output")
  if [ "$status" -eq 0 ]; then
    printf '  passed: %s\n' "$name"
  elif [ "$status" -eq 2 ] && [ -n "$reasons" ]; then
    printf '%s\n' "$reasons" | while IFS= read -r reason; do
      printf '  - %s: %s\n' "$name" "$reason" >> "$WORK/not-run"
    done
    printf '  could not run: %s\n' "$name"
    not_run_count=$((not_run_count + 1))
  else
    printf '  FAILED: %s\n' "$name"
    failed="$failed $name"
    failed_count=$((failed_count + 1))
  fi
done

passed_count=$((total - failed_count - not_run_count))

printf '\n===================================\n'
printf '%d of %d rehearsals passed\n' "$passed_count" "$total"

printf '%d failed; %d could not run\n' "$failed_count" "$not_run_count"
if [ "$not_run_count" -gt 0 ]; then
  printf '\nThese rehearsals could not run fully:\n'
  cat "$WORK/not-run"
fi

# GitHub supplies this variable for the rehearsal job in source-checks.yml.
if [ "${GITHUB_ACTIONS:-}" = true ] && [ "$not_run_count" -gt 0 ]; then
  printf '\nOn GitHub, rehearsals that could not run fail the job.\n'
  failed_count=$((failed_count + not_run_count))
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    printf '## Rehearsals\n\n'
    printf '%d of %d passed.\n\n' "$passed_count" "$total"
    printf '%d could not run.\n\n' "$not_run_count"
    if [ "$not_run_count" -gt 0 ]; then
      printf 'Could not run fully:\n'
      cat "$WORK/not-run"
      printf '\n'
    fi
    for name in $failed; do
      printf -- '- failed: `%s`\n' "$name"
    done
  } >> "$GITHUB_STEP_SUMMARY"
fi

if [ "$failed_count" -gt 0 ]; then
  if [ -n "$failed" ]; then
    printf '\nThese rehearsals failed:\n'
    for name in $failed; do
      printf -- '  - %s\n' "$name"
    done
  fi
  printf '\nRun one on its own to read its output: .agents/tests/<name>.sh\n'
  exit 1
fi

if [ "$not_run_count" -eq 0 ]; then printf 'Every rehearsal passed.\n'; fi
