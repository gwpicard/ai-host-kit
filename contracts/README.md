# Handover and hosting records

These are source contracts, outside the release while the hosting commands are
stubs. They validate declarations without contacting a host, running a command,
checking code or changing another repository.

## Ownership and files

| File | Owner | Purpose |
|---|---|---|
| `hosting/handover.json` | AI Build Kit | What one tool needs. AI Host Kit reads it. |
| `hosting/host-record.json` | AI Host Kit | What was set up for one tool. AI Host Kit writes it through a pull request the person merges. |
| `place-record.json` in the private place repository | AI Host Kit | Shared hosting details for the organisation. |

The [provisional handover schema](provisional-ai-build-kit/handover.schema.json)
is a draft for AI Build Kit to adopt. It is not a published or agreed upstream
contract. AI Build Kit owns the canonical schema once published. AI Host Kit
will vendor each supported published copy unchanged and record its release and
source location. No publication location or release is assumed here.

AI Host Kit owns the [host record schema](host-record.schema.json) and
[place record schema](place-record.schema.json). The schemas own the field
names and constraints; the [fixtures](../.agents/tests/fixtures/contracts/)
show complete records. All examples describe fictional places.

## Reading the handover

The draft uses JSON Schema draft 2020-12. `schema_version` is a `major.minor`
string. The reader supports `1.x`. A minor version may add optional fields;
the reader reports unknown fields by path and ignores them. Known fields keep
their constraints. A removal, rename, changed meaning or newly required field
needs a major version. An unknown major stops validation and asks for an
AI Host Kit update that supports it. No such update is claimed to exist.

`config` declares names, kinds, phases and sources, never values. Secret names
must use `phase: runtime`; `value` and `secret_value` fields are refused.
Unknown optional fields remain possible, so this schema is not a secret
scanner. A person must still keep values out of every record. Validation
messages print field paths and fixed explanations without printing values.

`jobs.runner` accepts `worker` for a separate process, `in-app` for a scheduler
in the web process, and `host-tick` for a host timer. A worker runner requires
`processes.worker`. The cron field checks five parts, not whether the schedule
will run. Staff sign-in uses `entra` for Microsoft, `google`, or generic `oidc`.
The outsider method `email-link` requires an email declaration.

Recovery targets use hours: how much recent data may be lost and how long a
restore may take. The app database role must declare that it owns no table and
cannot bypass row rules. Validation cannot prove those privileges, enforce
residency, measure recovery, register sign-in or judge whether a host fits.

## Reading Host Kit's records

The host record includes services with their versions and regions, the merge
release setting, health address, rollback targets, backup and restore evidence,
and the fit result. Missing backup or restore evidence is `null`; no rollback
evidence is an empty list. This lets an adopted tool be recorded as found.
These values do not permit a release. An accepted gap needs the person's words,
name and date; its status stays `accepted`. The schema has no `done` gap status.

The place record holds the network and firewall declarations, backup storage,
alert addresses, tools and encrypted state location. `key_custodian` names the
person keeping the key. There is no key field, and unknown fields are refused
in both Host Kit records. These formats currently support exactly `1.0`.
They do not prove the repository is private or the stored state is encrypted.

AI Build Kit owns the masterplan and its generated "How it stays running"
section. It will render that section from the handover and host record and
check for drift. AI Host Kit supplies the host record; this work adds no
renderer or writes to the masterplan. Fast-changing host readings belong in
the private place repository, not repeated project pull requests. This first
place format defines configuration; it does not collect readings.

## Local checks

Use the Python environment described in
[Maintaining AI Host Kit](../docs/MAINTAINING.md#checks-and-their-limits).

```sh
python3 .agents/tools/record_validation.py handover path/to/handover.json
python3 .agents/tools/record_validation.py host-record path/to/host-record.json
python3 .agents/tools/record_validation.py place-record path/to/place-record.json
python3 .agents/tools/check-handover-vendor.py
python3 .agents/tools/check-handover-vendor.py --published /path/to/published/handover.schema.json
```

The vendoring check takes a local schema file obtained from an AI Build Kit
release. It compares exact bytes, including whitespace. It does not download
files or authenticate their origin. The person running it must obtain the
published file from the release they intend to support. `--vendored` selects
another local copy for fixtures or a future supported version.

Exit status `0` means the requested check completed successfully, `1` means a
record or comparison failed, and `2` means the check could not run. With no
published copy, the vendoring check reports "could not check" and exits `2`.
Matching and differing fixture copies test the comparison; they do not prove
that the draft agrees with AI Build Kit. An unavailable published copy must
never count as a passed upstream comparison.
