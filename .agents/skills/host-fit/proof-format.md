# Recorded recipe runs

`PROVEN.md` lives beside a recipe's `capabilities.json`. The menu reader checks
this format before admitting the recipe. This checks the recorded evidence;
a maintainer must still judge whether the run happened and supports the recipe.

Include exactly one line in this form:

```text
Real run: YYYY-MM-DD; versions: component=version, component=version
```

The date must be a valid calendar date. Supply at least one named version,
with comma-space separators between pairs. Component names start with a letter
and use letters, digits, dots, underscores or hyphens. Versions start with a
digit or `v` followed by a digit, then use letters, digits, dots, underscores,
plus signs or hyphens. Name the versions used for the run, including the kit
and the relevant hosting software.

Include exactly one outcome line for each of these areas:

```text
Provision: passed - <what was provisioned and checked>
Deploy: passed - <what was deployed and checked>
Company sign-in: passed - <which sign-in and access checks passed>
Files: passed - <which storage and access checks passed>
Jobs: passed - <which background work completed>
Backup and restore: passed - <what was backed up, restored and checked>
Previews: passed - <which preview checks passed>
Rollback: passed - <what was rolled back and checked>
```

Replace the placeholders with the observed outcomes. The reader requires the
exact area labels, `passed - ` and non-empty details. A missing, duplicate or
malformed line, a failed outcome, or `No real run yet` keeps the recipe off the
menu. The `menu` command reports the reason without echoing the record's text.
Other headings and notes are allowed. Record `Moved from:` when the run was a
move, and mark later sections without a run `No real run yet`. Those notes do
not satisfy the required outcomes or receive a separate automated check.
