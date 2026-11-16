#!/bin/sh
# Launch order and IPv4 apt handling adapted from coolify-launchpad; see docs/SOURCES.md.
set -eu
export DEBIAN_FRONTEND=noninteractive
printf '%s\n' 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4
printf '%s\n' 'DPkg::Lock::Timeout "300";' > /etc/apt/apt.conf.d/99lock-timeout
apt-get -o Acquire::ForceIPv4=true update
apt-get -o Acquire::ForceIPv4=true install -y curl ca-certificates
install -d -m 700 /run/ai-host-kit
curl -4 -fsSL https://tailscale.com/install.sh -o /run/ai-host-kit/tailscale-install.sh
sh /run/ai-host-kit/tailscale-install.sh
rm -f /run/ai-host-kit/tailscale-install.sh
TAILSCALE_KEY_FILE=/run/ai-host-kit/tailscale-auth-key
trap 'rm -f "$TAILSCALE_KEY_FILE"' 0
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
# Verify every release file before modifying or running either script.
COOLIFY_VERSION=4.7.5
COOLIFY_FILES=/run/ai-host-kit/coolify
install -d -m 700 "$COOLIFY_FILES"
while read -r checksum name url; do
    if ! curl -4 -fsSL --retry 3 --connect-timeout 15 --max-time 120 "$url" -o "$COOLIFY_FILES/$name"; then
        printf '%s\n' 'Coolify release download failed.' >&2
        exit 1
    fi
    if ! (cd "$COOLIFY_FILES" && printf '%s  %s\n' "$checksum" "$name" | sha256sum --check --status); then
        printf '%s\n' "Coolify release checksum mismatch: $name. Installation stopped." >&2
        exit 1
    fi
done <<'HOST_KIT_COOLIFY_FILES'
c221f81e0bc9b47541f47bf671da76c79cfb61ce4741c3cb0800d7a18b99f137 install.sh https://raw.githubusercontent.com/coollabsio/coolify/v4.7.5/scripts/install.sh
d99cc100ce9e706d691980591aab6dee238eea59710ec8abacc84aedb79973d7 upgrade.sh https://raw.githubusercontent.com/coollabsio/coolify/v4.7.5/scripts/upgrade.sh
aa65c277fc13ab5b27c349fbfef12defc59c084b244e4b258329e1f6c570ae8d upgrade-postgres.sh https://raw.githubusercontent.com/coollabsio/coolify/v4.7.5/scripts/upgrade-postgres.sh
2532ee9258e10ad4e86cb3c2b46c29fe9329f5a0dace0f7da410744feec279bd docker-compose.yml https://raw.githubusercontent.com/coollabsio/coolify/v4.7.5/docker-compose.yml
f8b104aadfca48d0033fdee6cb87fea13c68bc5c67c63ba18b1934e9f901ff5d docker-compose.prod.yml https://raw.githubusercontent.com/coollabsio/coolify/v4.7.5/docker-compose.prod.yml
7895e54f7c9d40063e76afec9b35839048d91e5c3b5107d64ea49ef6987c304a .env.production https://raw.githubusercontent.com/coollabsio/coolify/v4.7.5/.env.production
HOST_KIT_COOLIFY_FILES
python3 - "$COOLIFY_FILES" <<'HOST_KIT_PREPARE'
from pathlib import Path
import re, sys
folder = Path(sys.argv[1])
# Local changes to verified upstream scripts: use verified configuration copies,
# fixed image versions, longer waits and no automatic updates.
for name, count in [('install.sh', 5), ('upgrade.sh', 4)]:
    text = (folder/name).read_text()
    def local_copy(match):
        name = match.group(1)
        return f'cp "{folder}/{name}" /data/coolify/source/{name}'
    text, changed = re.subn(r'curl -fsSL -L \$CDN/([.a-z-]+) -o /data/coolify/source/\1', local_copy, text)
    if changed != count:
        raise SystemExit('Coolify installer layout changed. Installation stopped.')
    if name == 'install.sh':
        start = text.index('# Fetch versions.json once')
        end = text.index('case "$OS_TYPE" in', start)
        text = text[:start] + 'LATEST_VERSION=4.7.5\nLATEST_HELPER_VERSION=1.0.19\n\n' + text[end:]
        for old, new in [('MAX_WAIT=180', 'MAX_WAIT=600'), ('HEALTH_WAIT=60', 'HEALTH_WAIT=600')]:
            if text.count(old) != 1:
                raise SystemExit('Coolify wait layout changed. Installation stopped.')
            text = text.replace(old, new)
    text = '# Modified locally by AI Host Kit for verified fresh installation.\n' + text
    (folder/name).write_text(text)
HOST_KIT_PREPARE
# Upstream diagnostics can include generated values. Keep them in a private file.
umask 077
AUTOUPDATE=false bash "$COOLIFY_FILES/install.sh" "$COOLIFY_VERSION" >"$COOLIFY_FILES/install.log" 2>&1 &
installer_pid=$!
while kill -0 "$installer_pid" 2>/dev/null; do
    printf '%s\n' 'Coolify installation is still running.'
    sleep 15
done
if ! wait "$installer_pid"; then
    printf '%s\n' 'Coolify installer failed. Installation diagnostics remain private on the server.' >&2
    exit 1
fi
# Require Docker health, including realtime, rather than only the HTTP API.
waited=0
while [ "$waited" -le 600 ]; do
    health=$(docker inspect coolify 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["State"].get("Health", {}).get("Status", "unknown"))' 2>/dev/null || true)
    if [ "$health" = healthy ]; then
        printf '%s\n' 'Coolify is healthy.'
        exit 0
    fi
    if [ "$waited" -lt 600 ]; then
        printf 'Coolify is not yet healthy; waited %s seconds.\n' "$waited"
        sleep 10
    fi
    waited=$((waited + 10))
done
printf '%s\n' 'Coolify did not become healthy within 10 minutes.' >&2
exit 1
