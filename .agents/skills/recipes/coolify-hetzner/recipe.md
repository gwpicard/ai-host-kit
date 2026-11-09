# Coolify on Hetzner

Deploy target: Coolify on Hetzner
Family: Coolify
Command-line tools: OpenTofu 1.13.2, Python 3, Tailscale, Node for the MCP
Last checked: 2026-11-09, offline provider mocks and stand-ins only
Last proven: Never
Proven on: No recorded real run
Plan terms: Not checked
Provisioning: tofu/hetzner-server
Regions: Germany and Finland for this server and object storage pair

This recipe stays off the menu. Empty-Place creation has offline checks only.
There is no `PROVEN.md`. Tool-level capabilities remain unknown except for the
recorded UK shortfall in `capabilities.json`. The command sequence and recovery
steps are in [setup.md](setup.md).

### Place provisioning

How it works: The module registers the person's public SSH key, creates a
firewall named `coolify` with no inbound rules, then creates the server with
that firewall attached. IPv6 is disabled. Packages precede the tailnet join;
Coolify 4.3.23 is installed only after a successful join. Later user-data and
firewall-rule changes are ignored by OpenTofu; lane scripts own later rules.
The person supplies the tailnet key through a hidden foreground prompt. The
script decodes it into an owner-only file under `/run`, joins with
`--auth-key=file:<path>`, suppresses join diagnostics and deletes the file on
success or failure. A failed join stops installation.
How it is checked: Provider mocks check resources, firewall attachment, closed
inbound rules, IPv4 apt and complete rendering. Local shell stand-ins exercise
file permissions, command arguments, cleanup on both paths and hard failure.
Visible reusable, ephemeral, unapproved and untagged key settings are refused.
The person declares the shortest available expiry, aiming for one hour; the
kit cannot infer key settings from the opaque auth key. Removal tests cover
these guards and the summary warning.
Script: `tofu/hetzner-server/main.tf`, `tofu/hetzner-server/cloud-init.sh`.
Who runs it: The person supplies keys and approves the saved plan. The agent
prepares the reviewable root and summary. No real provisioning is proved.
Ask: Create a single-use, pre-approved key for `tag:server`, not an ephemeral
node, with the shortest expiry that covers apply. Aim for one hour and record
the actual expiry in setup settings. The pinned provider cannot accept an
ephemeral value in user data. The key therefore reaches Hetzner in user data
and remains in encrypted OpenTofu plans and state. Server cloud-init copies
can remain too. These copies cannot be recalled. The choice is acceptable
because the key is single use, short lived and worthless once used or expired.
Encryption does not remove provider or server copies. Never reuse this key.

### Place state and secrets

How it works: The saved-plan gate supports local state and a restricted S3
configuration for Hetzner Object Storage. Use the shared encryption fragment
and the [approval guide](https://github.com/gwpicard/ai-host-kit/blob/main/.agents/skills/setup-hosting/approval-gate.md). Storage keys
are entered through a hidden foreground-terminal prompt and passed only in the
OpenTofu child environment. No credential helper, keychain or profile is read.
The key custodian keeps the state passphrase; losing it makes state unreadable.
How it is checked: A local S3-compatible HTTP stand-in exercises initialisation,
encrypted plans and state, locking, workspace selection, approval refusal and
exact approved apply. The setup runner also binds a digest of the prompted
project token to the saved-plan checksum and refuses a different token at apply
or retirement. Identity checks bind endpoint, bucket, key, region, prefix,
complete backend metadata and a digest incorporating the supplied credentials.
This does not establish Hetzner's locking or bucket versioning behaviour.
Script: `setup-hosting/scripts/init-s3.py`, `setup-hosting/scripts/approval_gate.py`.
Who runs it: The person supplies keys and approves; the agent prepares summaries.
Ask: The person creates the first storage key and bucket in their console.

### Place lanes, administration and docktail

How it works: SSH and Coolify administration stay on the tailnet. The person
approves the claim effect, creates the first administrator in Coolify over the
tailnet, enables two-factor authentication and confirms the claim through the
hidden prompt. The script requires a redirect from `/register` to this
instance's `/login` and an authenticated team read. Other responses, including
HTTP 429, are not proof of a claim. This combines the person's confirmation
with a read-back; it cannot authenticate who answered the local prompt.
The public lane permits only separately approved TCP 80 and/or 443. It checks
ownership, closed registration, the team read, effect approval and firewall
read-back. The internal lane has no public inbound rules.

The installed, unmodified Coolify MCP 3.9.0 runs over stdio with an explicit
tailnet URL and a prompted token. Every Coolify write uses it. Project creation,
docktail definition, each OAuth field, each container start and canary definition
have separate effects and approvals. docktail 1.8.6 runs unmodified as its own
container, with Docker and Tailscale socket access and no published ports.
The whoami canary has explicit tailnet service port 443 and container port 80.
Before registration, an existing service with different write-once ports is
refused. Before recording, a control-plane read must declare `tcp:443` and the
canary must answer over HTTPS in the joined server's MagicDNS suffix. That
reachability read checks this person's access, not every tailnet grant.

Scope declarations must be exactly `read`, `read:sensitive`, `write`, `deploy`.
`root` is refused in declarations and returned token-ability metadata. The pinned
Coolify API has no current-token abilities endpoint. A team read is not scope
proof; the script reports this limit and the person checks the token in
Coolify. No synthetic response establishes a real token's abilities.
How it is checked: Local transports cover the complete staged command flow,
missing approval, stage order, uncertain writes, claim confirmation, closed
registration, firewall closure, registration ports and read-back. The pinned
MCP has also created and started a synthetic service against a loopback API.
Protection removals cover the tested guards. No provider account is used.
Script: `scripts/setup.py`, `scripts/mcp.py`, `scripts/lane.py`, `scripts/api.py`.
Who runs it: The person approves each effect and enters secrets directly.
Ask: Review the tailnet policy, OAuth client abilities and who gains access
before approving a container start. The kit does not edit that policy. A failed
or interrupted write stops the sequence and requires inspection before retrying.

### Place health

How it works: Read-only checks compare outside TCP probes, including 8080, with
the recorded lane, reach Coolify over its tailnet IPv4 address and compare the
installed MCP package version with the pin. Fixed reads over Tailscale SSH
check the Hetzner instance identity, node name and address, temporary-key file
absence, server tag, disabled node-key expiry, Tailscale SSH and completed
cloud-init. Missing reads are reported separately. Nothing refreshes state, installs
a package, calls a write tool or changes a host. A timeout on a TCP connection
is treated as unreachable; a passing tailnet read is also required. This is a
finite port sample, not a scan of every port or a tailnet policy audit.
How it is checked: Stand-ins cover matching, unexpected open ports, wrong
versions, node facts and missing reads. Protection removals detect a missing
8080 probe and removed node guards.
Script: `scripts/check.py`.
Who runs it: `/check-live`, using the person's read token and installed MCP path.

### Place retirement and record

How it works: The record's `phase: place` describes only an empty place. It
cannot claim backups, alerts or live tools. IDs, addresses and exact version
pins are recorded; no key is recorded. Setup retains non-secret progress and
writes the final `hosting/place-record.json` only after the approved stages
and canary reads. It refuses to overwrite a changed choice. Coolify project,
docktail and canary IDs are recorded as plumbing, with the tailnet service name. The retire wrapper compares all three
owned deletions in an encrypted saved destroy plan, checks live ownership,
requires the typed place name and calls the saved-plan apply gate. It then
lists remaining Cloud resource IDs, including resources the kit never owned.
Object Storage, DNS, the tailnet machine and service definition need separate
console review and separate approval for removal.
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
