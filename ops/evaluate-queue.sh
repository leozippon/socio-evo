#!/usr/bin/env bash
# Evaluate a run as it lives, on the days given (0, 7, 14, 21 and 28 by default): ops/evaluate.sh
# on each day in turn, once the day's adapters are final and the run's evaluation of the day
# before has ended. Day 0 is the base model and starts at once. A day's adapters are those the
# residents fitted in the night after it, final once that night is complete (it writes
# learning/night-NN/done.json last, as learning.adapters reads it), which the checkpoint of the
# next day or the run's end also proves; a run that ends without the day's checkpoint stops the
# queue, as a failure. Each
# benchmark keeps LIVING requests in flight while the run lives and ENDED once it has ended. It
# looks every POLL seconds (60), logs dated lines, signals no process, and ends once the last
# day's evaluation has started.
#   ops/evaluate-queue.sh RUN [DAY...]     e.g. setsid nohup ops/evaluate-queue.sh social \
#                                               > runs/eval-logs/social-queue.log 2>&1 &
set -euo pipefail
LIVING=16 ENDED=48
if [[ $# -lt 1 ]]; then echo "usage: $0 RUN [DAY...]" >&2; exit 2; fi
run=$1
days=("${@:2}")
if [[ ${#days[@]} -eq 0 ]]; then days=(0 7 14 21 28); fi
previous=-1
for day in "${days[@]}"; do
    if ! [[ $day =~ ^(0|[1-9][0-9]*)$ ]] || ((day <= previous)); then
        echo "usage: $0 RUN [DAY...], the days increasing from 0" >&2; exit 2
    fi
    previous=$day
done
cd "$(dirname "$0")/.."
python=${PYTHON:-$HOME/miniconda3/envs/socio-evo/bin/python}
poll=${POLL:-60} # seconds between looks at the checkpoints, the manifest and the processes
manifest=runs/$run/manifest.json
[[ -f $manifest ]] || { echo "runs/$run has no manifest" >&2; exit 1; }
mkdir -p runs/eval-logs
log() { echo "$(date '+%m-%d %H:%M:%S') $*"; }
status() { # the run's status, as its manifest records it
    "$python" -c 'import json, sys; print(json.load(open(sys.argv[1]))["status"])' "$manifest"
}
final() { # until the adapters of day $1 are final; fails when the run ends without the day
    local dd next night s
    printf -v dd 'day-%02d' "$1"
    printf -v next 'day-%02d' "$(($1 + 1))"
    printf -v night 'night-%02d' "$1"
    while true; do
        s=$(status) # before the looks, so that a run ended by then has saved what it saves
        if [[ -f runs/$run/learning/$night/done.json || -f runs/$run/checkpoints/$next.json ]]; then
            return 0
        fi
        if [[ $s != running ]]; then
            if [[ -f runs/$run/checkpoints/$dd.json ]]; then return 0; fi
            log "the run is $s without $dd; the day-$1 evaluation not started"
            return 1
        fi
        sleep "$poll"
    done
}
evaluating() { # whether an evaluation of the run is running, started by the queue or by hand
    pgrep -f -- "-m evaluation\.(safety|mask) --run runs/$run " > /dev/null
}
for day in "${days[@]}"; do
    if ((day > 0)); then final "$day"; fi
    while evaluating; do sleep "$poll"; done
    if [[ $(status) == running ]]; then concurrency=$LIVING; else concurrency=$ENDED; fi
    log "starting the day-$day evaluation with $concurrency in flight a benchmark"
    CONCURRENCY=$concurrency ops/evaluate.sh "$run" "$day"
done
log "the evaluations of days ${days[*]} started"
