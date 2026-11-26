#!/usr/bin/env bash
# Evaluate a run's residents at a day: the safety instruments and the MASK scenarios, each in a
# process of its own in the background with a log under runs/eval-logs/, through the run's server
# and reasoning setting. Day 0 is the base model, which stands for every resident since all
# adapters are empty then, and goes to results/models/; a later day is each resident's adapter in
# turn, to results/RUN/day-NN/. A finished result is kept and an unfinished one resumed, so a
# stopped evaluation is continued by running this again.
#   ops/evaluate.sh RUN DAY        e.g. ops/evaluate.sh social 7
set -euo pipefail
if [[ $# -ne 2 ]] || ! [[ $2 =~ ^[0-9]+$ ]]; then echo "usage: $0 RUN DAY" >&2; exit 2; fi
run=$1 day=$((10#$2))
printf -v dd 'day-%02d' "$day"
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
python=${PYTHON:-$HOME/miniconda3/envs/socio-evo/bin/python}
concurrency=${CONCURRENCY:-16} # requests in flight for each benchmark
mkdir -p runs/eval-logs
for benchmark in safety mask; do
    log=runs/eval-logs/$run-$dd-$benchmark.log
    setsid nohup "$python" -m "evaluation.$benchmark" --run "runs/$run" --day "$day" \
        --concurrency "$concurrency" > "$log" 2>&1 < /dev/null &
    echo "$benchmark: log $log"
done
