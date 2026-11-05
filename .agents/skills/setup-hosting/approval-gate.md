# Reviewing a saved plan

These local tools prepare and check approval. Host modules and the step that
creates a place are not built. The hosting commands still stop after the local
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
The local checks also verify the syntax, encrypted state and plan files, and
that the passphrase is absent from decrypted plan JSON.

## Summary and approval

Save a plan outside the project repository with `tofu plan -out=<planfile>`.
Then run:

```sh
sh <skill-folder>/scripts/plan-summary.sh <planfile>
```

The four sections list destruction first, possible internet exposure, access
changes and irreversible effects. Replacements include destruction. The
summary names resources and network fields; it withholds free-text values.
Only narrow network values such as ports, IP addresses, source ranges,
protocols and known public-access settings can appear. Sensitive and unknown
masks take precedence, including parent object and list masks. Secret-shaped
map keys and keys beneath protected values are withheld too. Known wildcard
sources are named as all sources. Empty container changes have structural
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

The target includes the resolved absolute project root and its SHA-256, a
SHA-256 over the names and contents of the root `.tf` and `.tf.json` files,
and the selected workspace. A state target SHA-256 combines that root,
configuration digest, resolved OpenTofu data directory, workspace and a hash
of the local backend metadata, or the default local backend marker when no
metadata exists. Backend metadata is hashed without displaying its contents.
This identifies the state destination even before a state exists. The project
path and workspace are withheld if unsafe to display; their complete values
still contribute to the fingerprints. Copying a plan and record to another
project cannot match the absolute project root fingerprint. Changing configuration,
backend metadata, data directory or workspace requires fresh approval.
OpenTofu still checks whether a saved plan is stale against the state.

## Apply

```sh
sh <skill-folder>/scripts/apply.sh <planfile> <approval-record.json>
```

Apply checks the complete record, full SHA-256, short confirmation and freshly
computed summary. It compares the target before reading the plan and again
before apply. Approval also rechecks the target after terminal input. It checks
the original plan again immediately before apply.
It passes OpenTofu a private, read-only temporary copy of the exact checked
bytes, then deletes that copy. Replacing the original path after that check
cannot substitute another plan. It calls `tofu apply <private-plan-copy>`
without re-planning or adding arguments. All OpenTofu output is captured and
withheld, including errors, because provider diagnostics may contain values.
A refusal explains the next step. After an apply failure, inspect the state
privately and save a fresh plan before approving again.

The wrapper strips inherited logging and extra CLI-argument environment
variables. It requires an encrypted plan envelope and lets OpenTofu verify
and decrypt it. It does not establish that a configuration, provider binary,
local executable, environment or backend is trustworthy. The
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
