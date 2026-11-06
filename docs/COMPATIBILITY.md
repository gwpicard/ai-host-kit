# Installing the beta kit

AI Host Kit is beta. Its four commands are `/setup-hosting`, `/go-live`,
`/check-live` and `/change-live`. The local choice step in `/setup-hosting` and sampled Coolify Place reads
in `/check-live` are built. Creating a place, tool health, `/go-live` and
`/change-live` remain unbuilt. Installation
tests do not prove hosting behaviour.

Choose one route per project. Install from the project folder beside AI Build
Kit. Neither route should change application code or project instructions.

## Claude Code plugin

```sh
claude plugin marketplace add gwpicard/ai-host-kit
claude plugin install ai-host-kit@ai-host-kit --scope local
```

Use `/ai-host-kit:setup-hosting`, `/ai-host-kit:go-live`,
`/ai-host-kit:check-live` and `/ai-host-kit:change-live`. The plugin prefix keeps
these separate from AI Build Kit's commands, including its hosting command.
Each generated command loads the canonical skill from its own plugin folder.

## Shared skills installer

```sh
npx skills@1.7.6 add gwpicard/ai-host-kit --skill go-live check-live change-live
```

Installer version `1.7.6` was checked. Its `--skill` option selects skills by
name and accepts several names after one option. The command above installs
only `/go-live`, `/check-live` and `/change-live`. Choose your coding agents
when prompted. Codex, Cursor, Gemini CLI and Copilot read `.agents/skills/`;
Claude Code can read `.claude/skills/` through the shared installer. The source
also carries generated Cursor command files
and Gemini TOML command files for an archive copied as a whole. There is no
separate Codex command adapter.

AI Build Kit still has `/setup-hosting`. The shared installer uses a skill's
name as its destination, so installing AI Host Kit's skill of that name would
replace AI Build Kit's. Leave it out until AI Build Kit retires its command;
the shared route will then gain AI Host Kit's `/setup-hosting`. The Claude
plugin route keeps all four commands now because its prefix avoids the clash.

The pinned installer's [selection code](https://github.com/vercel-labs/skills/blob/v1.7.6/src/add.ts)
and [destination code](https://github.com/vercel-labs/skills/blob/v1.7.6/src/installer.ts)
define this behaviour. Do not select all skills with `--skill '*'` beside a
Build Kit release that still has `/setup-hosting`.

## Packaged plugin folder

The release builder adds full copies of the four command skills and the
`host-fit` background skill under
`agent-plugin/skills/`. A client of the Agent Plugins format can use that
folder and its `plugin.json`; source keeps only the metadata to avoid maintaining
duplicate skills. No client behaviour is claimed from a metadata check alone.

The choice script needs Python 3 and the pinned packages in the host-fit
skill's `resources/schema-requirements.txt`. Its schemas, reader and recipe declarations and runtime files are bundled inside that skill, so it does not need the maintainer
tools. `build-adapters.sh` refreshes these copies from their canonical files.
The shared install route above still omits host choice while the command
name belongs to AI Build Kit.

## Maintainer rehearsal

Run from the maintainer source with a Build Kit checkout that still contains
`setup-hosting` and a new output folder outside both repositories:

```sh
python3 .agents/tools/rehearse-installs.py /path/to/ai-build-kit /private/tmp/host-kit-installs
```

This needs Node.js, npm, network access and Claude Code. It copies tracked files
to throwaway folders and isolates Claude configuration and the npm cache.
It installs AI Build Kit first through each route, then checks that the plugin
lists four prefixed Host Kit commands and the shared installer adds exactly
three skills. It compares Build Kit's installed files before and after,
including `setup-hosting`, and leaves logs in the output folder. It does not
invoke a model or test hosting behaviour. A missing prerequisite is an
incomplete check, never a pass.
