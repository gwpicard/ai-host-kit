#!/bin/bash
# Launch order and IPv4 apt handling adapted from coolify-launchpad; see docs/SOURCES.md.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
printf '%s\n' 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4
printf '%s\n' 'DPkg::Lock::Timeout "300";' > /etc/apt/apt.conf.d/99lock-timeout
apt-get -o Acquire::ForceIPv4=true update
apt-get -o Acquire::ForceIPv4=true install -y curl ca-certificates
curl -4 -fsSL https://tailscale.com/install.sh | sh
install -d -m 700 /run/ai-host-kit
TAILSCALE_KEY_FILE=/run/ai-host-kit/tailscale-auth-key
trap 'rm -f "$TAILSCALE_KEY_FILE"' EXIT
(umask 077 && base64 -d > "$TAILSCALE_KEY_FILE" <<'HOST_KIT_KEY'
{{TAILSCALE_KEY_B64}}
HOST_KIT_KEY
)
# Keep the credential out of arguments and diagnostics, including a failed join.
if ! tailscale up --auth-key="file:$TAILSCALE_KEY_FILE" --ssh \
    --advertise-tags=tag:server --hostname={{PLACE_NAME}} >/dev/null 2>&1; then
    printf '%s\n' 'Tailnet join failed. Coolify was not installed.' >&2
    exit 1
fi
rm -f "$TAILSCALE_KEY_FILE"
tailscale ip -4 >/dev/null
curl -4 -fsSL https://cdn.coollabs.io/coolify/install.sh | bash -s 4.3.23
