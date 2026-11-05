# Handover and hosting records

These contracts validate declarations without contacting a host, checking code
or changing another repository. The host-fit skill bundles the schemas and
reader for its local choice step. The canonical copies live here.

## Ownership and files

| File | Owner | Purpose |
|---|---|---|
| `hosting/handover.json` | AI Build Kit | What one tool needs. AI Host Kit reads it. |
| `hosting/host-record.json` | AI Host Kit | What was set up for one tool. AI Host Kit writes it through a pull request the person merges. |
| `place-record.json` in the private place repository | AI Host Kit | Shared hosting details for the organisation. |

The [provisional handover schema](provisional-ai-build-kit/handover.schema.json)
is a draft for AI Build Kit to adopt. It is not a published or agreed upstream
contract. AI Build Kit owns the canonical schema once published. AI Host Kit
will vendor each supported published copy unchanged. The
[upstream pin](provisional-ai-build-kit/README.md) records its origin and is
empty until a published schema is adopted.

AI Host Kit owns the [host record schema](host-record.schema.json) and
[place record schema](place-record.schema.json). The schemas own the field
names and constraints; the [fixtures](../.agents/tests/fixtures/contracts/)
show complete records. All examples describe fictional places.

## Reading the handover

The draft uses JSON Schema draft 2020-12. `schema_version` is a `major.minor`
string. The reader supports `1.x`. A minor version may add optional fields;
the reader reports unknown fields by path and ignores them, except inside
`config` declarations. Known fields keep their constraints. A removal, rename,
changed meaning or newly required field needs a major version. An unknown major stops validation and asks for an
AI Host Kit update that supports it. No such update is claimed to exist.

`config` declares names, kinds, phases and sources, never values. Secret names
must use `phase: runtime`. Each declaration permits only `name`, `kind`,
`phase` and `source`, with their defined types and forms. Every other field
is refused by path, including in a newer minor version and when it contains
an object or array. This is an exception to ignoring optional minor-version
fields: extending a declaration requires a reader update before that record
can be accepted. This rule is part of the draft for AI Build Kit to adopt.

Closing declarations prevents extra fields from carrying values; it does not
recognise every secret disguised as metadata or text elsewhere. A person must
still keep values out of every record. Validation messages print field paths
and fixed explanations without printing values.

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

References use restricted forms:

| Fields | Allowed form |
|---|---|
| Host `address` and `health_address` | HTTPS URL, or `null` when not recorded. |
| Host `rollback_targets[].image` | Registry host, optional numeric port, repository path, then `:tag` or `@sha256:` and 64 lower-case hexadecimal characters. No URL scheme. |
| Place `backup_storage.location` and `encrypted_state.location` | HTTPS URL or `s3://bucket/path`; a bucket alone is allowed. |
| Backup and restore `evidence`, and place `tools[].host_record` | HTTPS URL or a relative repository path without `.` or `..` segments. |
| Place `alert_addresses` | Plain email address with an ASCII local part and domain. |

URLs have an ASCII host made from letters, digits, dots and hyphens, with an
optional numeric port for HTTPS. Paths use letters, digits, dots, underscores,
tildes, hyphens and slashes. URL user information, query strings, fragments,
percent escapes and spaces are refused. These are reference forms, not checks
that a host exists or that a file can be read. IPv6 URL literals and signed
URLs are not supported. `encrypted_state.encryption` accepts only `AES-GCM`,
`AES-256-GCM` or `ChaCha20-Poly1305`, with no parameters or key material.

The handover's `image.dockerfile` and `sign_in.staff.outside_refused_test`
use relative repository paths without `.` or `..` segments. `health.path`
and `sign_in.staff.redirect_path` start with one slash. These paths use the
same path characters as the references above and refuse URL credentials,
queries, fragments, percent escapes, backslashes and whitespace.

The remaining declared free-text fields in the handover and hosting record
schemas refuse
`scheme://` tokens containing `@`, `?`, `#`, `%` or a backslash, including
tokens within prose or commands. The same rule applies to cron text. This
blocks these URL forms, not every possible way to conceal a credential.
Unknown optional handover fields remain outside these field constraints.

The record validator also scans every string value in host and place records
for obvious secret content. It refuses assignments such as `key=`, `token=`,
`sig=` and `password=` (also with a colon), private-key headers and long runs
with high character entropy. Runs of at least 32 token characters are refused
at four bits per character; hexadecimal runs of at least 40 characters use
3.5 bits. The SHA-256 digest suffix in a rollback image is public metadata
and is excluded from this scan; the schema still checks its form. These
checks can reject harmless identifiers or other hashes and miss
short, disguised or low-entropy secrets. They catch obvious cases and are not
a guarantee that a record contains no secrets. The handover's free text is
not covered by this scan.

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
```

The vendoring check reads the committed upstream pin and refuses unsaved pin
changes. It obtains the tagged file itself, confirms the tag's commit and the
file's SHA-256, then compares the vendored copy byte for byte, including
whitespace. It accepts no command-line file or pin overrides. See the
[pin instructions](provisional-ai-build-kit/README.md) for its fields.

Exit status `0` means the requested check completed successfully, `1` means a
record or comparison failed, and `2` means the check could not run. An absent
or empty pin, failed fetch, moved tag or hash mismatch reports "could not
check" and exits `2`. A hash mismatch leaves the upstream bytes unconfirmed,
so it cannot establish drift in the vendored copy. Once upstream is confirmed,
a different vendored copy exits `1`.

The tests use temporary local Git repositories and tags through an internal
Python transport override. No CLI option, pin field or environment variable
enables that override. Matching local fixtures test byte comparison only;
they cannot establish publication. The test suite uses no network. Actual
agreement with AI Build Kit remains unchecked until the pin is filled.

## Recipe capabilities and local choice

The [capabilities schema](capabilities.schema.json) maps host-affectable handover
field paths to selectors. Array item paths use `*`, such as
`config.*.phase`. Enumerated needs can select a particular value; `*` covers
any value. An absent field or selector means unknown. Unknown is never inferred
as met. The fit report traverses objects and every array item, with a line for
each leaf, null or empty container. A mixed array also has a container line.
It withholds handover values. The declared
tool name, owner, successor and schema version are metadata; other fields under
`tool` are traversed. An absent optional field and the declared null worker do
not create requirements. The fixtures check these rules for the supplied
handovers and selected future structures, not every possible extension.

Array indices appear in fit lines. Internally, capability paths escape literal
backslashes, dots and stars in keys with a backslash. A literal dotted key is
shown in brackets and quotes, so `["limits.memory_mb"]` is distinct from
`limits.memory_mb` and cannot inherit its capability. Unknown key text still
passes through the reader's field-name filter before display.

Each entry is `met`, `cannot` with a reason, or `met-if` with a condition object.
Conditions name a field, an operator (`eq`, `in`, `lte`, `gte`) and a value.
An optional `check` names a relative script path; it is a reference, not a
command to execute. The reader interprets conditions as data. It reports the condition and whether it is
satisfied, not satisfied or unknown; it never executes an expression. A false
condition remains visible as not satisfied. `eq` and `in` distinguish JSON
booleans from numbers; integer and decimal representations of the same number
compare equally. A wildcard condition applies to every array item. Any false
item makes it not satisfied; otherwise an empty array, missing field or null
item makes it unknown. All items must satisfy it for a satisfied result.
Declaration validation does not
establish that a host fulfils the claim.

The stub recipe's section names own their capability entries through a
`Capabilities:` line. The local check rejects missing entries in either
direction, duplicates and entries assigned to the wrong section. Only the
rented server's UK limitation is declared today, from the supplied checked
planning facts. All other capability claims await verification. Recipe headers
record this limit. The menu checks `PROVEN.md` against the
[recorded-run format](../.agents/skills/host-fit/proof-format.md); no stub has
that file. A well-formed record is not independent verification of a real run.

The place record may contain only `schema_version` and `choice` before a place
exists. It cannot contain a partial infrastructure record. A complete existing
record may also carry `choice`. This preserves the original infrastructure
requirements. Choice records include the host, proof status at selection, answers,
an optional AWS or Google Cloud wish, and accepted shortfalls. An unlisted
existing provider uses host `existing`; the existing place details stay intact
and its capabilities are unknown. No provider folder is created for a wish.
An actual place takes priority over a saved host preference. The suggestion
shows that preference separately. Without a place, the saved choice comes first.

An acceptance names the need, has status `accepted`, and carries a date and
the person's words. Its text has the same URL and obvious-secret protections
as the other place strings. Validation happens before the local writer changes
a file. The writer preserves infrastructure details and same-host acceptance.
This checks stored declarations, not whether a person actually approved them.
A new choice of host starts a new acceptance list.

The suggestion table uses more than 300 seconds to interpret long work when
the handover supplies a duration, including integer-valued JSON numbers such
as `900.0`. This is a local choice convention, not a
verified provider limit. No preference follows the managed route. AWS and
Google Cloud wishes use the same nearest-host routing and prefer a proven
candidate if one exists. Today every candidate is not yet proven. Residency
is always read from the handover. The interview can ask about a missing or
null job duration, but a fit report still requires a valid handover; the
provisional schema itself is unchanged.

```sh
python3 .agents/tools/record_validation.py capabilities path/to/capabilities.json
python3 .agents/skills/host-fit/scripts/host_fit.py questions --handover hosting/handover.json
python3 .agents/skills/host-fit/scripts/host_fit.py menu
```
