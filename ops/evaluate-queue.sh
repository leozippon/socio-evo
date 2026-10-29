#!/usr/bin/env bash
# Evaluate a run as it lives, in two loops over the days given (7, 14, 21 and 28 by default), each
# waiting for a day's checkpoint. The first judges the journals of the days since the day before
# (from day 1 for the first) as soon as the day's checkpoint is saved, with a log under
# runs/eval-logs/; a week whose directory under results/RUN/journals/ exists is not judged again,
# and a judging that fails is logged and the next week judged. The second runs ops/evaluate.sh on
# the day once no capability evaluation of the run is running, the previous day's or one started
# by hand, with one task in flight a resident while the run lives and three once it has ended. A
# loop stops when the manifest says the run has ended without the day it waits for; a run killed
# outright, whose manifest still says running, keeps it waiting. It looks every POLL seconds (60),
# logs dated lines, signals no process, and fails when either loop does.
#   ops/evaluate-queue.sh RUN [DAY...]     e.g. setsid nohup ops/evaluate-queue.sh town \
#                                               > runs/eval-logs/town-queue.log 2>&1 &
set -euo pipefail
LIVING=1 ENDED=3 # capability tasks in flight a resident while the run lives and once it has ended:
                 # 24 tasks at 90k, three for each of eight residents, fill ~70% of both replicas
if [[ $# -lt 1 ]]; then echo "usage: $0 RUN [DAY...]" >&2; exit 2; fi
run=$1
days=("${@:2}")
if [[ ${#days[@]} -eq 0 ]]; then days=(7 14 21 28); fi
previous=0
for day in "${days[@]}"; do
    if ! [[ $day =~ ^[1-9][0-9]*$ ]] || ((day <= previous)); then
        echo "usage: $0 RUN [DAY...], the days increasing from 1" >&2; exit 2
    fi
    previous=$day
done
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
python=${PYTHON:-$HOME/miniconda3/envs/socio-evo/bin/python}
poll=${POLL:-60} # seconds between looks at the checkpoints, the manifest and the processes
manifest=runs/$run/manifest.json
[[ -f $manifest ]] || { echo "runs/$run has no manifest" >&2; exit 1; }
mkdir -p runs/eval-logs
log() { echo "$(date '+%m-%d %H:%M:%S') $*"; }
status() { # the run's status, as its manifest records it
    "$python" -c 'import json, sys; print(json.load(open(sys.argv[1]))["status"])' "$manifest"
}
await() { # until the checkpoint of day $1 is saved; fails, saying $2, when the run ends without it
    local dd s; printf -v dd 'day-%02d' "$1"
    while true; do
        s=$(status) # before the look for the checkpoint, which a run ended by then has saved or not
        if [[ -f runs/$run/checkpoints/$dd.json ]]; then return 0; fi
        if [[ $s != running ]]; then log "the run is $s without $dd; $2"; return 1; fi
        sleep "$poll"
    done
}
journals() {
    local first=1 failed=0 day dd out week
    for day in "${days[@]}"; do
        printf -v dd 'day-%02d' "$day"
        printf -v out 'results/%s/journals/day-%02d-%02d' "$run" "$first" "$day"
        await "$day" "the journals of days $first to $day not judged"
        if [[ -d $out ]]; then
            log "the journals of days $first to $day are in $out already"
        else
            log "$dd saved; judging the journals of days $first to $day"
            mapfile -t week < <(seq "$first" "$day")
            if "$python" -m evaluation.journals "runs/$run" --days "${week[@]}" --out "$out" \
                > "runs/eval-logs/$dd-journals.log" 2>&1; then
                log "the journals of days $first to $day judged: $out"
            else
                log "judging the journals of days $first to $day failed," \
                    "see runs/eval-logs/$dd-journals.log"
                failed=1
            fi
        fi
        first=$((day + 1))
    done
    return "$failed"
}
evaluations() {
    local day s concurrency
    for day in "${days[@]}"; do
        await "$day" "the day-$day evaluation not started"
        # the tasks, and the chain whose command line names them while its MASK scenarios run
        while pgrep -f -- "-m evaluation\.capability '?exports/$run/" > /dev/null; do
            sleep "$poll"
        done
        s=$(status)
        if [[ $s == running ]]; then concurrency=$LIVING; else concurrency=$ENDED; fi
        log "starting the day-$day evaluation with $concurrency in flight a resident"
        CONCURRENCY=$concurrency ops/evaluate.sh "$run" "$day"
    done
    log "the evaluations of days ${days[*]} started"
}
journals & evaluations &
wait -n && wait -n || { wait; exit 1; } # both to their end, and fail when either failed
