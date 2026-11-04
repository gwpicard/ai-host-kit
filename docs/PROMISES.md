# Hosting promises and their mechanisms

AI Host Kit is beta. Only the local host choice is built. The hosting promises below
have no mechanism yet and are not guarantees. Add a mechanism and a test that
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
| Invalid handover and hosting records name the field at fault. | `record_validation.py` uses the schemas in `contracts/`; `contracts.sh` checks invalid fixtures and their field paths. The handover schema is provisional pending AI Build Kit publication. |
| An unsupported handover major version stops validation. | `record_validation.py`; `contracts.sh` checks the refusal and update message, plus optional fields in a newer minor version. Config declarations remain closed at every minor version. |
| A differing vendored schema fails comparison; unconfirmed upstream bytes never produce a pass. | `check-handover-vendor.py` reads a committed pin, fetches the tag and confirms its commit and file hash before comparing bytes. `contracts.sh` checks matches, drift, absent pins, failed fetches, moved tags and hash mismatches using local Git repositories. Unconfirmed upstream bytes return `2`, "could not check". The pin is empty and actual upstream agreement remains unchecked. |
| Config declarations reject extra fields, including in newer minor versions. | The provisional handover schema closes each declaration to its permitted metadata. `contracts.sh` rejects alternative value fields and nested values, naming paths without printing values. |
| Declared reference fields reject URL user information, queries and fragments. | `contracts.sh` checks host `address`, `health_address`, `rollback_targets[].image`, `last_backup_check.evidence` and `last_restore_drill.evidence`; place `backup_storage.location`, `encrypted_state.location` and `tools[].host_record`; and handover `image.dockerfile`, `health.path`, `sign_in.staff.outside_refused_test` and `sign_in.staff.redirect_path`. The schemas define their restricted forms. |
| Declared free-text fields reject specific URL forms; host and place strings reject obvious secret text. | Schema patterns reject `scheme://` tokens containing `@`, `?`, `#`, `%` or a backslash. `record_validation.py` scans host and place strings for assignments, key headers and high-entropy runs, excluding rollback image digest suffixes. `contracts.sh` checks declared string fields and withheld values, plus independent encryption-method, email and hexadecimal-entropy refusals. Unknown optional handover fields are outside the URL constraints. These checks can miss secrets and reject harmless text; they are not a guarantee. |
| Host record gaps marked as accepted carry the person's words and date. | `host-record.schema.json`; `contracts.sh` rejects missing acceptance evidence and a `done` gap status. This checks the record, not the person's approval. |

| Local choice promise | Mechanism and evidence |
|---|---|
| Every declared hosting need has a fit line, including residency and unknowns. | `host_fit.py`; `host-fit.sh` compares fixed lines for each valid handover fixture and each stub, refuses invalid inputs, and removes residency and unknown lines in throwaway copies to prove detection. It checks conditional results and withheld handover values. |
| A supplied job duration removes the long-work question. | `host_fit.py questions`; `host-fit.sh` removes the skip and detects the repeated question in the returned list. This does not prove what a model asks. |
| Suggestions follow the local answer table, preserve cloud wishes and prefer an existing place. | `host_fit.py suggest`; `host-fit.sh` compares host, trade-off and proof status and removes routing, wish and existing-place protections in copies. Conversation replay results remain pending. |
| Stub recipes stay off the proven menu and sections agree with capability entries. | `PROVEN.md` presence and `check-recipes`; `host-fit.sh` removes the menu gate and both section checks, and detects each change. |
| Local choice records preserve accepted shortfalls and suppress their subsequent warning for the same host. | `host_fit.py record` and `warnings`; `host-fit.sh` checks exact words and dates, preserved place details, and no warning after acceptance. Mutations remove retention and warning suppression. This does not establish a person's consent or prove conversation behaviour. |
| Capability entries and choice acceptance reject invalid declarations by field. | The schemas and shared reader; `contracts.sh` checks invalid fixtures, including URL and secret text. `host-fit.sh` removes condition, reason, date, words, accepted status, proof and text protections in disposable copies and detects the removals. |
| Replay dry mode assembles runnable local projects without calling a model. | `replay-host-choice.py --dry`; each scripted case validates, resolves its bundled dependencies and runs local choice checks. `host-fit.sh` checks malformed turns and removes that protection in a copy. A model run and maintainer judgement are still required for replay evidence. |
