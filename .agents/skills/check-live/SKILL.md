---
name: check-live
description: Read-only health and recovery checks for a live tool.
---

This command will read health, the running commit, drift, backup and restore-drill age, rollback targets, access, residency, versions and certificate dates. It will report which side a fault belongs to and name the next step, such as `/change-live` for a rollback or the build kit for a code repair. It will always be read-only. It is not built yet. Report that to the person and stop without running tools or changing files or infrastructure.
