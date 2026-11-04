# Maintaining AI Host Kit

This is the beta kit's maintainer source. This guide does not ship in a release.
Read [AGENTS.md](../AGENTS.md) and [PHILOSOPHY.md](PHILOSOPHY.md) before editing.

## Prepare a clone

Run `git config core.hooksPath .githooks` before the first commit. Git does not
inherit that local setting. The unchanged hook removes attribution lines and
session links. Save as the maintainer with
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
The other checks are `pull-request-base` and `release-label`. Required checks
on `main` must be configured by the maintainer after these workflows merge.
Until then, a green local run is evidence, not a claim of merge protection.
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
honest about the stub; there are no background skills or agents yet.

Maintainer skills live in `.agents/maintainer-skills/`. They have no adapter or
release entry. The writing skill retains its MIT licence. Before saving any
prose, including error messages, commits and pull request text, load
`.agents/maintainer-skills/writing-review/SKILL.md` and use embedded mode.
Use British spelling and plain adult prose, with no em or en dashes. Preserve
facts and conditions, use natural verbs, and cut unsupported claims.

## Checks and their limits

The checks require Git, a POSIX shell, Python 3 and Ruby for YAML parsing.
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
