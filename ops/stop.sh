#!/usr/bin/env bash
# Stop a run: send SIGTERM to the process its manifest records, and to no other, wait for it to
# end and print the status the manifest then holds (interrupted: the day in progress is lost, and
# --resume lives it again from the last checkpoint). Refuses when the manifest records no process
# or the process is not a run. With --after-checkpoint it first waits, looking every 30 s, for the
# run's next daily checkpoint, so that nothing of a lived day is lost.
#   ops/stop.sh RUN [--after-checkpoint]      e.g. ops/stop.sh c --after-checkpoint
set -euo pipefail
case $#:${2-} in
    1: | 2:--after-checkpoint) ;;
    *) echo "usage: $0 RUN [--after-checkpoint]" >&2; exit 2 ;;
esac
cd "$(dirname "$0")/.."
run=runs/$1
python=${PYTHON:-$HOME/miniconda3/envs/socio-evo/bin/python}
[[ -f $run/manifest.json ]] || { echo "$run has no manifest" >&2; exit 1; }
field() { # a field of the manifest, empty when null or absent
    "$python" -c 'import json, sys
v = json.load(open(sys.argv[1])).get(sys.argv[2])
print("" if v is None else v)' "$run/manifest.json" "$1"
}
check() { # refuse unless the manifest records a process that is a run
    pid=$(field pid)
    if [[ -z $pid ]]; then
        echo "$run/manifest.json records no process (status: $(field status))" >&2; exit 1
    fi
    if ! grep -qaF experiments.run "/proc/$pid/cmdline" 2>/dev/null; then
        echo "process $pid in $run/manifest.json is not a run; nothing stopped" >&2; exit 1
    fi
}
latest() { local saved=("$run"/checkpoints/day-*.json); basename "${saved[-1]}" .json; }
check
if [[ $# -eq 2 ]]; then
    last=$(latest)
    echo "$1: waiting for the checkpoint after $last"
    while [[ $(latest) == "$last" ]]; do sleep 30; check; done
    echo "$1: saved $(latest)"
    check
fi
kill -TERM "$pid"
tail --pid="$pid" -f /dev/null
status=$(field status)
echo "$1: $status"
[[ $status != running ]]
