# Create and retire an empty place

This is the experimental Coolify on Hetzner sequence. It has offline evidence
only. It is not permission to contact a provider. Keep this recipe off the
proven menu until the required real runs and later tool outcomes are recorded.
Run it from the person's private place repository, never the kit source.

The person first provides a recorded Coolify on Hetzner choice in
`hosting/place-record.json`, their organisation and region, an existing SSH
public key, the server type, an existing Object Storage bucket and key path,
and the name of the state-key custodian. Copy `setup.example.json` into that
repository and replace its non-secret example settings. Never put a key,
password or token in that file. Record the actual tailnet key expiry and
confirm that it uses the shortest available expiry that covers apply: one day,
Tailscale's shortest option.

Console work has its own approvals. The person approves creating a project
token for the selected Hetzner project, a storage key for the selected bucket,
and a single-use, pre-approved `tag:server` Tailscale auth key for a persistent
node. The auth key must not be reusable or ephemeral. The person reviews the
tailnet's server SSH grants, MagicDNS, HTTPS and service approval policy. A
separate approval covers creating the docktail OAuth client and its abilities
to register services. Keep its ID and secret in the person's password manager.
The person also provides a read OAuth credential for Tailscale, a test
domain for the later public-lane run and the separately kept state passphrase.
This empty-place canary uses the tailnet domain; the test domain is not changed.

Copy `secrets.example.env` to `~/.config/ai-host-kit/places/<place-name>.env`,
outside every Git repository. Set mode 600 with `chmod 600` before adding
values. The file must be a regular file owned by you, with no symlink and no
group or other permissions. The kit checks these conditions before reading it.
The [console page map](console-pages.json) owns URLs, menu paths, buttons,
fields and one-time value warnings, keyed by provider and checked version.
Before collecting any console value, run the relevant entry through
`python3 "$RECIPE/scripts/setup.py" console --page provider.entry`.
It prints the entry and opens its URL with the system opener. Coolify entries
also take `--address` with the checked tailnet IPv4 address and `--config`
with the non-secret setup settings. Missing-value prompts do the same.
The template names the entry for each value. Use plain `KEY=value` lines and full-line comments. There is
no shell expansion, quote removal or `export` syntax. Do not source this file.
An optional `op://vault/item/field` value is resolved by `op read`; install and
unlock the 1Password CLI first. Its output and errors are withheld.

`setup.json` names the non-secret path in `secrets`; omission uses the default
above. `root` retains that path in progress. Every command accepts `--secrets`
to override it. `check.py`, `lane.py` and standalone `retire.py` also read the
path from `--config` (default `setup.json`), then use the place-name default.
A missing file or blank field falls back to the terminal prompt. Unsafe files
are refused. File values are never printed. Hidden prompts confirm only the
length and last four characters, withholding the suffix for four or fewer
characters. All local inputs are collected before recording an attempt or
spending approval. An input refusal leaves neither a receipt nor an uncertain
marker. A write or failed read-back after an attempt still needs inspection.

With all required values in the file, `init`, `plan`, `plan-destroy`, `summary`,
`bootstrap`, `discover` and `check.py` can run from the coding agent's shell.
Approvals and typed claim and retirement confirmations still require the
person's foreground terminal. See the [approval limits](https://github.com/gwpicard/ai-host-kit/blob/main/docs/PROMISES.md#protected-place-secrets)
for the Claude Code deny rule and the limits of that boundary.

### Prompt visibility

This table owns prompt visibility for the Place flow. Shown input is checked
for secret-shaped text before being displayed. This can reject harmless text
and cannot detect every secret. Each prompt names its visibility.

| Input | Visibility |
|---|---|
| State passphrase, Hetzner project token, storage secret key, one-off Tailscale auth key, Coolify team token, Tailscale API token, read and docktail OAuth secrets | Hidden; length and last four characters only after entry |
| Storage access key, read and docktail OAuth client IDs | Shown identifiers |
| Place name at retirement, approval checksum and words, `claimed <place-name>` | Shown; foreground terminal required |

After approval for local downloads and installation, run
`python3 "$RECIPE/scripts/setup.py" install-tools`. It installs OpenTofu
1.13.2, the pinned Python environment and `@masonator/coolify-mcp` 3.10.1 under
`~/.local/share/ai-host-kit/`. It compares published and pinned OpenTofu
checksums, permits only Python wheels and verifies installed versions, and uses
`npm install --ignore-scripts --save-exact` with the lock-file integrity in
`dependencies.json`. It reports each verification and refuses existing tool
destinations. It checks checksums over HTTPS, without release signatures.
Install Node, npm and Tailscale separately. Put the printed opentofu and
venv/bin folders on PATH and use the printed MCP package path.

Use the `tailscale.read-credential` entry for the recommended read OAuth route.
It has Services Read plus the read scopes required for policy, DNS and HTTPS
preflight. The kit exchanges it for a short-lived token with only the command's
read scopes. Keep it separate from docktail's write credential. The
`tailscale.access-token` fallback has the creating user's full API permissions,
including permitted writes and deletions. It is not read-only. Use one day and
revoke it after setup. An OAuth failure never silently falls back to that token.

docktail 1.8.6 runs unmodified with its observed `update_check=true`: an outbound
version check, not an automatic upgrade. This recipe retains it because an off
switch has not been verified against this version. The create and start effects
name that traffic before approval. No model or agent is installed on the server.

Set these non-secret paths in the person's shell. The kit chooses new numbered
plan and approval files under `~/.local/share/ai-host-kit/plans/<place>/`,
outside every repository. It records the current paths in the progress file;
shell variables do not select them. Keep encrypted state in the selected
bucket, with its passphrase elsewhere.
`MCP_PACKAGE` is the installed package's `package.json`, not a command.

```sh
cd "$PLACE"
SETUP="$RECIPE/scripts/setup.py"
PROGRESS="$PLACE/hosting/place-progress.json"
```

`PLACE`, `RECIPE`, `GATE` and `MCP_PACKAGE` are supplied as
absolute paths by the person. `RECIPE` is the installed host-fit recipe folder;
`GATE` is the installed setup-hosting scripts folder.
`SERVER_UUID` and `DESTINATION_UUID` are non-secret values read from the newly
created place, not invented in advance.

## First real run: create

1. Prepare the local root for review. This creates no provider resources.

   ```sh
   python3 "$SETUP" root --config "$PLACE/setup.json" --progress "$PROGRESS"
   ```

   Review `hosting/tofu/`, its module snapshot and `backend.json`. The person
   approves initialisation against that exact bucket, key, endpoint and region,
   then runs the next command. It reads the state passphrase
   and storage key pair from the protected file, prompting for missing values. It does not create the bucket or migrate state.

   ```sh
   python3 "$SETUP" init --progress "$PROGRESS"
   ```

2. After permission for provider reads, run preflight, then save a real plan
   and show its summary. `plan` repeats preflight before collecting the auth key
   or saving any plan. Preflight checks pinned tools, the signed bucket HEAD
   read, tag ownership, service auto-approval, administrator root SSH,
   MagicDNS and HTTPS certificates. Missing prerequisites refuse planning and
   name the map entry and policy lines. An allow-all grant is reported with a
   narrower canary proposal; it is not edited. Adding a narrow grant does not
   cancel an existing broad grant. The person reviews and approves each policy
   change in the console. Bucket reachability does not prove versioning,
   retention, object-write permissions or lock behaviour.
   The plan command reads the passphrase, project token, one-off tailnet
   key and storage pair from the protected file. Summary and approval need the
   passphrase and same storage pair. Missing values use prompts. The one-off key is in Hetzner user data and encrypted plans
   and state; server cloud-init copies can remain. The summary says these
   copies cannot be recalled and why a spent or expired key is worthless.

   ```sh
   python3 "$SETUP" preflight --progress "$PROGRESS" --mcp-package "$MCP_PACKAGE"
   python3 "$SETUP" plan --progress "$PROGRESS" --mcp-package "$MCP_PACKAGE"
   python3 "$SETUP" summary --progress "$PROGRESS"
   ```

   The summary shows resource names, server type, location, image, labels,
   IPv4 and IPv6 settings, and firewall ports and sources. Secrets, user data
   and sensitive or unknown values stay withheld. It ends with the checksum.
   When a newer plan supersedes one for the same place and operation, the kit
   offers cleanup. Run `prune-plans --progress "$PROGRESS"` through `"$SETUP"`
   to review the files. Enter keeps them; typing `delete` removes only the
   listed plans and identity sidecars. A plan can hold a spent key. Approval
   records and receipts remain. Cleanup never runs automatically.

3. The person reviews the exact summary and runs approval themselves, typing
   its checksum alone, shown as typed. Enter alone cancels. Their own words
   are optional and are shown after checks for secret-shaped text. Only that
   saved plan may be applied. Apply
   reads the passphrase, project token and storage pair from the same file.

   ```sh
   python3 "$SETUP" approve --progress "$PROGRESS"
   python3 "$SETUP" apply --progress "$PROGRESS"
   ```

4. Cloud-init takes several minutes. After permission for reads, run bootstrap.
   It finds the approved node name in the person's local Tailscale client and
   waits for cloud-init to finish. No match or several matching nodes stops it.
   This step neither fixes the node nor installs anything.

   ```sh
   python3 "$SETUP" bootstrap --progress "$PROGRESS"
   ```

   If needed, supply a checked tailnet IPv4 address with `--address`.
   Bootstrap still requires the
   Hetzner instance ID to match, the node name and address to match, the key
   file to be gone, `tag:server`, disabled node-key expiry, Tailscale SSH and
   completed cloud-init and a healthy Coolify container. It waits up to twenty
   minutes for cloud-init, with progress. A failed row reports its reason and,
   where recognised, the failed cloud-init module. A missing read stops the flow.

5. Prepare and approve the first-administrator effect. The person runs the
   approval command, then the run command. The runner reads the Hetzner project
   token, resolves any stored Coolify token and checks the closed firewall
   before recording an attempt. Under
   that approval it restarts the `coolify` container over Tailscale SSH and
   waits for health, then displays the tailnet `/register` address. The person
   has ten minutes from the restart to create the first administrator. Nothing
   is public. The password goes only into Coolify.

   Follow map entries `coolify.claim`, `coolify.two-factor`,
   `coolify.api-access` and `coolify.team-token`, printed by the runner.
   The run command asks for the shown confirmation `claimed <place-name>` and
   that token. It requires registration to redirect to this instance's login
   page and the authenticated team read to succeed. A closed setup window is
   reported as not claimed, with its consumed receipt retained. Prepare a new
   effect and obtain fresh approval to restart and reopen the window. An HTTP
   429 is not a completed claim; inspect it before reviewed recovery.

   ```sh
   python3 "$SETUP" prepare --progress "$PROGRESS" --step claim --effect "$PLACE/claim-effect.json"
   python3 "$GATE/approval_gate.py" approve-effect "$PLACE/claim-effect.json" "$PLACE/claim-approval.json"
   python3 "$SETUP" run --progress "$PROGRESS" --step claim --effect "$PLACE/claim-effect.json" --approval "$PLACE/claim-approval.json"
   ```

6. Read the localhost server and Docker destination identities in Coolify.
   Use map entry `coolify.destination` before collecting either identifier.
   After permission for reads, select them here. The API read-back refuses a
   server unless its name is `localhost` and its address is `127.0.0.1`,
   `localhost` or `host.docker.internal`, the built-in address in Coolify 4.7.5.
   It also refuses a destination outside that server.

   ```sh
   python3 "$SETUP" discover --progress "$PROGRESS" --server-uuid "$SERVER_UUID" --destination-uuid "$DESTINATION_UUID"
   ```

7. The following helper prepares one effect, lets the person approve it in
   their foreground terminal, then performs that one stage. The person calls
   it separately for each line below. Do not run a loop or approve on their
   behalf. Each run reads the Coolify token from the file or prompts if it is missing. The API has no current-token
   abilities route; the script says when scope remains a declaration. Check
   the actual token's scopes and whole-team access in Coolify before proceeding.

   ```sh
   stage() {
     python3 "$SETUP" prepare --progress "$PROGRESS" --step "$1" --effect "$PLACE/$1-effect.json" &&
     python3 "$GATE/approval_gate.py" approve-effect "$PLACE/$1-effect.json" "$PLACE/$1-approval.json" &&
     python3 "$SETUP" run --progress "$PROGRESS" --step "$1" --effect "$PLACE/$1-effect.json" --approval "$PLACE/$1-approval.json" --mcp-package "$MCP_PACKAGE"
   }
   stage project
   stage docktail
   stage oauth-id
   stage oauth-secret
   stage start-docktail
   stage register
   stage start-register
   stage record
   ```

   `project` creates only the infrastructure project. `docktail` creates its
   unmodified container definition with Docker and Tailscale socket access.
   The two OAuth stages separately approve storing each prompted value in
   Coolify's runtime environment. Each reads the production key first, updates
   it if present and creates it only if absent. Build time is off. Coolify
   creates empty keys while parsing Compose, so a duplicate create would fail.
   MCP masks empty and set values alike. The read-back therefore reduces the
   authenticated API response inside the local transport to set or unset and
   deployment flags; no value reaches command output and no reveal tool runs.
   `start-docktail` approves its ability to
   reconcile labelled Tailscale services. `register` defines the pinned canary
   with no published ports. `start-register` lets docktail advertise it to the
   people allowed by the reviewed tailnet policy. Registration stages ask for
   the separate Tailscale read credential and refuse different write-once service ports.
   Map entries `tailscale.docktail-credential` and `coolify.docktail-variables`
   own credential creation and any separately approved manual variable entry.
   `record` waits up to five minutes, with progress, for reconciliation and a
   certificate under the existing policy. If policy needs changing, stop for
   a separate specific approval. It requires the control-plane TCP 443
   definition and an HTTPS 200 in this server's tailnet, then replaces only the
   unchanged choice draft. It preserves the choice and records plumbing IDs.
   All read-only checks and record validation run before consuming approval or
   marking this local write uncertain. A failed readiness check leaves both
   progress and the choice unchanged.

8. After permission for reads, run the place checks and review every row.

   ```sh
   python3 "$RECIPE/scripts/check.py" --record "$PLACE/hosting/place-record.json" --mcp-package "$MCP_PACKAGE"
   ```

9. A public-lane test has a separate effect approval naming the selected ports.
   Preparation reads and shows the current firewall rules. Approval binds those
   rules, the requested ports, the receipt generation and one attempt. Keep
   `hosting/place-attempts/` and `hosting/place-attempts-generation.json`:
   receipts consume approvals before writes and retain uncertain results.
   The generation also lives in setup progress and the created place record.
   Apply refuses a missing or replaced journal, including a copied directory.
   Inspect the live state and obtain fresh approval through reviewed recovery.
   Deleting or replacing that directory does not revive an old approval, but
   restoring its earlier contents in place does: the receipts are local files,
   so anyone who can rewrite them can undo their record. Keep them as they are
   and never restore them from a backup. Local operations hold
   exclusive place and firewall locks through observation, comparison, write
   and read-back. A competing operation refuses plainly. These locks cover
   cooperating kit processes on this computer, not console or remote writers.
   After closure or a failed read-back, inspect the live rules, prepare a new
   effect at a new path and obtain fresh approval before applying again.

   This example opens TCP 80 and 443 to the internet, with no tool deployed.
   Approve that reachability explicitly. Other ports are refused. The command
   reads the project token and Coolify read token from the file, prompting for
   missing values, and saves a new record.
   The person reviews and adopts that local record before checking again.

   ```sh
   python3 "$RECIPE/scripts/lane.py" prepare --record "$PLACE/hosting/place-record.json" --lane public --port 80 --port 443 --effect "$PLACE/public-effect.json"
   python3 "$GATE/approval_gate.py" approve-effect "$PLACE/public-effect.json" "$PLACE/public-approval.json"
   python3 "$RECIPE/scripts/lane.py" apply --record "$PLACE/hosting/place-record.json" --lane public --port 80 --port 443 --effect "$PLACE/public-effect.json" --approval "$PLACE/public-approval.json" --new-record "$PLACE/hosting/place-record-public.json"
   mv "$PLACE/hosting/place-record-public.json" "$PLACE/hosting/place-record.json"
   python3 "$RECIPE/scripts/check.py" --record "$PLACE/hosting/place-record.json" --mcp-package "$MCP_PACKAGE"
   ```

   No listener is installed by this empty-place test. Open firewall rules do
   not make an absent listener answer. Record whether the outside probes
   actually match; do not turn a mismatch into a pass or tick the real-run
   outcome without the required evidence.

## Second real run: retire

There must be no live tool to export in this slice. From the same private place
repository, after separate permission for retirement reads, save and show a
destroy plan. The person supplies the passphrase, project token and storage
pair. The same project token must be supplied for plan and apply; its digest is
bound to the exact saved-plan checksum in local progress, never printed.
The spent auth key is not requested; a synthetic unused input satisfies
the required variable while planning deletion.

```sh
python3 "$SETUP" plan-destroy --progress "$PROGRESS"
python3 "$SETUP" summary --progress "$PROGRESS"
python3 "$SETUP" approve --progress "$PROGRESS"
python3 "$SETUP" retire --progress "$PROGRESS" --choice "$PLACE/hosting/place-record.json"
```

The person reviews and approves the exact destroy summary themselves, then
types the exact place name at retirement. Destruction loses the server disk
and its containers. The wrapper accepts only the three owned deletions,
checks live ownership and applies those exact encrypted saved bytes. It lists
remaining Cloud resources, including snapshot and backup images and resources
it did not own. The printed page-map entries name the service, machine, docktail
and read OAuth credentials, and fallback API token that may remain, with their
pages and removal buttons. Review Object Storage and DNS through
`hetzner.leftovers`. After destruction, every category is reported as listed, empty or
unchecked. An unreadable category leaves retirement incomplete with exit status
2; the later console checks are still printed. No leftover is removed
automatically. Keep the state and its key until recovery and retained copies
have been reviewed. Each further console
removal needs its own approval naming the data or access it removes.

## If a stage fails

Stop. Before apply, the runner has prepared local files only. After attempted
apply, the server, firewall and SSH key may exist. The progress file records
an uncertain write before it is sent and blocks later writes if its result is
unknown. Inspect the provider and Coolify records, with permission for those
reads, before deciding what to do. Do not clear the marker and retry blindly.

### Reviewed stage recovery

Keep the original effect, progress, receipt and journal generation. Recovery
holds the same place and firewall locks as a write. It binds the original
effect and uncertain receipt to a separate recovery effect, which the person
reviews and approves. It refuses a replaced journal, a changed effect or a
closed receipt. A spent write approval never authorises recovery or a retry.

For an uncertain administrator claim, prepare and approve the local recovery:

```sh
python3 "$SETUP" prepare-recovery --progress "$PROGRESS" --step claim --attempt-effect "$PLACE/claim-effect.json" --effect "$PLACE/claim-recovery.json"
python3 "$GATE/approval_gate.py" approve-effect "$PLACE/claim-recovery.json" "$PLACE/claim-recovery-approval.json"
python3 "$SETUP" recover --progress "$PROGRESS" --step claim --attempt-effect "$PLACE/claim-effect.json" --effect "$PLACE/claim-recovery.json" --approval "$PLACE/claim-recovery-approval.json"
```

The command reads both tokens and repeats the closed-firewall read,
registration redirect and authenticated team read, checks reported token
abilities when available, and asks for `claimed <place-name>`. Only a complete
pass records the claim as done and completes its receipt. A failure leaves
the stage uncertain and reports the failed check or HTTP status. It changes
no account or inbound firewall rule.

For an abandoned attempt, use `--abandon` on both recovery commands. Set
`STEP` to the failed stage and use new recovery paths:

```sh
python3 "$SETUP" prepare-recovery --abandon --progress "$PROGRESS" --step "$STEP" --attempt-effect "$PLACE/$STEP-effect.json" --effect "$PLACE/$STEP-recovery.json"
python3 "$GATE/approval_gate.py" approve-effect "$PLACE/$STEP-recovery.json" "$PLACE/$STEP-recovery-approval.json"
python3 "$SETUP" recover --abandon --progress "$PROGRESS" --step "$STEP" --attempt-effect "$PLACE/$STEP-effect.json" --effect "$PLACE/$STEP-recovery.json" --approval "$PLACE/$STEP-recovery-approval.json"
```

Abandonment requires the runner's durable evidence that it never dispatched
the write, or a complete Coolify inventory in the same team recorded in the
receipt showing that the named project or service creation is absent. An
older receipt without that team identity cannot use the absence route.
A start acknowledgement, a stopped container or
masked environment values cannot prove absence of a write. Without suitable
evidence, recovery refuses and keeps the uncertainty. The administrator claim
has its own completion route above because the person acts outside the runner.

On success, recovery retains the old receipt as `not-written` and appends the
abandoned attempt and reason to progress. That changes the next effect's
checksum. Prepare a new effect at a new path and obtain fresh approval before
running the stage. Keep the old effect and approval; neither can be reused.
Recovery also accepts the matching uncertain receipt if a crash happened
before progress could be marked uncertain. If a recovery itself stops during
its local writes, keep all evidence for inspection; do not restore receipts
from an earlier copy.

After bootstrap, export a fresh candidate record for retirement without
claiming that setup finished:

```sh
python3 "$SETUP" candidate --progress "$PROGRESS" --config "$PLACE/hosting/place-candidate.json"
```

Use the retire sequence with `--choice` pointing to that candidate. If apply
was partial and bootstrap never passed, use the partial retirement mode:

```sh
python3 "$SETUP" plan-destroy --partial --progress "$PROGRESS"
python3 "$SETUP" summary --progress "$PROGRESS"
python3 "$SETUP" approve --progress "$PROGRESS"
python3 "$SETUP" retire --partial --progress "$PROGRESS"
```

These commands read the state passphrase, project token and storage pair from
the protected file, prompting for missing values. Partial mode reads the encrypted state into
a recovery record in the progress file. It accepts only resources at the kit's
three generated addresses, checks their live identities, names and ownership
labels against that record, requires the typed place name and applies only
the deletions in the approved saved plan. A resource outside those addresses
is refused. Keep the state and request a reviewed recovery step if credentials
or state are unavailable. A failed command may have created resources.
