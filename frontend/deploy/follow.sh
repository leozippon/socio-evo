#!/usr/bin/env bash
# Follow live runs: publish the runs root into SITE and push it to HOST, again every INTERVAL
# seconds (120 by default), until interrupted. A failed publish or push is reported and tried
# again at the next turn. PYTHON, RUNS_ROOT and RESULTS_ROOT may be set in the environment.
#   frontend/deploy/follow.sh HOST SITE [INTERVAL]
set -euo pipefail
if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "usage: $0 HOST SITE [INTERVAL]" >&2; exit 2
fi
host=$1 site=$2 interval=${3:-120}
python=${PYTHON:-$HOME/miniconda3/envs/socio-evo/bin/python}
HERE=$(cd "$(dirname "$0")" && pwd)
while :; do
    if "$python" -m frontend.publish --runs-root "${RUNS_ROOT:-runs}" \
        --results-root "${RESULTS_ROOT:-results}" --out "$site"; then
        "$HERE/push.sh" "$host" "$site" || echo "push failed; trying again in $interval s" >&2
    else
        echo "publish failed; trying again in $interval s" >&2
    fi
    sleep "$interval"
done
