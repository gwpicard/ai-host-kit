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
confirm that it is the shortest option that covers apply, aiming for one hour.

Console work has its own approvals. The person approves creating a project
token for the selected Hetzner project, a storage key for the selected bucket,
and a single-use, pre-approved `tag:server` Tailscale auth key for a persistent
node. The auth key must not be reusable or ephemeral. The person reviews the
tailnet's server SSH grants, MagicDNS, HTTPS and service approval policy. A
separate approval covers creating the docktail OAuth client and its abilities
to register services. Keep its ID and secret in the person's password manager.
The person also provides a read token for Tailscale service definitions, a test
domain for the later public-lane run and the separately kept state passphrase.
This empty-place canary uses the tailnet domain; the test domain is not changed.

Use OpenTofu 1.13.2, the Python schema requirements and the installed, verified
`@masonator/coolify-mcp` 3.9.0 package. Its tarball integrity is in
`dependencies.json`. Installation is reviewed separately; the runner never
fetches a package. docktail 1.8.6 runs as an unmodified container. No model or
agent is installed on the server.

Set these non-secret paths in the person's shell. All plan and approval paths
must be new. `CREATE` and `DESTROY` are absolute paths outside repositories;
keep encrypted state in the selected bucket, with its passphrase elsewhere.
`MCP_PACKAGE` is the installed package's `package.json`, not a command.

```sh
cd "$PLACE"
SETUP="$RECIPE/scripts/setup.py"
PROGRESS="$PLACE/hosting/place-progress.json"
```

`PLACE`, `RECIPE`, `GATE`, `CREATE`, `DESTROY` and `MCP_PACKAGE` are supplied as
absolute paths by the person. `RECIPE` is the installed host-fit recipe folder;
`GATE` is the installed setup-hosting scripts folder. `TAILNET_IP`,
`SERVER_UUID` and `DESTINATION_UUID` are non-secret values read from the newly
created place, not invented in advance.

## First real run: create

1. Prepare the local root for review. This creates no provider resources.

   ```sh
   python3 "$SETUP" root --config "$PLACE/setup.json" --progress "$PROGRESS"
   ```

   Review `hosting/tofu/`, its module snapshot and `backend.json`. The person
   approves initialisation against that exact bucket, key, endpoint and region,
   then runs the next command themselves. It prompts for the state passphrase
   and storage key pair. It does not create the bucket or migrate state.

   ```sh
   python3 "$SETUP" init --progress "$PROGRESS"
   ```

2. After permission for provider reads, save a real plan and show its summary.
   The plan command prompts for the passphrase, project token, one-off tailnet
   key and storage pair. Later summary and approval commands prompt for the
   passphrase and same storage pair. No value is printed or kept in a local
   settings file. The one-off key is in Hetzner user data and encrypted plans
   and state; server cloud-init copies can remain. The summary says these
   copies cannot be recalled and why a spent or expired key is worthless.

   ```sh
   python3 "$SETUP" plan --progress "$PROGRESS" --plan "$CREATE"
   python3 "$SETUP" summary --progress "$PROGRESS" --plan "$CREATE"
   ```

3. The person reviews the exact summary and runs approval themselves, typing
   its checksum and their words. Only that saved plan may be applied. Apply
   asks for the passphrase, project token and storage pair again.

   ```sh
   python3 "$SETUP" approve --progress "$PROGRESS" --plan "$CREATE" --approval "$PLACE/create-approval.json"
   python3 "$SETUP" apply --progress "$PROGRESS" --plan "$CREATE" --approval "$PLACE/create-approval.json"
   ```

4. Wait for cloud-init to finish. Find the server's tailnet address using the
   person's Tailscale client. After permission for reads, check the bootstrap.
   This step neither fixes the node nor installs anything.

   ```sh
   tailscale ip -4 test-place
   python3 "$SETUP" bootstrap --progress "$PROGRESS" --address "$TAILNET_IP"
   ```

   Replace `test-place` with the approved place name. Bootstrap requires the
   Hetzner instance ID to match, the node name and address to match, the key
   file to be gone, `tag:server`, disabled node-key expiry, Tailscale SSH and
   completed cloud-init. A missing read stops the flow.

5. Prepare and approve the first-administrator effect. The person runs the
   approval command, then the run command. The runner records that the attempt
   has started before displaying the tailnet `/register` address. The person
   opens that address themselves. They create the first administrator, enable two-factor
   authentication and create a team token with exactly `read`, `read:sensitive`,
   `write`, `deploy`, never `root`. Nothing is public. The password goes only
   into Coolify. An HTTP 429 is not a completed claim; wait ten minutes before
   one careful retry. The run command asks for that token and the hidden
   confirmation `claimed <place-name>` and requires registration to redirect
   to this instance's login page and the authenticated team read to succeed.

   ```sh
   python3 "$SETUP" prepare --progress "$PROGRESS" --step claim --effect "$PLACE/claim-effect.json"
   python3 "$GATE/approval_gate.py" approve-effect "$PLACE/claim-effect.json" "$PLACE/claim-approval.json"
   python3 "$SETUP" run --progress "$PROGRESS" --step claim --effect "$PLACE/claim-effect.json" --approval "$PLACE/claim-approval.json"
   ```

6. Read the localhost server and Docker destination identities in Coolify.
   After permission for reads, select them here. The API read-back refuses a
   non-localhost server or a destination outside it.

   ```sh
   python3 "$SETUP" discover --progress "$PROGRESS" --server-uuid "$SERVER_UUID" --destination-uuid "$DESTINATION_UUID"
   ```

7. The following helper prepares one effect, lets the person approve it in
   their foreground terminal, then performs that one stage. The person calls
   it separately for each line below. Do not run a loop or approve on their
   behalf. Each run prompts for the Coolify token. The API has no current-token
   abilities route; the script says when scope remains a declaration. Check
   the actual token's scopes in Coolify before proceeding.

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
   Coolify's runtime environment. `start-docktail` approves its ability to
   reconcile labelled Tailscale services. `register` defines the pinned canary
   with no published ports. `start-register` lets docktail advertise it to the
   people allowed by the reviewed tailnet policy. Registration stages ask for
   a Tailscale read token and refuse different write-once service ports.
   Before `record`, wait for reconciliation and service approval under the
   existing policy. If policy needs changing, stop for a separate specific
   approval. `record` requires the control-plane TCP 443 definition and a
   successful HTTPS read in this server's tailnet, then replaces only the
   unchanged choice draft. It preserves the choice and records plumbing IDs.

8. After permission for reads, run the place checks and review every row.

   ```sh
   python3 "$RECIPE/scripts/check.py" --record "$PLACE/hosting/place-record.json" --mcp-package "$MCP_PACKAGE"
   ```

9. A public-lane test has a separate effect approval naming the selected ports.
   Preparation reads and shows the current firewall rules. Approval binds those
   rules, the requested ports and one attempt. Keep `hosting/place-attempts/`:
   its receipts consume approvals before writes and retain uncertain results.
   After closure or a failed read-back, inspect the live rules, prepare a new
   effect at a new path and obtain fresh approval before applying again.

   This example opens TCP 80 and 443 to the internet, with no tool deployed.
   Approve that reachability explicitly. Other ports are refused. The command
   prompts for the project token and Coolify read token and saves a new record.
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
python3 "$SETUP" plan-destroy --progress "$PROGRESS" --plan "$DESTROY"
python3 "$SETUP" summary --progress "$PROGRESS" --plan "$DESTROY"
python3 "$SETUP" approve --progress "$PROGRESS" --plan "$DESTROY" --approval "$PLACE/retire-approval.json"
python3 "$SETUP" retire --progress "$PROGRESS" --plan "$DESTROY" --approval "$PLACE/retire-approval.json" --choice "$PLACE/hosting/place-record.json"
```

The person reviews and approves the exact destroy summary themselves, then
types the exact place name at retirement. Destruction loses the server disk
and its containers. The wrapper accepts only the three owned deletions,
checks live ownership and applies those exact encrypted saved bytes. It lists
remaining Cloud resources, including snapshot and backup images and resources
it did not own. Review Object
Storage, DNS, the tailnet machine and the recorded Tailscale service definition
separately. No leftover is removed automatically. Keep the state and its key
until recovery and retained copies have been reviewed. Each further console
removal needs its own approval naming the data or access it removes.

## If a stage fails

Stop. Before apply, the runner has prepared local files only. After attempted
apply, the server, firewall and SSH key may exist. The progress file records
an uncertain write before it is sent and blocks later writes if its result is
unknown. Inspect the provider and Coolify records, with permission for those
reads, before deciding what to do. Do not clear the marker and retry blindly.

After bootstrap, export a fresh candidate record for retirement without
claiming that setup finished:

```sh
python3 "$SETUP" candidate --progress "$PROGRESS" --config "$PLACE/hosting/place-candidate.json"
```

Use the retire sequence with `--choice` pointing to that candidate. If apply
was partial and bootstrap never passed, use the partial retirement mode:

```sh
python3 "$SETUP" plan-destroy --partial --progress "$PROGRESS" --plan "$DESTROY"
python3 "$SETUP" summary --progress "$PROGRESS" --plan "$DESTROY"
python3 "$SETUP" approve --progress "$PROGRESS" --plan "$DESTROY" --approval "$PLACE/retire-approval.json"
python3 "$SETUP" retire --partial --progress "$PROGRESS" --plan "$DESTROY" --approval "$PLACE/retire-approval.json"
```

These commands request the state passphrase, project token and storage pair
through hidden terminal prompts. Partial mode reads the encrypted state into
a recovery record in the progress file. It accepts only resources at the kit's
three generated addresses, checks their live identities, names and ownership
labels against that record, requires the typed place name and applies only
the deletions in the approved saved plan. A resource outside those addresses
is refused. Keep the state and request a reviewed recovery step if credentials
or state are unavailable. A failed command may have created resources.
