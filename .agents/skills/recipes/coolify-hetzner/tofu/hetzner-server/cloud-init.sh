#!/bin/bash
# Launch order and IPv4 apt handling adapted from coolify-launchpad; see docs/SOURCES.md.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
printf '%s\n' 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4
printf '%s\n' 'DPkg::Lock::Timeout "300";' > /etc/apt/apt.conf.d/99lock-timeout
apt-get -o Acquire::ForceIPv4=true update
apt-get -o Acquire::ForceIPv4=true install -y curl ca-certificates
curl -4 -fsSL https://tailscale.com/install.sh | sh
# No enrolment credential is put in user-data, metadata or a cloud-init cache.
# Enrolment is blocked pending an approved secret delivery mechanism.
# Wait a bounded interval; never install Coolify before a tailnet address exists.
for attempt in $(seq 1 120); do
    if tailscale ip -4 >/dev/null 2>&1; then
        curl -4 -fsSL https://cdn.coollabs.io/coolify/install.sh | bash -s 4.3.23
        exit 0
    fi
    sleep 5
done
printf '%s\n' 'Tailnet enrolment did not complete. Coolify was not installed.' >&2
exit 1
