---
name: go-live
description: Put a tool live for the first time only.
---

This command will read `handover.json`, check the place fits, show the changes for approval, put secrets in the host store and release the tool for the first time. It will prove backup and restore, rollback and previews before recording the address and opening a `host-record.json` pull request. It will adopt a tool already live without changing it; later code releases start with the build kit, while rollback or a release on request belongs to `/change-live`. It is not built yet. Report that to the person and stop without running tools or changing files or infrastructure.
