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
project-founding behaviour left out. The release label check is adapted
further: a missing category produces a notice instead of a failure, and the
categories are enforced when a release is prepared. The commit hook was already present and
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
The adapted launch order, IPv4 apt setting, one-off key-file delivery and
cleanup, person-led administrator claim, tailnet node reads, outside port sample
and retirement ownership checks are from launchpad. Lane separation, explicit docktail
service port and the control-plane write-once port check are from coolify-devops.
Closely adapted files carry source headers. Both MIT notices remain intact.

Earlier kits used `@masonator/coolify-mcp` 3.10.1, MIT, from
[StuMason/coolify-mcp](https://github.com/StuMason/coolify-mcp), as a runtime
dependency for Coolify writes. The kit now calls Coolify's API itself; the
reasons are under [Coolify access route](#coolify-access-route). No code from
that package was copied. Its MIT notice remains in NOTICES.
Declared token scopes do not establish the abilities of a real token; the
pinned Coolify API has no current-token introspection route.

[docktail](https://github.com/marvinvr/docktail) 1.8.6 is an AGPL-3.0 runtime
dependency, run unmodified as its own container. No docktail code is copied,
modified or bundled. The exit route is to remove its service labels and
container after a separate approval and manage Tailscale Services directly.
The kit does not depend on a patched docktail or distribute its image.

[Coolify v4.7.5](https://github.com/coollabsio/coolify/tree/v4.7.5), commit
`378ce3735c4522ebb6b68e93b909b0511f278763`, supplies the fresh-install files.
They are fetched on the new server, never bundled here. `dependencies.json`
records the tagged URLs and SHA-256 of the installer, upgrade and PostgreSQL
upgrade scripts, both compose files and the production environment template.
Cloud-init verifies them before use, then changes the installer and upgrade
script locally to copy the verified files. It replaces live version discovery
with Coolify 4.7.5 and helper 1.0.19, extends installer waits and disables automatic
updates. Docker installation and operating-system packages retain upstream
behaviour; this pins Coolify's release files, not the whole machine image.
Coolify's Apache-2.0 licence is preserved in NOTICES, including for these local
changes. Its tagged OpenAPI and routes confirm rollback and token abilities;
the recipe owns those facts and their limits. No Coolify source is bundled.

## Coolify access route

The Place stages, and the later slices for going live, changing a live tool,
backups and previews, call Coolify's REST API directly from the recipe's
`scripts/api.py`. The `@masonator/coolify-mcp` package was removed. Coolify's
built-in MCP server is not used by the scripted stages; it remains an option
for a later, separately approved, read-only agent surface.

The reasons come from reading the Coolify v4.7.5 source (the commit above),
[laravel/mcp](https://github.com/laravel/mcp) 1.0.1 and the installed
coolify-mcp 3.10.1 package. Nothing was run against a live Coolify.

- Both MCP routes end in the same REST controllers. Coolify's built-in server
  sends every write through the REST routes and their middleware
  (`app/Mcp/Concerns/CallsRestApi.php`), and the package calls the same
  routes over HTTP. For scripted stages, MCP adds a layer but no ability.
- Every current and planned need has a REST route in `routes/api.php`:
  projects, services with Compose, service variables and start or stop;
  applications from a Dockerfile or image, with runtime-only secrets;
  PostgreSQL creation, deploys, logs, rollback, backups including run now,
  and previews. Extra PostgreSQL roles have no route in any of the three
  options and need `psql` over Tailscale SSH.
- The dropped build-time flags are server behaviour, not a package fault.
  `ServicesController::create_env` and `update_env_by_uuid` read only key,
  value, literal, multiline, shown-once and comment, whichever client sends
  the request. Calling the API directly lets the kit refuse those flags
  instead of sending them unnoticed.
- Supply chain: the package has one maintainer and a stated tested range of
  Coolify 4.0 to 4.3 (`dist/lib/tested-range.js`), while the kit pins 4.7.5.
  Its four runtime dependencies use caret ranges, so they were not pinned. It
  needed Node and npm on the person's computer, and a third-party process held
  the full-team token.
- Token exposure stays the same. The REST calls use the same tailnet path to
  port 8000, with the same token, that the kit already used for reads.

The kit now owns its request shapes. They were taken from the 4.7.5
controllers, and each Coolify write stage first reads the running version and
refuses any other. The package's own mapping confirmed one detail: it
base64-encodes `docker_compose_raw` before `POST /services`, which the 4.7.5
route requires. The 4.7.5 rate limit on these writes, 200 a minute from the
`api` throttle, is inferred from the code and has not been tested. A
supervised run on a fresh place still has to confirm the switch end to end.
