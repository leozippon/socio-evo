#!/usr/bin/env bash
# Evaluate a run's residents at a day: the safety instruments and the MASK scenarios, side by side
# in processes of their own with a log each under runs/eval-logs/, through the run's server and
# reasoning setting. Day 0 is the base model, which stands for every resident since all adapters
# are empty then, and goes to results/models/; a later day is each resident's adapter in turn, to
# results/RUN/day-NN/. It waits for both and fails, naming which failed and its log, when either
# does. A finished result is kept and an unfinished one resumed, so a stopped or failed evaluation
# is continued by running this again. Run it under setsid nohup to leave it running.
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
declare -A pids logs
for benchmark in safety mask; do
    logs[$benchmark]=runs/eval-logs/$run-$dd-$benchmark.log
    "$python" -m "evaluation.$benchmark" --run "runs/$run" --day "$day" \
        --concurrency "$concurrency" > "${logs[$benchmark]}" 2>&1 < /dev/null &
    pids[$benchmark]=$!
    echo "$benchmark: log ${logs[$benchmark]}"
done
failed=()
for benchmark in safety mask; do
    if ! wait "${pids[$benchmark]}"; then failed+=("$benchmark"); fi
done
for benchmark in "${failed[@]}"; do
    echo "$benchmark of $run $dd failed, see ${logs[$benchmark]}" >&2
done
((${#failed[@]} == 0))
