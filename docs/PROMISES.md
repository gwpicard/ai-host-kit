# Hosting promises and their mechanisms

AI Host Kit is beta. All four commands are stubs. The hosting promises below
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
| The configured commit hook removes recognised attribution for all five supported agents. | `attribution-scrub.sh` checks real disposable commits for each agent, ordinary prose and human co-author trailers. `commit-hook.sh` checks the original Claude block and separator. [MAINTAINING.md](MAINTAINING.md#prepare-a-clone) lists the forms and limits. |
| A beta version keeps its README notice. | `validate-kit.sh`; `source-rules.sh` removes the notice in a scratch copy. |
| A pull request names a release category and targets only main. | The base and label scripts and workflows; `pull-request-checks.sh` tests accepted and refused inputs. |
| The suite continues after failures and distinguishes incomplete checks. | `run-all.sh`; `rehearsal-runner.sh` plants passing, failing and incomplete tests. |
