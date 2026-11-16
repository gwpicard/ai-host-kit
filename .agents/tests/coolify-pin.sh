#!/usr/bin/env sh
# coolify-pin.sh: guard release consistency, verified downloads, health waits and bootstrap reasons.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
exec python3 "$ROOT/.agents/tests/lib/coolify_pin_checks.py"
