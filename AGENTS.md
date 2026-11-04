# AGENTS.md

Standing instructions for maintaining AI Host Kit itself.

## What this repository is

The maintainer source for a kit that hosts tools in accounts a person or their
organisation controls. It holds canonical skills, checks and release machinery.
It is never a hosted project. Do not run the hosting commands here.

Before editing, read `docs/PHILOSOPHY.md` and the relevant parts of
`docs/MAINTAINING.md`. Check the branch and unsaved work first.

## Where things live

- `.agents/skills/`: the four command stubs, the single source of truth.
- `.agents/tools/`: validation, adapter generation, packaging and rehearsal.
  `kit-inventory.txt` lists the commands.
- `.agents/tests/`: checks of source and distribution boundaries.
- `.agents/maintainer-skills/`: maintainer skills, outside installer discovery
  and the release. Load `writing-review/SKILL.md` by path.
- `.claude/commands/`, `.cursor/commands/`, `.gemini/commands/`: generated
  adapters. Change the source, run `.agents/tools/build-adapters.sh`, and save
  both together. Codex and Copilot read the canonical skills.
- `.claude-plugin/` and `agent-plugin/plugin.json`: plugin metadata.
- `release-manifest.txt`: the complete release allowlist. Maintainer instructions,
  tests, workflows and maintainer skills do not ship.
- `docs/`: philosophy, maintenance, promises, compatibility and sources.

## How changes are made

Work on one agreed slice on a branch from `origin/main`. Open a pull request
with `gh pr create --base main`; a person decides whether to merge it. Never
push directly to `main`, force push, merge a pull request, close an issue or
change repository settings without an explicit instruction allowing it.

A skill instruction earns its place through a mechanism, measured behaviour,
or a judgement. The philosophy explains the test. Keep the commands as stubs
until their behaviour is built and checked. Do not copy AI Build Kit's skills.
Record borrowed work in `docs/SOURCES.md` and preserve its licence.

When a check and an instruction disagree, report the disagreement and trust
the check. Never weaken a check merely to make the work pass.

## Checks

Run `.agents/tools/validate-kit.sh` and `.agents/tests/run-all.sh` after a
change. Each test states on its second line what it guards. Test outcomes and
boundaries, not the wording of a skill.

Before pushing, run `.agents/tools/rehearse-merged-tree.sh` on the saved tree.
The release builder takes a version and a new folder outside this repository.
See `docs/MAINTAINING.md` for the commands and install rehearsals.

## Referring to work

Issue and pull request numbers belong on GitHub, never in tracked files.
Describe the reason so it survives moving a file to another repository.

## Attribution

Commits and pull request text carry only the maintainer's identity. Do not add
co-author trailers, generated-by footers or session links to files, commits,
issues or pull requests. Legal notices and source credits remain intact.
Commit with `git -c user.name="Guillaume Picard" commit`. Keep
`core.hooksPath` set to `.githooks`. The hook removes recognised agent trailers,
standalone footers, address bylines and session links while preserving ordinary
prose and human co-author trailers. [MAINTAINING.md](docs/MAINTAINING.md#prepare-a-clone)
defines its coverage and limits.

## Secrets and external changes

Keys, passwords and tokens never enter tracked files or printed output. Keep
temporary evidence in `.agents/tmp/` or outside the repository, without secrets.
Never discard another person's unsaved work.

Nothing changes real infrastructure without a plan summary the person approves.
The summary names what changes, what becomes reachable, who gains or loses
access, and what cannot be undone. Approval covers the specific change;
permission to investigate an incident is not approval to change the host.
The mechanical approval gate is not built yet, as `docs/PROMISES.md` records.

Publishing releases and changing external data or access need explicit approval.
The current work adds no hosting behaviour and changes no real infrastructure.

## Writing

Before saving prose, load `.agents/maintainer-skills/writing-review/SKILL.md`
and use its embedded mode. Use British spelling, no em or en dashes, and plain
adult prose in text AI Host Kit maintains. The copied `writing-review` skill
is the narrow exception: keep its licence, American spelling and dash examples
as copied. Preserve facts, scope and limits. Maintainer documents may use
precise technical language. Keep one owner per concept and link from elsewhere.
