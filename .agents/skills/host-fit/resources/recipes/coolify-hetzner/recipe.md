# Coolify on Hetzner

Deploy target: Coolify on Hetzner
Family: Coolify
Command-line tools: OpenTofu 1.13.2, Python 3, Tailscale, Node for the MCP
Last checked: 2026-11-06, offline provider mocks and stand-ins only
Last proven: Never
Proven on: No recorded real run
Plan terms: Not checked
Provisioning: tofu/hetzner-server
Regions: Germany and Finland for this server and object storage pair

This recipe stays off the menu. Place plumbing has offline checks, but tailnet
bootstrap, claiming the first administrator and the complete docktail/MCP write
path are unfinished. There is no `PROVEN.md`. Tool-level capabilities remain
unknown except for the recorded UK shortfall in `capabilities.json`.

### Place provisioning

How it works: The module creates an existing public SSH key registration, a
firewall named `coolify` with no inbound rules, then a server with that firewall
attached at creation. IPv6 is disabled. The server waits for a tailnet address
before installing Coolify 4.3.23. It fails after ten minutes without one. Later
user-data and firewall rule changes are ignored by OpenTofu; lane scripts own
subsequent rules. Never use a separate, later firewall attachment.
How it is checked: Provider-mocked plans check the three resources, the attached
firewall, no inbound rules, IPv4 apt and fully rendered cloud-init. Mutations
remove each tested protection in a throwaway copy.
Script: `tofu/hetzner-server/main.tf`, `tofu/hetzner-server/tests/fresh.tftest.hcl`.
Who runs it: The maintainer runs offline checks. No real provisioning yet.
Ask: Agree a secret delivery route before creating anything. The pinned hcloud
provider cannot accept an ephemeral value for `user_data`. It hashes that field
in state, but ordinary input values can remain in a plan and cloud-init caches
and provider metadata can retain the original script. State encryption does
not remove those copies. This module therefore contains no tailnet auth key.
A hidden console enrolment step is a possible alternative, pending agreement.

### Place state and secrets

How it works: The saved-plan gate supports local state and a restricted S3
configuration for Hetzner Object Storage. Use the shared encryption fragment
and the [approval guide](https://github.com/gwpicard/ai-host-kit/blob/main/.agents/skills/setup-hosting/approval-gate.md). Storage keys
are entered through a hidden foreground-terminal prompt and passed only in the
OpenTofu child environment. No credential helper, keychain or profile is read.
The key custodian keeps the state passphrase; losing it makes state unreadable.
How it is checked: A local S3-compatible HTTP stand-in exercises initialisation,
encrypted plans and state, locking, workspace selection, approval refusal and
exact approved apply. Identity checks bind endpoint, bucket, key, region, prefix,
complete backend metadata and a digest incorporating the supplied credentials.
This does not establish Hetzner's locking or bucket versioning behaviour.
Script: `setup-hosting/scripts/init-s3.py`, `setup-hosting/scripts/approval_gate.py`.
Who runs it: The person supplies keys and approves; the agent prepares summaries.
Ask: The person creates the first storage key and bucket in their console.

### Place lanes, administration and docktail

How it works: SSH and Coolify administration stay on the tailnet. The internal
lane has no public inbound rule. The public lane permits only the explicitly
approved TCP ports among 80 and 443. A lane change checks resource IDs, names
and ownership labels, reads an authenticated Coolify team over the tailnet,
checks the exact effect approval, then reads the firewall rules back. This
account read does not prove who claimed the first administrator.
The docktail library specifies an unmodified `ghcr.io/marvinvr/docktail:1.8.6`
container and explicit `service-port=443` labels. It refuses an existing service
definition with different ports and requires a control-plane read-back of
`tcp:443` and readiness. It does not yet install or drive that container.
`scoped_mcp` pins `@masonator/coolify-mcp@3.9.0` and accepts declarations of
`read`, `read:sensitive`, `write`, `deploy` only. It refuses `root`. It does
not inspect a real token's abilities or start the MCP. The complete MCP write
transport and first-admin claim remain blocked, rather than being presented
as finished access controls.
How it is checked: Stand-ins exercise lane writes, ownership refusal, missing
or changed effect approval, docktail port refusal and read-back, and pin/scope
declarations. The cloud route adapter uses an in-memory HTTP transport.
Script: `scripts/lane.py`, `scripts/place.py`, `scripts/api.py`.
Who runs it: The person approves each named effect. No live script runs yet.
Ask: The first administrator must be claimed over the tailnet before a public
lane opens. This remains a manual real-run checkpoint, not a proved mechanism.

### Place health

How it works: Read-only checks compare outside TCP probes, including 8080, with
the recorded lane, reach Coolify over its tailnet IPv4 address and compare the
installed MCP package version with the pin. Nothing refreshes state, installs
a package, calls a write tool or changes a host. A timeout on a TCP connection
is treated as unreachable; a passing tailnet read is also required. This is a
finite port sample, not a scan of every port or a tailnet policy audit.
How it is checked: Stand-ins cover matching, unexpected open ports, wrong
versions and missing reads. Protection removals detect a missing 8080 probe.
Script: `scripts/check.py`.
Who runs it: `/check-live`, using the person's read token and installed MCP path.

### Place retirement and record

How it works: The record's `phase: place` describes only an empty place. It
cannot claim backups, alerts or live tools. IDs, addresses and exact version
pins are recorded; no key is recorded. The retire wrapper compares all three
owned deletions in an encrypted saved destroy plan, checks live ownership,
requires the typed place name and calls the saved-plan apply gate. It then
lists remaining Cloud resource IDs, including resources the kit never owned.
Object Storage, DNS and the tailnet machine need separate console review.
How it is checked: Stand-ins cover wrong IDs, names and labels, wrong typed
name, non-destroy or extra plan actions, missing resources and remaining volumes.
The shared gate checks the actual encrypted plan approval. No real retirement
has been run. There is no export path for tools in this slice; retirement
refuses a record with tools.
Script: `scripts/retire.py`, `scripts/place.py`; `setup-hosting/scripts/approval_gate.py plan-destroy`.
Who runs it: The person types the name and approves the destroy plan separately.
Ask: Review leftovers in Hetzner and the machine in Tailscale before removing
anything else. Keep the encrypted state and its key for recovery.

## Residency

Capabilities: `residency`

How it works: The rented server module accepts German and Finnish locations.
The checked planning facts give no UK location.
How it is checked: Local fit checks report the UK shortfall; module validation
refuses other locations. Placement of actual data has not been checked.
Script: `tofu/hetzner-server/main.tf`.
Who runs it: The maintainer runs mocks; actual placement needs a real run.
