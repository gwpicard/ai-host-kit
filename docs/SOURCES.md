# Sources

AI Host Kit adapts ideas from [coolify-devops](https://github.com/KasperHonore/coolify-devops)
and [coolify-launchpad](https://github.com/gwpicard/coolify-launchpad), both MIT
licensed. Neither project endorses AI Host Kit. Their copyright notices and
MIT texts remain in [NOTICES](../NOTICES).

coolify-devops informs the planned separation of public and private access,
restricted token scopes, preview isolation, rollback and live checks.
coolify-launchpad informs the planned launch order, private administration,
outside port checks, hidden token entry and retirement checks. The Place module and operation libraries now have offline checks;
[PROMISES.md](PROMISES.md) records their limits and the remaining live gaps.

[AI Build Kit](https://github.com/gwpicard/ai-build-kit), MIT, supplies the
working conditions: maintainer instructions, generated command adapters,
release allowlist, source checks, test runner, merged-tree rehearsal, issue
forms and pull request checks. They are adapted to hosting, with build and
project-founding behaviour left out. The commit hook was already present and
is unchanged. The published handover schema is vendored unchanged under
`contracts/ai-build-kit/`, with its origin in `upstream.json` and its MIT notice
in [NOTICES](../NOTICES). No installable Build Kit skills are copied.

The maintainer-only writing-review skill is copied from AI Build Kit with its
MIT licence intact. Its pattern guidance comes from
[Humanizer](https://github.com/blader/humanizer/tree/v2.9.1), with the
maintainer's writing framework. It is excluded from installation and releases.

Legal notices and these source credits identify borrowed work. They do not
attribute commits or reviews to a coding agent.

The Place work studied coolify-launchpad v0.1.1, commit
`d8b5813ad5c6728057b7c006a8371bdd0b1183ed`, read only from the maintainer's
checkout, and coolify-devops v0.9.0, commit
`20809551215f442379238ea20338364d96ab765e`, read from its public repository.
The adapted launch order, IPv4 apt setting, outside port sample and retirement
ownership checks are from launchpad. Lane separation, explicit docktail
service port and the control-plane write-once port check are from coolify-devops.
Closely adapted files carry source headers. Both MIT notices remain intact.

`@masonator/coolify-mcp` 3.9.0 is the planned MIT runtime dependency, from
[StuMason/coolify-mcp](https://github.com/StuMason/coolify-mcp). Its npm tarball
was verified against its published SHA-512 integrity before reading. The exact
pin and integrity are in the recipe's `dependencies.json`; no MCP source is
copied into the runtime. Its MIT notice is included in NOTICES. Declared token
scopes do not establish the abilities of a real token. Complete MCP transport
and the first-admin claim are still unfinished.

[docktail](https://github.com/marvinvr/docktail) 1.8.6 is an AGPL-3.0 runtime
dependency, run unmodified as its own container. No docktail code is copied,
modified or bundled. The exit route is to remove its service labels and
container after a separate approval and manage Tailscale Services directly.
The kit does not depend on a patched docktail or distribute its image.
