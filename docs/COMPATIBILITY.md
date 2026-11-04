# Installing the beta kit

AI Host Kit is beta. Its four commands are `/setup-hosting`, `/go-live`,
`/check-live` and `/change-live`. They report that they are not built yet and
stop. Installation tests do not prove hosting behaviour.

Choose one route per project. Install from the project folder beside AI Build
Kit. Neither route should change application code or project instructions.

## Claude Code plugin

```sh
claude plugin marketplace add gwpicard/ai-host-kit
claude plugin install ai-host-kit@ai-host-kit --scope local
```

Use `/ai-host-kit:setup-hosting`, `/ai-host-kit:go-live`,
`/ai-host-kit:check-live` and `/ai-host-kit:change-live`. The plugin prefix keeps
these separate from AI Build Kit's commands, including its older hosting command.
Each generated command loads the canonical skill from its own plugin folder.

## Shared skills installer

```sh
npx skills add gwpicard/ai-host-kit
```

The installer offers the four canonical skills. Codex, Cursor, Gemini CLI and
Copilot read `.agents/skills/`; Claude Code can read `.claude/skills/` through
the shared installer. The source also carries generated Cursor command files
and Gemini TOML command files for an archive copied as a whole. There is no
separate Codex command adapter.

Older AI Build Kit releases also contain `setup-hosting`. The shared installer
uses a skill's name as its destination and cannot keep two skills of that name
in the same project. Check its overwrite report before proceeding. Use the
Claude plugin route alongside those releases, or wait for the Build Kit
release that retires that skill. Do not overwrite the older skill silently.

## Packaged plugin folder

The release builder adds full copies of the four skills under
`agent-plugin/skills/`. A client of the Agent Plugins format can use that
folder and its `plugin.json`; source keeps only the metadata to avoid maintaining
duplicate skills. No client behaviour is claimed from a metadata check alone.

## Maintainer rehearsal

Use a disposable project and an isolated `CLAUDE_CONFIG_DIR` for plugin tests.
Local marketplace paths let a branch be tested without publication. For shared
skills, use `npx skills add <checkout> -a codex -a claude-code -s '*' -y` in a
separate disposable project. Install AI Build Kit first and inspect both the
command files and installer reports for overwrites. Keep logs outside the
repository; a clash is a failed check, not a successful installation.
