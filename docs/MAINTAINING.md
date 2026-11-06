# Maintaining AI Host Kit

This is the beta kit's maintainer source. This guide does not ship in a release.
Read [AGENTS.md](../AGENTS.md) and [PHILOSOPHY.md](PHILOSOPHY.md) before editing.

## Prepare a clone

Run `git config core.hooksPath .githooks` before the first commit. Git does not
inherit that local setting. The unchanged hook removes Claude attribution lines
and session links. [PROMISES.md](PROMISES.md) records the coverage limit and
pending upstream fix. Save as the maintainer with
`git -c user.name="Guillaume Picard" commit`.

## Work and review

Keep work in this repository's issues. An epic has sub-issues for its pieces;
use two levels. A piece describes the problem, evidence, goal, scope, Done when,
assumptions and risks. Its Done when lines describe results someone can check.
Use an `area:` label and a type label. `needs-answers` marks an unanswered
question; `ready` means the maintainer judged the piece shaped.

Start a short-lived branch from `origin/main`. Pull requests target only `main`.
Use `gh pr create --base main` and choose a release label: `feature`,
`enhancement`, `bug`, `documentation`, `chore`, `skip-release-notes`,
`release-major`, `release-minor` or `release-patch`. The label check requires a
choice; it cannot judge whether the choice fits.

The source workflow has jobs named `source-kit-validation` and `rehearsal`.
The other checks are `pull-request-base` and `release-label`. The `main` ruleset
requires all four checks, so a failing required check blocks merging.
The first release will establish `stable` and its ruleset; neither exists as
part of this work. Do not change repository settings during source work.

## Skills and adapters

Edit `.agents/skills/<name>/SKILL.md`, then run:

```sh
.agents/tools/build-adapters.sh
.agents/tools/validate-kit.sh
.agents/tests/run-all.sh
```

Save canonical skills and generated adapters together. The inventory is
`.agents/tools/kit-inventory.txt`. [COMPATIBILITY.md](COMPATIBILITY.md) owns the
installation routes and coding agent map. A command's description must remain
honest about what is built. `host-fit` is a background skill with no command
adapter; the inventory records it separately. No agents are shipped.

Maintainer skills live in `.agents/maintainer-skills/`. They have no adapter or
release entry. The writing skill retains its MIT licence. Before saving any
prose, including error messages, commits and pull request text, load
`.agents/maintainer-skills/writing-review/SKILL.md` and use embedded mode.
Follow the writing rule and copied-skill exception in [AGENTS.md](../AGENTS.md#writing).
Preserve facts and conditions, use natural verbs, and cut unsupported claims.

## Checks and their limits

The checks require Git, a POSIX shell, Python 3 and Ruby for YAML parsing.
The contract tests also use pinned Python packages. Prepare an environment
outside the repository and activate it before running the suite or rehearsal:

```sh
python3 -m venv /private/tmp/ai-host-kit-checks
. /private/tmp/ai-host-kit-checks/bin/activate
python3 -m pip install -r .agents/tools/schema-requirements.txt
```

On systems without `/private/tmp`, choose another temporary folder. CI installs
the same requirements. [The contract guide](../contracts/README.md) describes
the published, vendored handover, Host Kit records and the separate vendoring check.

The validator checks adapter drift, command consistency, configuration syntax,
release boundaries, attribution, issue references and the beta notice. It
rejects em and en dashes in shipped prose. It reads Git's tracked file list;
stage new files before checking them. It also checks saved executable modes.

The test runner discovers every shell test in `.agents/tests/`, continues
after failures and lists each result. Each test's second line names what it
guards. A test that could not run reports that separately and never counts as
passed; on GitHub it fails the job. The deterministic suite uses no host,
credentials or model. It tests boundaries and script outcomes. It does not
claim to prove conversations or hosting promises.

Before pushing, save the tree, then run:

```sh
.agents/tools/rehearse-merged-tree.sh
```

This copies tracked files and modes into a fresh repository outside this one,
commits as the maintainer, and runs adapter checking, validation and the suite.
Use `--allow-dirty` only for a rehearsal before committing. A supplied output
folder retains the copy for inspection. Default scratch folders are removed.

## Release boundary

`release-manifest.txt` lists every source and destination that may ship. A
directory entry copies only its tracked files. Maintainer instructions, tools,
tests, hooks, workflows and maintainer skills stay out. Symlinks, unsafe paths
and overlapping destinations are refused before output is created.

```sh
.agents/tools/build-release.sh v0.0.1 /private/tmp/ai-host-kit-preview
```

The destination must be new and outside the source repository. Packaging stamps
both plugin manifests and `.ai-host-kit-version`, and puts full skill copies
in `agent-plugin/skills/`. It publishes nothing. Version `0.0.1` is the initial
beta version. Every version below `1.0.0` requires the README beta notice.

Before a release, read [PROMISES.md](PROMISES.md) and [SOURCES.md](SOURCES.md),
run both checks and the merged-tree rehearsal, then rehearse both install
routes in disposable projects. Ask what an existing user must do to upgrade.
Record missing checks and compatibility limits in the review. Publication,
tags, release promotion and the `stable` ruleset need separate instructions.

## Adopt an upstream handover commit

Read the [pin format](../contracts/ai-build-kit/README.md). Fetch AI Build Kit's
named branch and the candidate commit in a temporary repository. Confirm the
commit is reachable from that branch, inspect `hosting/handover.schema.json`
at the commit, and record its Git blob and SHA-256. A release tag is not needed.
Copy the file byte for byte into `contracts/ai-build-kit/handover.schema.json`
and save the six-field `upstream.json` pin beside it. Never edit the schema to
make Host Kit's checks pass.

Update fixtures, reader paths and any rules that rely on changed fields.
Check whether Host Kit refuses a handover the published schema accepts;
remove the extra rule or explain why it is needed. Refresh bundled resources
with `build-adapters.sh`, run validation and the suite after each step, and
run replay dry mode. Save the pin and schema together, then run
`python3 .agents/tools/check-handover-vendor.py` with network access. The
checker requires the pin in `HEAD`; an unsaved pin cannot produce a pass.
Report a failed or unavailable real check as such. Finish with the saved-tree
rehearsal. Review the commit, blob, hash, fixture and rule changes and all check
results in the pull request before adopting the commit.

## Local host choice and replays

Edit recipe declarations in `.agents/skills/recipes/`, schemas in `contracts/`
and the reader in `.agents/tools/record_validation.py`. `build-adapters.sh`
also refreshes their runtime copies in `host-fit/resources/`. Never edit those
copies directly. Drift fails the same adapter check. The script and generated
resources ship inside host-fit so a skill-only installation has its dependencies.

The local outcome checks are in `.agents/tests/host-fit.sh`. They compare fixed
fit lines for every valid handover fixture against every stub and refuse the
invalid fixtures before reporting fit. They test the suggestion table, question
selection, record preservation, acceptance and recipe/menu boundaries. Mutations
remove protections in disposable copies and rerun the outcome assertions.

Prepare replay projects without calling a model:

```sh
python3 .agents/tools/replay-host-choice.py --dry --case all
```

Dry mode reads the Project skills command prefix from `host-fit/SKILL.md`,
requires the harness's independent Bash allow rule to match it exactly, then
runs that command with `python3` from each throwaway project root. The rule
uses Claude Code's [trailing wildcard syntax](https://code.claude.com/docs/en/permissions#wildcard-patterns).
The check covers this literal command form, not Claude Code's permission engine
or the agent's choice of command. The suite changes the skill command and
allow rule separately in a disposable copy, requires dry mode to fail, then
restores each change and reruns it. It also refuses a broader Python allow rule.
Packaged and shared skill copies run their documented commands from separate
projects. These checks do not invoke a model or repeat the real installers.

On the finished branch, the maintainer can run the scripted person turns once:

```sh
python3 .agents/tools/replay-host-choice.py --run --case all --output /private/tmp/ai-host-kit-host-choice-replays
```

Use the activated Python environment above and a new output folder. The run
needs an authenticated Claude Code installation. It calls `claude -p` for each
person turn and resumes the same session within a case. Tool permission covers
local file operations and the host-fit script. The fixture instructions forbid
provider calls; the harness is not a host isolation mechanism. It does not load
project or provider credentials into the child environment.

Each case leaves its transcript, expected outcomes and project files. Review
meaning and outcomes: the suggested host, trade-off, questions actually asked,
every need shown, recorded answers and wishes, and a single shortfall notice
followed by dated acceptance with no further gate. A completed call is not a
pass. Record the maintainer's verdict beside the evidence; deterministic checks
and dry mode do not establish that a replay suggests the expected host.
