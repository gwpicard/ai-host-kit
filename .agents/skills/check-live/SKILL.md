---
name: check-live
description: Read-only place checks and planned health and recovery checks for a live tool.
---

For a Coolify on Hetzner place record with `infrastructure`, use the sibling host-fit skill's `resources/recipes/coolify-hetzner/scripts/check.py` from the person's project root, with `--record hosting/place-record.json` and `--mcp-package` naming the installed MCP's `package.json`. Locate that sibling beside this installed skill, including in plugins. Ask for the package path if unknown; never fetch a package or read credential files. The person supplies a read token through the hidden prompt. Report every result, including missing reads. The recipe owns this finite port sample, tailnet version read, temporary auth-key removal, node identity, server tag, disabled node-key expiry, Tailscale SSH, cloud-init completion and local MCP package check and their limits. Tool health, commits, drift, backups, restore drills, rollback targets, residency and certificate checks are not built. Say which checks could not run. Propose repairs through `/change-live`; never refresh state, call a write tool or change a file or host from this command.
