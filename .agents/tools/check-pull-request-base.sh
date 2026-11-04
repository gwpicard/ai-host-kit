#!/usr/bin/env sh
# check-pull-request-base.sh: accept only main as a pull request base.
# Adapted from AI Build Kit; see docs/SOURCES.md.
set -eu
[ "$#" -eq 1 ] && [ -n "$1" ] || { echo 'usage: check-pull-request-base.sh <base>' >&2; exit 2; }
if [ "$1" != main ]; then
  echo 'Pull requests must target main. Change the base to main before review.' >&2
  exit 1
fi
echo 'Pull request base is main.'
