# AI Host Kit

> **Beta and experimental.** AI Host Kit is under active development. Its
> commands, file formats and host recipes will change without notice, and no
> host is proven yet. Do not rely on it for a tool people depend on.

AI Host Kit will put a tool built with [AI Build Kit](https://github.com/gwpicard/ai-build-kit)
live on the infrastructure you choose, in accounts you or your organisation
control, and look after it there.

AI Build Kit owns what the tool is: its code, its tests and its records. It
writes a handover file that says what the tool needs to run. AI Host Kit will read
that file, set up the place where your tools run, put each tool live, and
keep it recoverable: backups with a tested restore, a way back to an earlier
version, and checks that never change anything.

## Commands

| Command | When you reach for it |
|---|---|
| `/setup-hosting` | You need somewhere to run your tools, or you already have hosting you want the kit to look after |
| `/go-live` | A tool is ready to go live for the first time |
| `/check-live` | You want to know whether a live tool is healthy. It will only read, and never change anything |
| `/change-live` | Something about a live tool needs to change: undo a release, secrets, access, a restore test, a move, or retiring it |

The choice step in `/setup-hosting` compares the handover with stub recipes,
suggests a host and saves a local choice record. The experimental Coolify on
Hetzner path can then prepare an empty place through separate approvals; only
offline checks have run. `/check-live` can run the Coolify on Hetzner recipe's sampled
read-only Place checks. Tool health checks, `/go-live` and `/change-live` remain
stubs. The [offline Place recipe](.agents/skills/recipes/coolify-hetzner/recipe.md)
records its commands and live-check limits. No host is proven.

## Install the beta

From your project folder, choose one route. For Claude Code:

```sh
claude plugin marketplace add gwpicard/ai-host-kit
claude plugin install ai-host-kit@ai-host-kit --scope local
```

Its commands use the `ai-host-kit:` prefix, such as `/ai-host-kit:check-live`.
For Codex, Cursor, Gemini CLI and other coding agents:

```sh
npx skills@1.7.6 add gwpicard/ai-host-kit --skill go-live check-live change-live
```

The shared route leaves out `/setup-hosting` because AI Build Kit still owns
a skill of that name and the installer would replace it. This temporary limit
ends when AI Build Kit retires its command. The Claude plugin keeps all four.
See [compatibility](docs/COMPATIBILITY.md) for the limits and agent map.

## Credits

AI Host Kit adapts ideas and code from
[coolify-devops](https://github.com/KasperHonore/coolify-devops) by Kasper
Honore and from [coolify-launchpad](https://github.com/gwpicard/coolify-launchpad),
both under the MIT licence. [NOTICES](NOTICES) keeps their copyright lines. If
you want to host on Coolify specifically, coolify-devops is focused on that.
Neither project endorses AI Host Kit.

## Licence

MIT. See [LICENSE](LICENSE).
