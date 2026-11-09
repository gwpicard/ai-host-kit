# Reviewing a saved plan

These local tools prepare and check approval. The Coolify on Hetzner module has offline provider-mocked checks. Secret-free
bootstrap and the complete step that creates a place are not built. The hosting commands still stop after the local
choice. Use these tools only with a reviewed OpenTofu configuration; a saved
plan can contain provisioners and other executable work.

The scripts require Python 3, the packages in
`resources/schema-requirements.txt`, and OpenTofu 1.13.2 on `PATH`. Run them
from the configuration's working folder. Resolve `<skill-folder>` to this
installed setup-hosting folder. A plugin installation keeps the scripts and
their resources together.

## Encryption

Copy `resources/encryption.tf` into the root OpenTofu configuration before
initialising it. The source copy is `tofu/encryption.tf` in the maintainer
repository. This is a root configuration fragment for future modules to use;
child modules cannot set root state encryption. It pins OpenTofu and uses
`key_provider "pbkdf2"`, `method "aes_gcm"`, and `enforced = true` for both
`state` and `plan`, with no unencrypted fallback.

The person supplies `TF_VAR_host_state_passphrase` through a hidden terminal
prompt in their own shell and exports it for the commands. Do not put its
value in an argument, a variable file, shell history or a record. The variable
is sensitive and ephemeral. Unset it when finished. The kit keeps no copy;
the person keeps it in their password manager. Use a separate passphrase per
state and keep state and plans outside project repositories, including when
encrypted. Loss of the passphrase makes the state unreadable.

The fragment is checked against the pinned version's
[encryption documentation](https://opentofu.org/docs/v1.13/language/state/encryption/).
The gate requires a verbatim copy of the bundled fragment in a root `.tf`
file before planning, showing a summary or applying. OpenTofu enforces the
fragment's refusal of unencrypted state and plans and decrypts plans for
`show -json`. The gate checks the encrypted envelope, but does not decrypt
plans or inspect their internal format. Presence of the fragment does not establish that it is the only encryption
configuration or restrict every effective encryption parameter. The local
checks verify the fragment's syntax, encrypted state and plan files, and that
the passphrase is absent from decrypted plan JSON.

## Summary and approval

Save a plan outside the project repository with the controlled plan command:

```sh
sh <skill-folder>/scripts/plan.sh <new-planfile>
```

It runs `tofu plan -input=false -out <new-planfile>` and captures the destination
immediately before and after planning. A changed identity refuses and removes
only the new plan. The command refuses existing plan or identity paths. On
success it creates `<new-planfile>.identity.json` with owner-only permissions,
binding the identity to the full plan SHA-256. Keep this sidecar with the plan;
a plan copied without it, or with another plan's record, cannot be approved.
Plans saved directly with OpenTofu need to be saved again through this command.

Then run:

```sh
sh <skill-folder>/scripts/plan-summary.sh <planfile>
```

The four sections list destruction first, possible internet exposure, access
changes and irreversible effects. Replacements include destruction. The
summary names resources and network fields; it withholds free-text values.
Only narrow network values such as ports, IP addresses, source ranges,
protocols and known public-access settings can appear. Fields whose names suggest
addresses, ranges, sources, ports, protocols or public access are listed as
possibly affecting who can reach the tool, even without a specific rendering
rule. Zero ports are shown as zero unless an unmasked protocol in the same
rule specifies all protocols. Sensitive and unknown
masks take precedence, including parent object and list masks. Secret-shaped
map keys and keys beneath protected values are withheld too. Known wildcard
sources and equivalent zero-prefix IP ranges are named as all sources. Empty container changes have structural
lines, and each output is labelled as created, changed or removed while its
value stays withheld. Unrecognised resource types and actions get their own review lines. This conservative
report can flag a closed port or private rule for review; it does not establish
live reachability. Unknown or withheld sources must be resolved before the
person can judge who gains access. Observed drift and deferred changes are listed separately. Incomplete or
deferred plans cannot be approved or applied; resolve them and save a complete
fresh plan after reviewing them.

The person runs the following command themselves in a foreground terminal.
In Claude Code they can start it with `!`; if that route provides no interactive
terminal, they use a separate terminal. The agent must not run it, feed its
prompt, create a record, or treat permission to invoke a shell as plan approval.

```sh
sh <skill-folder>/scripts/approve.sh <planfile> <new-approval-record.json>
```

It shows the summary itself and asks for `approve` followed by the displayed
12 hexadecimal digits, grouped in fours. It then asks for the person's words.
Both answers come from the controlling terminal with echo disabled. Pipes,
redirected standard input or output, a wrong checksum and unsafe record text
are refused. A record is created with owner-only permissions and never
overwrites an existing file. No option accepts confirmation or words as an
argument. Keep the record in the private place repository; it contains the
redacted summary, no plan values.

The [approval record contract](resources/contracts/approval-record.schema.json)
is owned by AI Host Kit; the installed copy is
`resources/contracts/approval-record.schema.json`. The checksum binds the full
saved plan bytes; the short checksum is only for reading back. The date and
words record the decision, and `summary` records exactly the four sections
shown. The separate `target` records the project path, configuration and state
workspace displayed above those sections. Records without a target must be
replaced by running approval again. References and text use the shared record
protections. The record is not signed and is not evidence of a person's identity.

The plan-time identity and approval record use the same `target` fields:

- The resolved project root and its SHA-256.
- A SHA-256 over the names and contents of root `.tf` and `.tf.json` files.
- The selected workspace, backend type and resolved local state path and
  workspace state folder.
- A state target SHA-256 combining the complete root, configuration digest,
  resolved OpenTofu data directory, complete backend metadata, resolved local
  paths and workspace.
- An empty `environment` object: state and workspace overrides must be unset.

The supported backends are `local` and a restricted `s3` configuration for
Hetzner Object Storage. The latter has loopback stand-in evidence only; its
real locking and bucket versioning checks are pending. An explicit local backend must have a non-empty `path` in
its initialised metadata; a null or environment-selected destination refuses.
With no backend metadata, OpenTofu's implicit local paths are used. A null
`workspace_dir` uses the local backend's fixed default folder.

The gate refuses all set `TF_*` variables except input variables (`TF_VAR_*`),
logging variables (which it strips), `TF_INPUT`, `TF_IN_AUTOMATION` and
`TF_CLI_CONFIG_FILE`. The last selects CLI configuration, not local state.
This refuses `TF_WORKSPACE`, `TF_DATA_DIR`, every `TF_CLI_ARGS*` variable and
backend-specific variables, including `TF_HTTP_ADDRESS`. It also refuses
`TOFU_ENCRYPTION`, which can override encryption settings. Even an empty or
unchanged override must be unset. The local backend has no additional
backend-specific destination environment variable; the tests change
`TF_WORKSPACE` and `TF_DATA_DIR` between planning and apply and require refusal.

The summary shows the recorded destination above its four sections. Unsafe
paths and workspace names are withheld; complete values still contribute to
the fingerprints. Before summary, approval and apply, the gate validates the
[plan-time identity record](resources/contracts/plan-identity.schema.json),
checks its plan checksum and compares its identity with the current project.
Missing, malformed or mismatched records require a newly saved and approved
plan. Switching workspace refuses; returning to the recorded workspace permits
the original plan. Copying the plan and records to another project cannot match
the absolute root fingerprint. OpenTofu still checks saved plans for stale state.

The gate checks the pinned OpenTofu version before `show -json` and immediately
before apply. OpenTofu reads and decrypts the private plan copy used for the
summary and apply. There is no in-gate decryption or internal plan reader.

## Apply

```sh
sh <skill-folder>/scripts/apply.sh <planfile> <approval-record.json>
```

Apply checks the complete record, full SHA-256, short confirmation and freshly
computed summary. It compares the approval target and plan-time identity
before reading the plan, then rechecks the identity record and current target immediately before apply.
Approval also rechecks both after terminal input. Apply checks the original
plan again immediately before passing its private copy to OpenTofu.
It passes OpenTofu a private, read-only temporary copy of the exact checked
bytes, then deletes that copy. Replacing the original path after that check
cannot substitute another plan. It calls `tofu apply <private-plan-copy>`
without re-planning or adding arguments. All OpenTofu output is captured and
withheld, including errors, because provider diagnostics may contain values.
A refusal explains the next step. After an apply failure, inspect the state
privately and save a fresh plan before approving again.

The wrapper strips inherited logging variables and refuses extra CLI-argument
environment variables. It requires an encrypted plan envelope; OpenTofu
verifies and decrypts it and enforces the configured refusal of plaintext.
The wrapper does not establish that a configuration, provider binary, local
executable, environment or backend is trustworthy. The
[approval limits](../../../docs/PROMISES.md#approval-gate-limits) define the
boundary of these checks.

## Agent settings

The released `.claude/settings.json` asks before direct OpenTofu apply and
destroy calls, and before approval and apply wrappers. Review and merge these
rules into the project's settings when installing the kit. Plugin and
skill-only installations do not automatically install project permissions.
Rules cover literal command forms and wildcard matches from Claude Code's
[permission syntax](https://code.claude.com/docs/en/permissions#wildcard-patterns).
The tests inspect these rules without starting Claude Code. They do not prove
its permission engine or cover other coding agents. Keep prompts enabled;
never grant the agent unattended approval or bypass permissions.

## Hetzner Object Storage

Use `recipes/coolify-hetzner/tofu/backend.example.json` from the installed
host-fit resources as the settings template. Change the bucket and key to the
person's destination. The endpoint and region must be a matching pair for
`fsn1`, `nbg1` or `hel1`; only HTTPS Hetzner Object Storage endpoints are
accepted. Set an explicit workspace prefix. All safety switches and null-file
credential paths in that template are required. Extra non-null settings,
credential fields, profiles, alternative endpoints and credential chains refuse.
The shared encryption fragment is still required. The bucket already exists;
these tools do not create it or silently fall back to another backend.

For a reviewed root configuration with an empty `backend "s3" {}` block:

```sh
python3 <skill-folder>/scripts/init-s3.py <public-backend-settings.json>
```

The person runs this themselves in a foreground terminal. Both storage key
fields are read with echo disabled and kept only in process memory and the
OpenTofu child environment. The kit saves neither field to a file. Provider
credentials are separate. Never put storage keys in backend settings or use
`-backend-config` to supply them. Initialisation changes local backend metadata;
it is not a cloud resource creation command. Review any state migration as a
separate change; this wrapper supplies no automatic migration approval.

Plan, summary, approval and apply ask for the same storage key pair each time.
Their identity includes a digest incorporating the credentials as well as the
endpoint, bucket, key, region, prefix, workspace and every backend setting.
Changing the pair requires a new saved and approved plan. The digest is an
identity check, not secret storage or proof of the key's owner. No key is
rendered in the target. Inherited `AWS_*` variables and `TOFU_*` overrides
other than stripped logging variables refuse, even when empty. Proxy and TLS
certificate-file environment overrides also refuse for S3. The child
receives only the prompted pair, null shared-config paths and disabled metadata
credential discovery. Existing `TF_*` override refusals still apply.

Local S3 checks cover encrypted state and plans, the lock lifecycle and
workspace identity. They do not prove the remote service's conditional-write
or versioning semantics. Confirm those before a real place uses the backend.

## Effects and retirement

For an action without a saved plan, prepare an effect document that names its
exact change and binds its arguments and place-record digest. The person runs:

```sh
python3 <skill-folder>/scripts/approval_gate.py approve-effect <effect.json> <new-approval.json>
```

The gate displays the effect, asks for its checksum and the person's words
through its hidden foreground-terminal prompt, and refuses existing output
paths. A lane write regenerates the effect and compares the full checksum
before it calls the cloud adapter. This has the same trusted-local-process
limit as saved-plan approval. An agent must never answer the prompt or make
a real approval record. Synthetic approval records belong to offline tests only.
The staged Place runner uses this gate for each Coolify MCP write, the
person-led administrator claim and final record assembly. The recipe owns
the exact sequence and failure recovery. An approval record alone does not perform the action.

A destroy plan is saved through the same controlled identity command:

```sh
python3 <skill-folder>/scripts/approval_gate.py plan-destroy <new-destroy-plan>
```

Review and approve it through the ordinary summary and approve commands. The
recipe's retire wrapper additionally checks the three owned deletions and the
typed place name before calling apply. It never calls an unplanned `tofu destroy`.
