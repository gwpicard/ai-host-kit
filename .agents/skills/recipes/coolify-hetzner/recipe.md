# Coolify on Hetzner

Deploy target: Coolify on Hetzner
Family: Coolify
Command-line tools: OpenTofu 1.13.2, Python 3, Tailscale, Node for the MCP
Last checked: 2026-11-16, public release files, offline mocks and stand-ins only
Last proven: Never
Proven on: No recorded real run
Plan terms: Not checked
Provisioning: tofu/hetzner-server
Regions: Germany and Finland for this server and object storage pair

This recipe stays off the menu. Empty-Place creation has offline checks only.
There is no `PROVEN.md`. Tool-level capabilities remain unknown except for the
recorded UK shortfall in `capabilities.json`. The command sequence and recovery
steps are in [setup.md](setup.md).
The [versioned console page map](console-pages.json) owns every Place console
URL, menu path, button, field and one-time warning. Use `setup.py console
--page provider.entry` to print and open an entry before collecting its value.

### Place prerequisites and local tools

`setup.py preflight` and the start of `plan` read prerequisites before saving
a plan. They check the pinned tools and Python requirements, a signed HEAD of
the state bucket, tag ownership, service auto-approval, administrator SSH,
MagicDNS and HTTPS certificates. Missing or unreadable prerequisites refuse
planning with console guidance and proposed policy lines. An allow-all grant
is reported with a narrower canary proposal. No policy is changed; the person
reviews and approves console changes themselves. Bucket reachability does not
prove versioning, retention or lock behaviour.

The recommended Tailscale read credential uses OAuth with Services Read and
the read scopes required by preflight. See `tailscale.read-credential` in the
map. It is exchanged for a short-lived bearer token. The access-token fallback
carries the creating user's full API permissions and must be revoked after
setup. It is never described as read-only. The separate docktail credential
has write abilities and is never used by preflight.

`setup.py install-tools` installs into `~/.local/share/ai-host-kit/`: OpenTofu
1.13.2 checked against published and pinned SHA-256, the pinned Python wheel
environment, and MCP 3.10.1 installed with scripts disabled and an exact version.
The MCP lock integrity must match `dependencies.json`; npm verifies fetched
tarballs. Existing destinations are refused. These are checksum and version
checks, without release signature verification. Node, npm and Tailscale are
separate system prerequisites. The installer changes no host or console.

### Place provisioning

How it works: The module registers the person's public SSH key, creates a
firewall named `coolify` with no inbound rules, then creates the server with
that firewall attached. IPv6 is disabled. Packages precede the tailnet join;
Coolify 4.7.5 is installed only after a successful join. The installer, both
compose files, environment template and both upgrade scripts come from the same
release tag. Cloud-init verifies each SHA-256 before running anything. It
replaces the scripts' CDN downloads with verified local copies, fixes helper
1.0.19 and disables automatic updates. Installer waits allow ten minutes; a
final Docker health read also allows ten minutes and reports progress.
Download, checksum, installer and health failures stop cloud-init. Later
user-data and firewall-rule changes are ignored by OpenTofu; lane scripts own later rules.
The person supplies the tailnet key through the protected file or a hidden prompt. The
script decodes it into an owner-only file under `/run`, joins with
`--auth-key=file:<path>`, suppresses join diagnostics and deletes the file on
success or failure. A failed join stops installation.
How it is checked: Provider mocks check resources, firewall attachment, closed
inbound rules, IPv4 apt and complete rendering. Local shell stand-ins exercise
file permissions, command arguments, cleanup on both paths and hard failure.
Visible reusable, ephemeral, unapproved and untagged key settings are refused.
The person declares the shortest available expiry: one day, Tailscale's
shortest option. The kit cannot infer key settings from the opaque auth key. Removal tests cover
these guards and the summary warning.
Script: `tofu/hetzner-server/main.tf`, `tofu/hetzner-server/cloud-init.sh`.
Who runs it: The person supplies keys and approves the saved plan. The agent
prepares the reviewable root and summary. No real provisioning is proved.
Ask: Create a single-use, pre-approved key for `tag:server`, not an ephemeral
node, with the shortest available expiry that covers apply. Use one day,
Tailscale's shortest option, and record the actual expiry in setup settings. The pinned provider cannot accept an
ephemeral value in user data. The key therefore reaches Hetzner in user data
and remains in encrypted OpenTofu plans and state. Server cloud-init copies
can remain too. These copies cannot be recalled. The choice is acceptable
because the key is single use, short lived and worthless once used or expired.
Encryption does not remove provider or server copies. Never reuse this key.

### Place state and secrets

How it works: The saved-plan gate supports local state and a restricted S3
configuration for Hetzner Object Storage. Use the shared encryption fragment
and the [approval guide](https://github.com/gwpicard/ai-host-kit/blob/main/.agents/skills/setup-hosting/approval-gate.md). Values come from the protected file described in [setup.md](setup.md), with
terminal prompts for missing values. That guide owns the file format and prompt
visibility table. Storage keys are passed only to OpenTofu and the signed
preflight bucket read. No credential helper,
keychain or profile is read.
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
shown foreground-terminal prompt. The script requires a redirect from `/register` to this
instance's `/login` and an authenticated team read. Other responses, including
HTTP 429, are not proof of a claim. This combines the person's confirmation
with a read-back; it cannot authenticate who answered the local prompt.
The public lane permits only separately approved TCP 80 and/or 443. It checks
ownership, closed registration, the team read, effect approval and firewall
read-back. The internal lane has no public inbound rules.

The installed, unmodified Coolify MCP 3.10.1 runs over stdio with an explicit
tailnet URL and a prompted token. Every Coolify write uses it. Project creation,
docktail definition, each OAuth field, each container start and canary definition
have separate effects and approvals. docktail 1.8.6 runs unmodified as its own
container, with Docker and Tailscale socket access and no published ports.
Its recorded `update_check=true` performs an outbound version check. The
recipe keeps this default because an off switch has not been verified for
1.8.6; the create and start effects disclose it before approval.
The whoami canary has explicit tailnet service port 443 and container port 80.
Before registration, an existing service with different write-once ports is
refused. Before recording, a control-plane read must declare `tcp:443` and the
canary must answer over HTTPS in the joined server's MagicDNS suffix. That
reachability read checks this person's access, not every tailnet grant.

Scope declarations must be exactly `read`, `read:sensitive`, `write`, `deploy`.
These abilities require a token covering the whole team, since server and team
reads are team operations in 4.7.5. `root` is refused in declarations and
returned token-ability metadata. The pinned Coolify API has no current-token abilities endpoint. A team read is not scope
proof; the script reports this limit and the person checks the token in
Coolify. No synthetic response establishes a real token's abilities.
How it is checked: Local transports cover the complete staged command flow,
missing approval, stage order, uncertain writes, claim confirmation, closed
registration, firewall closure, registration ports and read-back. The pinned
MCP has also created and started a synthetic service against a loopback API.
Protection removals cover the tested guards. No provider account is used.
Script: `scripts/setup.py`, `scripts/mcp.py`, `scripts/lane.py`, `scripts/api.py`.
Who runs it: The person approves each effect and keeps the protected file; missing values use terminal prompts.
Ask: Review the tailnet policy, OAuth client abilities and who gains access
before approving a container start. The kit does not edit that policy. A failed
or interrupted write stops the sequence and requires inspection before retrying.

### Place health

How it works: Read-only checks compare outside TCP probes, including 8080, with
the recorded lane, reach Coolify over its tailnet IPv4 address and compare the
installed MCP package version with the pin. Fixed reads over Tailscale SSH
check the Hetzner instance identity, node name and address, temporary-key file
absence, server tag, disabled node-key expiry, Tailscale SSH and completed
cloud-init and a healthy Coolify container. Bootstrap waits up to twenty minutes
for running cloud-init, with progress. Failed rows name a fixed reason; cloud-init
failures include recognised module names without raw logs. Missing reads are
reported separately. Nothing refreshes state, installs a package, calls a write tool or changes a host. A timeout on a TCP connection
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
A completed retirement moves the applied flag, outputs and completed stages
into a retirement entry in setup progress, so a new create can be planned;
an incomplete one leaves the place applied and planning refuses.
The page map owns the separate console review for Object Storage, DNS, the
tailnet machine, service definition, OAuth credentials and fallback API token.
Retirement prints each relevant entry. Each removal needs separate approval.
How it is checked: Stand-ins cover wrong IDs, names and labels, wrong typed
name, non-destroy or extra plan actions, missing resources and remaining volumes.
`place-retirement.sh` runs full and partial retirement through the setup
command and checks the progress outcome, unchanged receipts and the refusals
of a new create for an applied place.
The shared gate checks the actual encrypted plan approval. No real retirement
has been run. There is no export path for tools in this slice; retirement
refuses a record with tools.
Script: `scripts/retire.py`, `scripts/place.py`; `setup-hosting/scripts/approval_gate.py plan-destroy`.
Who runs it: The person types the name and approves the destroy plan separately.
Ask: Review leftovers in Hetzner and the machine in Tailscale before removing
anything else. Keep the encrypted state and its key for recovery.

### Release and rollback facts

The pins were checked on 16 November 2026 against Coolify's stable release and
npm. MCP 3.10.1 is the current release; it includes the service-storage fix and
current client validation. Its unmodified package is rehearsed over stdio
against a loopback API, not a real Coolify instance.

Coolify 4.7.5's tagged OpenAPI documents `GET /applications/{uuid}/rollback-images`
and `POST /applications/{uuid}/rollback`. The read returns `current` and `images`;
each image has a `tag`, `created_at`, `is_current` and `source`. The write takes
`commit`, which must identify an available rollback image or a successful
production deployment, and returns a queued `deployment_uuid`. Tagged routes
require `read` for the list and `deploy` for rollback. This confirms API facts;
no application rollback or recovery drill has been performed.


## Residency

Capabilities: `residency`

How it works: The rented server module accepts German and Finnish locations.
The checked planning facts give no UK location.
How it is checked: Local fit checks report the UK shortfall; module validation
refuses other locations. Placement of actual data has not been checked.
Script: `tofu/hetzner-server/main.tf`.
Who runs it: The maintainer runs mocks; actual placement needs a real run.
