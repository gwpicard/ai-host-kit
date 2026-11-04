---
name: host-fit
description: Compare a handover with recipe declarations and guide a local host choice.
---

Use this background skill for the choice step in `/setup-hosting`. Run
`python3 scripts/host_fit.py` from this skill's folder. It needs the packages
in `resources/schema-requirements.txt`; report a missing dependency and stop
without claiming a check passed. Never install packages without explaining
that local prerequisite.

Call `questions --handover FILE` with `--place FILE` when a place record
exists, and `--answers FILE` as answers arrive. Ask only the returned questions.
The answer object uses `cloud` (azure, aws, google-cloud, none, not-sure),
`care` (managed, server, no-preference) and `long_work` (true or false).
Residency comes from the handover. A known job duration supplies long_work;
more than 300 seconds counts as long work for this suggestion only.

Call `suggest` with the same inputs. Show the host, proof status, trade-off,
extra lines and alternatives. No preference follows the managed route. Call
`fit --handover FILE --recipe HOST` for every recipe, including the chosen
host. An unlisted existing provider uses `--recipe existing` and reports
unknown fit without inventing a recipe. Show every returned line, including unknowns and unsatisfied conditions.
`menu` lists only recipes whose `PROVEN.md` meets the [recorded-run format](proof-format.md)
and reports malformed or incomplete records; today it is empty. Suggestions
from stubs must always be described as not yet proven.

For the chosen host call `warnings` with the handover, recipe and existing
place record. Explain each returned shortfall once, naming the need and its
consequence. Show any alternative the script returns. Count the residency line in the suggestion
or fit report as that notice. If the suggestion repeats the fit report's
residency reason, show that line once as both the fit line and the extra
residency notice; do not add another warning. If the
person accepts, keep their exact words and the date in an acceptance object
with `field`, `status: accepted`, `date` (YYYY-MM-DD) and `words`. Pass an array
of those objects with `--acceptances FILE` to `record`, together with
`--handover`, `--answers`, `--recipe`, `--output` and any `--place`. Never
invent acceptance. After acceptance, carry on without refusing or asking
again. The script preserves recorded acceptance for the same host and omits
its warning on subsequent calls. Unknowns remain visible; they are not
silently converted to met or accepted.
