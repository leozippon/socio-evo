#!/usr/bin/env bash
# Push an already published socio-evo bundle; the shared deployer preserves protected modes.
set -euo pipefail
if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "usage: $0 HOST SITE [ROOT]" >&2; exit 2
fi
[[ -f "$2/data/manifest.json" ]] || { echo "$2 is not a published site" >&2; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
exec "$HERE/../../ops/webui/push.sh" "$1" "$2" socio-evo "${3:-/opt/socio-evo}"
