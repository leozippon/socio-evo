#!/usr/bin/env bash
# Evaluate a run's residents at a day: export the day's checkpoint, then for every resident
# run the MASK scenarios and the held-out capability tasks in the background, one chain a
# resident, with a log each under runs/eval-logs/. Day 0 is the resident as created and goes to
# the shared results/day-00; a later day goes to results/RUN/day-DD. A stopped capability
# evaluation is continued by running this again.
#   ops/evaluate.sh RUN DAY        e.g. ops/evaluate.sh c 0
set -euo pipefail
if [[ $# -ne 2 ]]; then echo "usage: $0 RUN DAY" >&2; exit 2; fi
run=$1 day=$2
printf -v dd 'day-%02d' "$day"
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
python=${PYTHON:-$HOME/miniconda3/envs/socio-evo/bin/python}
export=exports/$run/$dd
if [[ $day -eq 0 ]]; then results=results/$dd; else results=results/$run/$dd; fi
[[ -d $export ]] || "$python" -m experiments.export "runs/$run" --day "$day" --out "$export"
mkdir -p runs/eval-logs "$results/mask" "$results/capability"
for dir in "$export"/*/; do
    r=$(basename "$dir")
    setsid nohup bash -c "
        '$python' -m evaluation.mask '$export/$r' --out '$results/mask/$r.json' \
            --model experiments/configs/model.yaml --reasoning low \
            > 'runs/eval-logs/$dd-$r-mask.log' 2>&1
        '$python' -m evaluation.capability '$export/$r' --split eval --out '$results/capability/$r' \
            --model experiments/configs/model.yaml --reasoning low --concurrency 4 \
            > 'runs/eval-logs/$dd-$r-capability.log' 2>&1
    " >/dev/null 2>&1 &
    echo "$r: mask then capability, logs runs/eval-logs/$dd-$r-*.log"
done
