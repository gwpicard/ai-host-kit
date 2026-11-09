# Hosting promises and their mechanisms

AI Host Kit is beta. Local host choice and saved-plan approval tools are built.
The hosting promises below still lack complete mechanisms and are not guarantees. Add a mechanism and a test that
fails when it is removed before changing a row from "none yet".

| Hosting promise | Mechanism today | Check today |
|---|---|---|
| Nothing goes online without approval. | none yet | none yet |
| Backup and a tested restore precede recording a live address and opening it to users. | none yet | none yet |
| A rollback target exists. | none yet | none yet |
| Secrets are never shown. | none yet | none yet |
| Access changes only with approval. | none yet | none yet |
| A check that did not run is never a pass. | none yet | none yet |
| An accepted gap is recorded as "accepted", never "done". | none yet | none yet |

The maintainer source has narrower, tested protections. These do not prove
the hosting promises above.

| Source promise | Mechanism and evidence |
|---|---|
| Adapters match canonical commands. | `build-adapters.sh --check`; `source-rules.sh` plants drift. |
| Maintainer material stays outside the public kit. | Release allowlist and packer; `release-builder.sh` checks the assembled files and refusal cases. |
| Attribution lines and issue references stay out of tracked files. | `validate-kit.sh`; `source-rules.sh` plants violations. |
| The existing commit hook removes Claude attribution lines and session links. | `commit-hook.sh` checks an actual disposable commit. Coverage for other agents is pending an upstream AI Build Kit fix, which AI Host Kit will copy. |
| A beta version keeps its README notice. | `validate-kit.sh`; `source-rules.sh` removes the notice in a scratch copy. |
| A pull request names a release category and targets only main. | The base and label scripts and workflows; `pull-request-checks.sh` tests accepted and refused inputs. |
| The suite continues after failures and distinguishes incomplete checks. | `run-all.sh`; `rehearsal-runner.sh` plants passing, failing and incomplete tests. |
| Invalid handover and hosting records name the field at fault. | `record_validation.py` uses the schemas in `contracts/`; `contracts.sh` checks invalid fixtures and their field paths. The published AI Build Kit schema is vendored unchanged. |
| An unsupported handover major version stops validation. | `record_validation.py`; `contracts.sh` checks the refusal and update message, plus optional fields in a newer minor version. Config declarations remain closed at every minor version. |
| A differing vendored schema fails comparison; unconfirmed upstream bytes never produce a pass. | `check-handover-vendor.py` reads a committed pin, fetches the commit and branch, confirms reachability, Git blob and SHA-256 before comparing bytes. `contracts.sh` checks matches, drift, absent pins, failed fetches, unreachable commits, wrong blobs and hash mismatches using local Git repositories. Unconfirmed upstream bytes return `2`, "could not check". The pin names a published commit without requiring a tag. A real check proves agreement with that pinned file only when it runs. |
| Config declarations reject extra fields, including in newer minor versions. | The published handover schema closes each declaration to its permitted metadata. `contracts.sh` rejects alternative value fields and nested values, naming paths without printing values. |
| Declared reference fields reject URL user information, queries and fragments. | `contracts.sh` checks host `address`, `health_address`, `rollback_targets[].image`, `last_backup_check.evidence` and `last_restore_drill.evidence`; place `backup_storage.location`, `encrypted_state.location` and `tools[].host_record`. Host Kit's schemas define these restricted forms; the handover uses the published schema's own path rules. |
| Declared free-text fields reject specific URL forms; host and place strings reject obvious secret text. | Schema patterns reject `scheme://` tokens containing `@`, `?`, `#`, `%` or a backslash. `record_validation.py` scans host and place strings for assignments, key headers and high-entropy runs, excluding rollback image digest suffixes. `contracts.sh` checks declared string fields and withheld values, plus independent encryption-method, email and hexadecimal-entropy refusals. The published handover schema rejects all scheme URLs in free text and checks extension values recursively. These checks can miss secrets and reject harmless text; they are not a guarantee. |
| Host record gaps marked as accepted carry the person's words and date. | `host-record.schema.json`; `contracts.sh` rejects missing acceptance evidence and a `done` gap status. This checks the record, not the person's approval. |

| Local choice promise | Mechanism and evidence |
|---|---|
| The tested handovers retain their expected fit lines, including residency, typed sign-in and the selected unknown structures. | `host_fit.py`; `host-fit.sh` compares fixed lines for each existing valid handover fixture and each stub, and refuses invalid inputs. Regressions cover future nulls, empty containers, mixed and nested arrays, unknown tool fields and internal literal dotted keys. Normal handover validation refuses dotted extension keys. Protection removals fail the corresponding checks. This covers those shapes, not every possible future handover. |
| Tested numeric durations remove the long-work question and control the suggestion. | `host-fit.sh` checks ordinary integer durations and `900.0`, `300.0` and `301`, including contradictory answers. Removing the skip or decimal handling fails. This does not prove what a model asks. |
| Tested suggestions follow the local answer table, preserve cloud wishes and prefer an actual place over a saved choice. | `host-fit.sh` compares host, trade-off and proof status, including a Hetzner place with a Vercel preference and a choice without a place. Routing, wish and priority mutations fail. Conversation replay results remain pending. |
| Stub recipes and the tested invalid proof records stay off the proven menu; tested recipe sections agree with capability entries. | `host-fit.sh` checks the [recorded-run format](../.agents/skills/host-fit/proof-format.md) with valid, empty, malformed and incomplete fixtures, invalid dates and versions, and each missing, failed or duplicate required outcome. Removing proof validation or either section check fails. The check cannot verify that a recorded run happened or that its outcome details are accurate. |
| Tested conditions preserve boolean and numeric distinctions and evaluate wildcard items. | `host-fit.sh` checks `true in [1]` and its reverse, numeric equality, and wildcard arrays with all true, false, missing, null and no items. Removing type comparison, wildcard resolution or traversal beyond the first item fails. These are declaration checks, not measurements of hosting capability. |
| Local choice records preserve accepted shortfalls and suppress their subsequent warning for the same host. | `host_fit.py record` and `warnings`; `host-fit.sh` checks exact words and dates, preserved place details, and no warning after acceptance. Mutations remove retention and warning suppression. This does not establish a person's consent or prove conversation behaviour. |
| Capability entries and choice acceptance reject invalid declarations by field. | The schemas and shared reader; `contracts.sh` checks invalid fixtures, including URL and secret text. `host-fit.sh` removes condition, reason, date, words, accepted status, proof and text protections in disposable copies and detects the removals. |
| Replay dry mode assembles runnable local projects without calling a model. | `replay-host-choice.py --dry`; each scripted case validates, resolves its bundled dependencies and runs local choice checks. `host-fit.sh` checks malformed turns and removes that protection in a copy. A model run and maintainer judgement are still required for replay evidence. |

## Approval gate limits

The saved-plan gate is built and tested locally. The experimental empty-Place scripts have offline checks only. The broad promises above remain unproven: future
host scripts, API writes and directory changes must use an approval mechanism
before they can back those promises.

| Local approval promise | Mechanism and evidence |
|---|---|
| Apply uses the approved saved bytes. | `setup-hosting/scripts/approval_gate.py` requires a valid record, matching full SHA-256, short confirmation and regenerated summary. It checks the original again and applies a private copy of the same bytes. `approval-gate.sh` exercises real encrypted saved plans, including missing and malformed records, changed bytes, a replacement at the same path and a change during apply. It detects removed record, checksum, summary and final-check protections. |
| Approval and apply require a matching plan-time destination identity. | The controlled plan command captures project, configuration, workspace, backend settings and environment identity before and after planning, refuses changes and binds the record to the saved plan SHA-256. Summary, approval and apply validate that record and compare the current identity; approval and apply recheck it after review. Local state storage and a restricted Hetzner S3 backend are accepted, with explicit destinations and no inherited state, workspace or AWS overrides. The S3 path prompts for storage keys and incorporates their digest into the target identity; keys are passed only to the child environment. Loopback S3 tests cover encrypted state, locks and workspace identity, not the live service. Tests refuse missing, malformed and substituted records, different state paths, workspace switches, changed environments, unsupported backends and identity changes during planning. Returning to the recorded workspace permits the original plan. Protection removals fail their outcome assertions. OpenTofu retains responsibility for stale-state checks. The [usage guide](../.agents/skills/setup-hosting/approval-gate.md) owns the supported-storage list and identity fields. |
| The tested summaries put destruction first and name network changes without showing fixture secrets. | The same check covers real built-in destroy and replacement plans and a saved JSON network fixture. It checks ports, widened sources, public addresses and buckets, directory changes, nested sensitive and unknown masks, unknown resource types and the key-loss warning. Regressions cover secret-shaped map keys through summary, approval, records, apply and refusals; explicit address and protocol fields; wildcard sources; empty structures; and output actions. Removing the relevant protections fails these checks. This does not prove every provider schema or establish live reachability. |
| Approval input comes from a foreground terminal. | The approve command reads the typed checksum and words from the controlling terminal, with echo disabled. `approval-gate.sh` refuses piped input, wrong confirmation and unsafe words, then exercises a synthetic terminal and a successful local apply. Removing the terminal check fails the pipe case even when a controlling terminal exists. |
| Approval records reject the tested malformed records and unsafe text. | `approval-record.schema.json` and the shared reader check required fields, references and secret-shaped text. Contract fixtures and approval tests check refusals without printing the input values. Schema and secret-scan removals fail. These text checks can still miss disguised secrets. |
| The gate requires the bundled encryption fragment; OpenTofu enforces its refusal of unencrypted state and plans. | The gate checks for a verbatim fragment in a root `.tf` file and an encrypted plan envelope. OpenTofu decrypts the private saved plan for `show -json` and apply; the gate does not decrypt or parse its internal format. Fragment presence does not establish that it is the only encryption configuration or restrict every effective encryption parameter. Offline tests check encrypted state and plans, a wrong passphrase, plaintext refusal and absence of the ephemeral passphrase from plan JSON. Removing fragment presence, either enforcement flag or the ephemeral declaration fails its check. The pinned executable version is checked before show and immediately before apply. |
| The OpenTofu test installer verifies downloaded bytes before extraction. | It compares the official published checksum with a platform pin, then hashes the archive. Local transport tests refuse altered checksums and archives; removing either comparison fails. The checks verify integrity against the fetched release and pin, not a release signature. |
| The shipped Claude Code settings request confirmation for the listed command forms. | The tests match direct and path-qualified OpenTofu calls and the approval and apply wrappers against the shipped ask rules; removing the rules fails. No agent or permission engine runs in these tests. Plugin and skill-only installation does not install project settings automatically. |

A terminal is an input boundary, not proof of human identity. There is no
cryptographic signature or separate approval service. An agent with arbitrary
shell or file access can manufacture a terminal, forge a record, alter the
scripts or invoke OpenTofu directly. The synthetic terminal test demonstrates
why the terminal alone cannot authenticate a person. The gate prevents the
tested unattended input and accidental plan substitution when the scripts,
records and execution environment are trusted. It cannot prevent a hostile
process with the same access as the person.

The Place receipts that mark an approval as used have the same limit. A
missing or replaced receipt journal is refused, but restoring its earlier
contents in place makes a used approval valid again. A counter kept on the
live firewall and server, which no local file can roll back, is planned
before the Coolify recipe joins the menu.

The person must run approval themselves, review unresolved effects, keep the
passphrase, and leave agent permission prompts enabled. Agent settings are
another prompt, not a security boundary against arbitrary code or a bypass
mode. A stronger guarantee needs a signer or execution boundary outside the
agent's control. No such boundary is claimed here. The
[usage guide](../.agents/skills/setup-hosting/approval-gate.md) owns the commands,
recording flow, encryption setup and output limits.

## Offline Place checks

The Coolify on Hetzner recipe remains off the menu. `place.sh` exercises the
provider-mocked module, one-off key rendering, a local S3 stand-in, named-effect
approval, claim confirmation and registration read-back, lanes, ownership,
node reads, sampled ports including 8080, the MCP protocol, scope declarations,
docktail port definitions, staged record assembly, destroy membership and
leftovers. A generated root validates with the pinned provider. The complete
setup command sequence uses stand-ins and synthetic approvals. The unmodified
MCP pin has also created and started a synthetic service against a loopback
API. Tests remove the corresponding guards in throwaway copies.

These checks do not prove who claimed a real administrator, real tailnet
policy, token abilities unavailable through the pinned API, actual docktail
reconciliation, Hetzner locking or versioning, or either real-run outcome.
The recipe owns the key-retention warning and approval sequence. A one-off
key is still a secret while unused and unexpired. No broad hosting promise
above changes to a guarantee.
