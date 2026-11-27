#!/usr/bin/env bash
# Evaluate a run's residents at a day: the safety instruments and the MASK scenarios, side by side
# in processes of their own with a log each under runs/eval-logs/, with the run's reasoning setting,
# on the run's server or, when EVAL_SERVER names one (an LLMConfig YAML of a server of the same
# base, serving it under the run's name), on that server, onto which the day's adapters are
# loaded, so that the town's own server is not touched; GUARD_CONFIG names another LLMConfig of
# the safety judge than evaluation/safety/guard.yaml. Day 0 is the base model, which stands for
# every resident since all adapters are empty then, and goes to results/models/; a later day is
# each resident's adapter in turn, to results/RUN/day-NN/. It waits for both and fails, naming which failed and its log, when either
# does. A finished result is kept and an unfinished one resumed, so a stopped or failed evaluation
# is continued by running this again. Run it under setsid nohup to leave it running.
#   ops/evaluate.sh RUN DAY        e.g. EVAL_SERVER=ops/eval-server.yaml ops/evaluate.sh social 14
set -euo pipefail
if [[ $# -ne 2 ]] || ! [[ $2 =~ ^[0-9]+$ ]]; then echo "usage: $0 RUN DAY" >&2; exit 2; fi
run=$1 day=$((10#$2))
printf -v dd 'day-%02d' "$day"
server=${EVAL_SERVER:-} guard=${GUARD_CONFIG:-} # the caller's, before .env is read
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
python=${PYTHON:-$HOME/miniconda3/envs/socio-evo/bin/python}
concurrency=${CONCURRENCY:-16} # requests in flight for each benchmark
mkdir -p runs/eval-logs
declare -A pids logs
for benchmark in safety mask; do
    logs[$benchmark]=runs/eval-logs/$run-$dd-$benchmark.log
    options=(--concurrency "$concurrency")
    if [[ -n $server ]]; then options+=(--server "$server"); fi
    if [[ -n $guard && $benchmark == safety ]]; then options+=(--guard "$guard"); fi
    "$python" -m "evaluation.$benchmark" --run "runs/$run" --day "$day" "${options[@]}" \
        > "${logs[$benchmark]}" 2>&1 < /dev/null &
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
