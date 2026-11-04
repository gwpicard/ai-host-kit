#!/usr/bin/env sh
# attribution-scrub.sh: clean real commits for every supported agent and preserve prose.
#
# The hook exists because this repository went public carrying a session link
# in nineteen commit messages and in thirteen pull request descriptions. A
# session link is a personal address on the agent vendor's site. Taking them
# out meant rewriting every commit and force-pushing a branch other people had
# already cloned, which is a thing to do once.
#
# A setting turns the lines off at the source, and this hook is the guard
# behind it, for the session that overrides the setting and the clone that
# never had it. So the hook is the thing worth testing, and it is testable:
# a message goes in, a message comes out, and a machine can judge it.
#
# The case that matters most is the last one. The kit is built with Claude,
# Cursor and Gemini and writes about them in almost every commit. A hook that
# went after the word rather than the attribution line would quietly gut those
# messages, and nobody would notice until the history was unreadable.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
HOOK="$ROOT/.githooks/commit-msg"

[ -f "$HOOK" ] || { echo "FAIL: missing $HOOK" >&2; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

passes=0

echo "Attribution scrub checks:"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

ok() {
  echo "  ok: $1"
  passes=$((passes + 1))
}

# scrub <message>: run the real hook over a message, print the result.
scrub() {
  printf '%s\n' "$1" > "$WORK/msg"
  sh "$HOOK" "$WORK/msg"
  cat "$WORK/msg"
}

# gone <what> <message> <needle>: the needle must not survive the hook.
gone() {
  if scrub "$2" | grep -qiF -- "$3"; then
    fail "$1"
  fi
  ok "$1"
}

# kept <what> <message> <needle>: the needle must survive the hook.
kept() {
  if scrub "$2" | grep -qF -- "$3"; then
    ok "$1"
  else
    fail "$1"
  fi
}

# The attribution words are built from pieces rather than written out. The
# validator refuses a tracked file carrying them, and a sample built this way
# gives it nothing to find, so this file needs no exemption. A real line pasted
# in here by mistake is still caught.
session=$(printf 'claude.ai/code/%s' 'session_')
session_key=$(printf 'Claude-%s:' Session)
coauthor=$(printf 'Co-%sed-By: Claude' 'Author')
vendor=$(printf 'noreply@%s.com' 'anthropic')
generated=$(printf 'Generated %s' 'by')
with=$(printf 'Generated %s' 'with')

session_trailer="Say the thing

$session_key https://${session}0000000000000000000000"

coauthor_trailer="Say the thing

$coauthor Opus 5 (1M context) <$vendor>"

squashed="Say the thing

Some body text.

---------

$coauthor <$vendor>"

# The same squash merge with another trailer below the removed one. The dashes
# are no longer the last line, and they are still stranded.
squashed_signed="Say the thing

Some body text.

---------

$coauthor <$vendor>
Signed-off-by: A Person <a.person@example.com>"

# A row of dashes with a kept line under it is not stranded.
dashes_kept='Say the thing

---------

Signed-off-by: A Person <a.person@example.com>'

footer="Say the thing

🤖 $with [Claude Code](https://claude.com/claude-code)"

plain_footer="Say the thing

🤖 $with Claude Code"

about_the_tools='Rename the command that shapes a piece

Claude Code now carries a /plan of its own, which starts its read-only plan
mode. The command is now /shape, and it reads the same in Claude, Cursor and
Gemini alike.'

bare_link="Say the thing

https://${session}0000000000000000000000"

# A sentence that names the tool is not the footer, even when it uses the
# footer's words.
footer_words_in_prose='Say the thing

The first draft was generated with Claude Code and then rewritten by hand.'

plain='Say the thing

A body with nothing to take out of it.'

gone "the session link goes" "$session_trailer" "$session"
gone "the co-author trailer goes" "$coauthor_trailer" "$coauthor"
gone "the vendor address goes with it" "$coauthor_trailer" "$vendor"
gone "the pull request footer goes" "$footer" 'Generated with [Claude Code]'
gone "the footer without its link goes" "$plain_footer" 'Generated with Claude Code'
kept "a sentence using the footer's words stays" "$footer_words_in_prose" 'generated with Claude Code and then'
gone "a bare session link goes" "$bare_link" "$session"

# A squash merge writes a row of dashes above the trailer it folds in. Take the
# trailer and leave the dashes, and every rewritten message ends on punctuation
# with nothing after it.
gone "the stranded squash separator goes too" "$squashed" '---------'
kept "the body above the separator stays" "$squashed" 'Some body text.'
gone "the separator goes when another trailer follows" "$squashed_signed" '---------'
kept "and that other trailer stays" "$squashed_signed" 'Signed-off-by: A Person'
kept "a separator with a kept line under it stays" "$dashes_kept" '---------'

# The subject line is the one part of a message that is always read.
kept "the subject line survives" "$session_trailer" 'Say the thing'

# The rule the hook is most likely to get wrong.
kept "prose about the tools survives" "$about_the_tools" 'reads the same in Claude, Cursor and'
kept "so does a slash command named in prose" "$about_the_tools" '/shape'

# A message with nothing to remove must come back byte for byte, or the hook is
# editing every commit in the repository rather than the ones it was written for.
printf '%s\n' "$plain" > "$WORK/before"
cp "$WORK/before" "$WORK/msg"
sh "$HOOK" "$WORK/msg"
if cmp -s "$WORK/before" "$WORK/msg"; then
  ok "a clean message is returned unchanged"
else
  fail "a clean message was edited"
fi

# The samples above are built from pieces so that the validator can read this
# file like any other. An exemption by path would let a real line pasted in here
# pass unseen, so require that the validator names no such exemption.
if grep -qF '.agents/tests/attribution-scrub.sh' "$ROOT/.agents/tools/validate-kit.sh"; then
  fail "the validator still leaves this file out of its attribution scan"
fi
ok "the validator reads this file like any other"

# The control. A check that cannot fail proves nothing, so take the rule out of
# a copy of the hook and require the run to notice.
#
# The message here is the bare link rather than the trailer. Two rules catch a
# Claude-Session trailer, the one that reads the key and the one that reads the
# address, so removing either still left the trailer caught and the control
# passed while proving nothing. The bare link is reached by one rule only.
sed '/if (low ~ .*claude/d' "$HOOK" > "$WORK/hook-without-the-rule"
printf '%s\n' "$bare_link" > "$WORK/msg"
sh "$WORK/hook-without-the-rule" "$WORK/msg"
if grep -qF "$session" "$WORK/msg"; then
  ok "removing the session rule is caught"
else
  fail "the hook still removed the session link without its rule, so nothing here is guarded"
fi

# Use Git itself: a filter-only test would miss a non-executable hook or wrong
# installation path. Each sample must leave exactly the expected commit body.
git init -q "$WORK/repo"
git -C "$WORK/repo" config core.hooksPath "$ROOT/.githooks"
trailer=$(printf 'Co-%sed-By:' 'Author')
real_commit() {
  label=$1
  expected=$2
  extra=$3
  printf '%s\n' "$expected" > "$WORK/expected"
  printf '%s\n\n%s\n' "$expected" "$extra" > "$WORK/message"
  git -C "$WORK/repo" -c user.name="Guillaume Picard" \
    -c user.email=rehearsal@example.invalid -c commit.gpgSign=false \
    commit -q --allow-empty --cleanup=verbatim -F "$WORK/message"
  git -C "$WORK/repo" log -1 --format=%B > "$WORK/saved"
  # git log adds a record separator after the message.
  printf '\n' >> "$WORK/expected"
  cmp -s "$WORK/expected" "$WORK/saved" || fail "$label: saved message differs"
  ok "$label: real commit has exactly the expected message"
}

# Sources for documented defaults are beside the rules in the hook. Generated
# footers and labelled sessions for all five agents are defensive samples, not
# a claim that every agent emits every form. Addresses are built at runtime.
while IFS='|' read -r name model address url; do
  body="Keep the commit readable

Work was done with $name and checked by hand.
The first draft was generated with $name and then revised.
The first draft was generated by [$name](https://example.com/tool).
Generated by $name during a test, this sentence stays.
Generated by $model during a test, this sentence stays.
Made with $name during a test, this sentence stays.
Signed-off-by: A Person <person@example.com>"
  real_commit "$name co-author" "$body" "$trailer $model <$address>"
  real_commit "$name name alone" "$body" "$trailer $model"
  real_commit "$name generated footer" "$body" "$generated $name."
  real_commit "$name linked footer" "$body" "🤖 $with [$name](https://example.com/tool)"
  real_commit "$name session key" "$body" "$name-Session: example-session"
  real_commit "$name bare session link" "$body" "$url"
  real_commit "$name address byline" "$body" "Agent <$address>"
  real_commit "$name bare address" "$body" "$address"
  real_commit "$name prose only" "$body" ""
done <<EOF
Claude Code|Claude Sonnet 4.6|$vendor|https://${session}example
Codex|Codex|$(printf 'noreply@%s.com' openai)|$(printf 'https://chatgpt.com/codex/%s' task_example)
Cursor|Cursor Agent|$(printf 'cursoragent@%s' cursor.com)|$(printf 'https://cursor.com/%s' agents/example)
Gemini CLI|gemini-cli|$(printf '218195315+gemini-cli@%s' users.noreply.github.com)|$(printf 'https://gemini.google.com/%s' share/example)
GitHub Copilot|Copilot|$(printf 'copilot@%s.com' github)|$(printf 'https://github.com/copilot/%s' tasks/example)
EOF

real_commit "Cursor native trailer" "$plain" "$(printf 'Made-%s: Cursor' with)"
real_commit "Cursor PR footer" "$plain" "$(printf 'Made %s Cursor' with)"
real_commit "case and whitespace" "$plain" "  $(printf 'cO-%sEd-bY: GPT-5.3-Codex' aUtHoR)  "
real_commit "Copilot bot address" "$plain" "$trailer An Agent <$(printf '175728472+copilot-swe-agent[bot]@%s' users.noreply.github.com)>"
real_commit "Claude bare model" "$plain" "$trailer Opus 4.6"
real_commit "Gemini model" "$plain" "$trailer Gemini 2.5 Pro"
real_commit "GPT model with letter suffix" "$plain" "$trailer GPT-4o-mini"
real_commit "Claude version before family" "$plain" "$trailer Claude 3.5 Sonnet"

# Human co-authors, ordinary noreply addresses and near-matching tool names
# stay, as do documentation links and sentences mentioning attribution words.
negative="$plain

$trailer Claude Shannon <claude@example.com>
$trailer A Person <123+person@users.noreply.github.com>
$trailer Codexia <codexia@example.com>
$trailer Gemini Researcher <person@example.com>
$generated a code generator.
$generated [Codex](https://example.com) and edited by hand.
$generated Gemini 2.5 Pro during a test, this sentence stays.
$generated GPT-5.3-Codex during a test, this sentence stays.
Read https://chatgpt.com/codex/ for the product.
Read https://cursor.com/docs/agent/overview for the agent documentation.
Read https://geminicli.com/docs/ for Gemini CLI.
Contact noreply@example.com for the test.
Discuss the phrase $trailer Codex in the guide."
real_commit "ordinary prose and human trailers" "$negative" ""

echo
echo "attribution-scrub.sh: all $passes checks passed"
