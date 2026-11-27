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
Push the branch, then open the pull request with a release category:

```sh
.agents/tools/open-pull-request.sh chore --title "..." --body "..."
```

The tool refuses a missing or unknown category, then runs
`gh pr create --base main --head <current branch> --label <category>` with any
further arguments. Naming the head stops `gh` from pushing; the tool never
merges. `.agents/tools/release-categories.txt` is the single list of categories
and what each means for the version: `feature`, `enhancement`, `bug`,
`documentation`, `chore`, `skip-release-notes`, `release-major`,
`release-minor` and `release-patch`.

The `release-label` check reports the category but never fails for a missing
one. Without a category it passes with a notice on the pull request and in the
job summary, explaining how to add one. The category is enforced when a release
is prepared, as the release section describes. No check judges whether the
chosen category fits.

The source workflow has jobs named `source-kit-validation` and `rehearsal`.
The other checks are `pull-request-base` and `release-label`. The `main` ruleset
requires all four checks, so a failing required check blocks merging. Because
`release-label` passes without a category, it blocks a merge only if the check
itself cannot run.
`main` is the working branch; people who install the Claude Code plugin
receive only what a release puts on `stable`, as the release section
describes. The `stable` ruleset needs a separate instruction. Do not change
repository settings during source work.

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

The checks require Git, dash or posh for shell syntax checks, Python 3 and Ruby
for YAML parsing. The validator refuses to run its syntax checks without dash
or posh; it does not fall back to the system `sh`, which may accept Bash syntax.
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

Before choosing a release's version, confirm that every pull request merged
since the last release has a category:

```sh
.agents/tools/check-release-categories.py
```

It asks GitHub through `gh` for the latest published release and the pull
requests merged into `main` after it. It refuses to proceed while any lacks a
category, lists each one by number and title, and says how to add a label. When
all have one, it lists each pull request with its category so a person can
decide the version. With no published release, it checks every merged pull
request. `--since` overrides the release time; `--input` reads the
pull requests from a file, or standard input with `-`, in the shape
`gh pr list --json number,title,labels,mergedAt` prints. The builder does not
run this check, because it works offline; nothing maps categories to a version
automatically.

Then read [PROMISES.md](PROMISES.md) and [SOURCES.md](SOURCES.md),
run both checks and the merged-tree rehearsal, then rehearse both install
routes in disposable projects. Ask what an existing user must do to upgrade.
Record missing checks and compatibility limits in the review. Publication,
tags, release promotion and the `stable` ruleset need separate instructions.

## Release to stable

The marketplace entry in `.claude-plugin/marketplace.json` installs the plugin
from this repository's `stable` branch. Claude Code computes the plugin's
version from `version` in `.claude-plugin/plugin.json` on that branch and
replaces an installed copy only when that version changes, as its
[version rules](https://code.claude.com/docs/en/plugins/loading.md#how-claude-code-computes-the-version)
describe. Merging to `main` therefore reaches nobody who installed the plugin;
a release does. The validator refuses any other plugin source, a version in the
marketplace entry, and version markers that disagree.

The version markers are both plugin manifests, `.ai-host-kit-version` and
`KIT_VERSION` in the Coolify recipe's `mcp.py` and its generated host-fit copy.
`main` keeps the version it already has. Only the release commit carries the
new one, and the release tool reads the last released version from
`origin/stable` and the local `v` tags.

After the category check, on a clean checkout of the commit to release:

```sh
git fetch origin --tags
git switch main && git pull --ff-only
.agents/tools/prepare-stable.sh v0.1.0
```

The tool works offline and pushes nothing. It refuses unsaved or untracked
files, a commit that is not on `origin/main`, version markers that disagree,
and a version that is not newer than the last release under Semantic
Versioning precedence. A second argument names an earlier commit on
`origin/main` instead of `HEAD`. It builds the release commit in a private
index without touching the checkout, stamps every version marker, and saves
the commit as the maintainer on a local `release/v<version>` branch with an
annotated `v<version>` tag. Unless `stable` is already part of the source
history, the commit's second parent is the current `origin/stable`, so
`stable` always moves by fast-forward although the stamp never returns to
`main`. The tool prints the push commands and the commands that discard the
local branch and tag.

Check the release tree, then push it:

```sh
git switch release/v0.1.0
.agents/tools/validate-kit.sh
git switch main
git push origin <release commit>:refs/heads/stable
git push origin refs/tags/v0.1.0
```

An ordinary push refuses anything but a fast-forward; never force `stable`.
Publishing a GitHub release from the tag, for example with
`gh release create v0.1.0 --verify-tag`, gives the category check its next
starting point. Without one, pass `--since` to that check. For the Agent
Plugins package, build the folder from the tag in a separate worktree, such as
`git worktree add /private/tmp/ai-host-kit-v0.1.0 v0.1.0`, then run that
worktree's `build-release.sh v0.1.0` with a new output folder.

Finally, add the marketplace in a disposable project as the
[compatibility guide](COMPATIBILITY.md) describes, install the plugin and
confirm that `claude plugin list --json` reports the new version.

### The first release

Until `stable` exists, an install or marketplace refresh that reads this entry
from `main` cannot fetch the plugin. Existing installs keep their cached copy.
Push the first release as soon as the change that introduced the `stable`
entry is merged:

1. Before merging, run `.agents/tools/check-release-categories.py` and choose
   the version. Every pull request so far has a category, and several are
   `feature`, so the first release is a minor release: `v0.1.0`.
2. Merge the change.
3. Run the three release steps above with `v0.1.0`, the checks and the
   merged-tree rehearsal on the merged `main`, then push both refs.
4. In a disposable project, install from `gwpicard/ai-host-kit` and confirm
   version `0.1.0`. Then confirm that an install of `0.0.1` made from `main`
   moves to `0.1.0` with the update commands in the compatibility guide, and
   record whether it needed the reinstall described there.

## Try unreleased work

Adding a clone as a marketplace does not load the clone's files, because the
entry fetches `stable` from GitHub. Load the working tree for one session
instead:

```sh
claude --plugin-dir /path/to/ai-host-kit
```

Claude Code loads a `--plugin-dir` plugin in place, and it replaces an installed
plugin of the same name for that session, as its
[loading reference](https://code.claude.com/docs/en/plugins/loading.md#name-conflicts)
describes. Your installed copy and its settings are unchanged. The install
rehearsal in the compatibility guide points its disposable copy's marketplace
entry at that copy, so it also tests the tracked files rather than `stable`.

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

Dry mode checks that both skills, the script defaults and the harness use
`hosting/place-record.json` for the local draft. It exercises reading and writing
that default path. The suite changes each location independently in a disposable
copy and requires dry mode to fail.

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

## Saved-plan approval checks

Install the pinned OpenTofu outside this repository, then put that folder on
`PATH` alongside the Python environment described above:

```sh
python3 .agents/tools/install-tofu.py /private/tmp/ai-host-kit-tofu
export PATH="/private/tmp/ai-host-kit-tofu:$PATH"
```

Choose a new folder if that binary already exists. The installer downloads
OpenTofu 1.13.2 from the official
[release](https://github.com/opentofu/opentofu/releases/tag/v1.13.2), compares
the published SHA-256 with the checked-in platform pin, then compares the
archive bytes before extracting only the binary. CI uses the same installer
for Linux amd64. This verifies checksums over HTTPS; it does not verify a
release signature. The pins cover macOS and Linux on arm64 and amd64.

`approval-gate.sh` builds real saved plans using only the built-in
`terraform_data` resource in temporary folders. It runs `tofu validate` and
`tofu test` offline. OpenTofu's
[test command](https://opentofu.org/docs/v1.13/cli/commands/test/) supports
mock providers in test files; the ordinary plan command has no mock-provider
option. These tests need neither provider downloads nor mocks. The network
summary case uses `network.show.json`, a constructed fixture in the shape of
`tofu show -json`, because there is no cloud provider schema installed.
Refusal tests use actual encrypted saved plans, not that JSON fixture.

The suite creates synthetic terminal confirmations for local fixtures only.
They are test data, never a person's approval. Protection removals run in
throwaway copies and must fail the same outcome assertions. No test uses a
host, model, cloud account or credential store.

The runtime scripts are canonical in `setup-hosting/scripts/`. The builder
bundles the canonical record reader, approval and plan-time identity schemas,
and `tofu/encryption.tf`
in `setup-hosting/resources/`. Regenerate and save those copies whenever their
sources change. The released project settings are `.claude/settings.json`;
installation must merge them into the user's project settings to take effect.
