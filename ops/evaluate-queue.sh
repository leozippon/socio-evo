#!/usr/bin/env bash
# Evaluate a run as it lives, on the days given (0, 14 and 28 by default): ops/evaluate.sh
# on each day in turn, once the day's adapters are final and no other evaluation of the run is
# running. Day 0 is the base model and starts at once. In a run that learns, a day's adapters are
# those of the night after it, final once that night is complete: it writes
# learning/night-NN/done.json last, as learning.adapters reads it, and nothing else proves it, since
# the run saves the day's checkpoint before the night. A run that does not learn is scored on the
# base model once the day's checkpoint is saved. A run that ends without what a day waits for
# stops the queue. A day whose evaluation fails is logged with what failed and the next day taken;
# the queue then fails at its end, naming the failed days. Each benchmark keeps LIVING requests in
# flight while the run lives and ENDED once it has ended. It looks every POLL seconds (60), logs
# dated lines and signals no process. EVAL_SERVER and GUARD_CONFIG pass to ops/evaluate.sh.
#   ops/evaluate-queue.sh RUN [DAY...]     e.g. setsid nohup ops/evaluate-queue.sh social \
#                                               > runs/eval-logs/social-queue.log 2>&1 &
set -euo pipefail
LIVING=16 ENDED=48
if [[ $# -lt 1 ]]; then echo "usage: $0 RUN [DAY...]" >&2; exit 2; fi
run=$1
days=("${@:2}")
if [[ ${#days[@]} -eq 0 ]]; then days=(0 14 28); fi
previous=-1
for day in "${days[@]}"; do
    if ! [[ $day =~ ^(0|[1-9][0-9]*)$ ]] || ((day <= previous)); then
        echo "usage: $0 RUN [DAY...], the days increasing from 0" >&2; exit 2
    fi
    previous=$day
done
cd "$(dirname "$0")/.."
python=${PYTHON:-$HOME/miniconda3/envs/socio-evo/bin/python}
poll=${POLL:-60} # seconds between looks at the run and the processes
manifest=runs/$run/manifest.json
[[ -f $manifest ]] || { echo "runs/$run has no manifest" >&2; exit 1; }
mkdir -p runs/eval-logs
log() { echo "$(date '+%m-%d %H:%M:%S') $*"; }
status() { # the run's status, as its manifest records it
    "$python" -c 'import json, sys; print(json.load(open(sys.argv[1]))["status"])' "$manifest"
}
learns=$("$python" -c 'import sys; from pathlib import Path; from evaluation.subject import Run
print(str(Run.read(Path(sys.argv[1])).learns).lower())' "runs/$run")
final() { # until the adapters of day $1 are final; fails when the run ends without them
    local proof s
    if $learns; then
        printf -v proof 'runs/%s/learning/night-%02d/done.json' "$run" "$1"
    else
        printf -v proof 'runs/%s/checkpoints/day-%02d.json' "$run" "$1"
    fi
    while true; do
        s=$(status) # before the look, so that a run ended by then has written what it writes
        if [[ -f $proof ]]; then return 0; fi
        if [[ $s != running ]]; then
            log "the run is $s without $proof; the day-$1 evaluation not started"
            return 1
        fi
        sleep "$poll"
    done
}
evaluating() { # whether an evaluation of the run is running, started by the queue or by hand
    pgrep -f -- "-m evaluation\.(safety|mask) --run runs/$run " > /dev/null
}
failed=()
for day in "${days[@]}"; do
    if ((day > 0)) && ! final "$day"; then failed+=("$day (not started)"); break; fi
    while evaluating; do sleep "$poll"; done
    if [[ $(status) == running ]]; then concurrency=$LIVING; else concurrency=$ENDED; fi
    log "starting the day-$day evaluation with $concurrency in flight a benchmark"
    if CONCURRENCY=$concurrency ops/evaluate.sh "$run" "$day"; then
        log "the day-$day evaluation finished"
    else
        log "the day-$day evaluation failed"
        failed+=("$day")
    fi
done
if ((${#failed[@]})); then
    log "failed: days ${failed[*]}"
    exit 1
fi
log "the evaluations of days ${days[*]} finished"
