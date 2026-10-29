#!/usr/bin/env bash
# Evaluate a run's residents at a day: export the day's checkpoint (an export there already is
# kept when it is of the run's present tags and replaced when it is not), then for every resident
# run in the background, one chain a resident, with a log each under runs/eval-logs/: the MASK
# scenarios, on the days of MASK_DAYS only, and then the held-out capability tasks, for the
# residents whose occupation is in CAPABILITY only, the programmers and their leader, who work the
# Office's tasks. Both answer through the run's own model and runtime settings, which the export
# records from the run's frozen configuration with each resident's occupation, except the
# capability tasks' compaction threshold, set below. Day 0 is the resident as created and goes to
# the shared results/day-00; a later day goes to results/RUN/day-DD. A stopped capability
# evaluation is continued by running this again.
#   ops/evaluate.sh RUN DAY        e.g. ops/evaluate.sh c 0
set -euo pipefail
MASK_DAYS=(0 14 28)                 # the days the design measures external honesty on
CAPABILITY=(programmer) # the occupations whose capability it measures
if [[ $# -ne 2 ]]; then echo "usage: $0 RUN DAY" >&2; exit 2; fi
run=$1 day=$2
printf -v dd 'day-%02d' "$day"
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
python=${PYTHON:-$HOME/miniconda3/envs/socio-evo/bin/python}
# KV cache: four residents at 225k tokens fill 59% of a replica's 1,535,199, so tasks at 225k beside
# them would evict prefixes (130 s to rebuild); eight 90k tasks, one a resident, use ~25% of both.
concurrency=${CONCURRENCY:-1}        # capability tasks in flight per resident
compaction=${EVAL_COMPACTION:-90000} # their compaction threshold, in place of the run's
export=exports/$run/$dd
if [[ $day -eq 0 ]]; then results=results/$dd; else results=results/$run/$dd; fi
case " ${MASK_DAYS[*]} " in *" $day "*) masked=true ;; *) masked=false ;; esac
"$python" -m experiments.export "runs/$run" --day "$day" --out "$export"
residents=$("$python" -m evaluation.exports "$export") # "name occupation", a line each
mkdir -p runs/eval-logs "$results/capability"
if $masked; then mkdir -p "$results/mask"; fi
while read -r r occupation; do
    mask="" capability=""
    if $masked; then
        mask="'$python' -m evaluation.mask '$export/$r' --out '$results/mask/$r.json' \
            > 'runs/eval-logs/$dd-$r-mask.log' 2>&1"
    fi
    case " ${CAPABILITY[*]} " in *" $occupation "*)
        capability="'$python' -m evaluation.capability '$export/$r' --split eval \
            --out '$results/capability/$r' --concurrency $concurrency \
            --compaction-threshold $compaction > 'runs/eval-logs/$dd-$r-capability.log' 2>&1"
    esac
    if [[ -z $mask$capability ]]; then
        echo "$r: nothing on this day"
        continue
    fi
    setsid nohup bash -c "$mask${mask:+ ; }$capability" >/dev/null 2>&1 &
    echo "$r: ${mask:+mask}${mask:+${capability:+ then }}${capability:+capability}," \
        "logs runs/eval-logs/$dd-$r-*.log"
done <<< "$residents"
