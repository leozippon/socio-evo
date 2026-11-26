#!/usr/bin/env bash
# Validate the training stack on the real base, on two free GPUs: fit a small adapter twice on the
# first GPU (learning.train), serve the base with LoRA enabled as one replica on both
# (ops/vllm/serve.sh), hot-load the adapter and compare it with the base (validate.py check).
# Usage (from the repository root):
#   set -a; . ./.env; set +a; GPUS=a,b [BASE=...] [PORT=8199] [TRAIN_PYTHON=...] ops/train/validate.sh
# It refuses to start unless both GPUs are free (no process, under 1 GiB in use) and nothing answers
# on PORT, and it stops the server it started. Its files are under runs/train-validate/<time>/.
set -euo pipefail

: "${VLLM_API_KEY:?VLLM_API_KEY is not set; source the repository .env first}"
gpus=${GPUS:?GPUS must name two free GPUs, e.g. GPUS=4,5}
if [[ ! $gpus =~ ^[0-9]+,[0-9]+$ ]]; then
  echo "GPUS must name exactly two GPUs, got: $gpus" >&2
  exit 1
fi
python=${TRAIN_PYTHON:-/Data2/lzp/envs/socio-evo-train/bin/python}
base=${BASE:-/Data2/lzp/models/Qwen3.8-27B-Uncensored-FP8}
export VLLM_BASE_URL=http://127.0.0.1:${PORT:-8199}/v1
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

busy=$(nvidia-smi --query-compute-apps=gpu_uuid --format=csv,noheader)
for gpu in ${gpus/,/ }; do
  read -r used uuid < <(nvidia-smi --id="$gpu" --query-gpu=memory.used,uuid --format=csv,noheader,nounits | tr -d ,) || true
  if [[ ! $used =~ ^[0-9]+$ || -z $uuid ]]; then
    echo "cannot read the state of GPU $gpu; refusing to run" >&2
    exit 1
  fi
  if (( used >= 1024 )) || grep -qF "$uuid" <<<"$busy"; then
    echo "GPU $gpu is not free ($used MiB in use or a process on it); refusing to run" >&2
    exit 1
  fi
done
if curl -s -o /dev/null "$VLLM_BASE_URL/models"; then
  echo "something already answers at $VLLM_BASE_URL; choose another PORT" >&2
  exit 1
fi

work=$repo/runs/train-validate/$(date +%Y%m%d-%H%M%S)
mkdir -p "$work"
"$python" "$repo/ops/train/validate.py" prepare "$work" "$base"
echo "fitting on GPU ${gpus%%,*}; files in $work" >&2
(cd "$repo" && CUDA_VISIBLE_DEVICES=${gpus%%,*} "$python" -m learning.train --jobs "$work/jobs.json") 2>&1 | tee "$work/train.log"

echo "starting vLLM with LoRA on GPUs $gpus" >&2
GPUS=$gpus LORA=1 MODEL_PATH=$base SERVED_NAME=validate-base setsid "$repo/ops/vllm/serve.sh" >"$work/serve.log" 2>&1 &
server=$!
trap 'kill -TERM -- "-$server" 2>/dev/null || true' EXIT
for _ in $(seq 120); do
  curl -sf -o /dev/null -H "Authorization: Bearer $VLLM_API_KEY" "$VLLM_BASE_URL/models" && break
  if ! kill -0 "$server" 2>/dev/null; then
    echo "the server exited; see $work/serve.log" >&2
    exit 1
  fi
  sleep 10
done
curl -sf -o /dev/null -H "Authorization: Bearer $VLLM_API_KEY" "$VLLM_BASE_URL/models" || {
  echo "the server did not answer within 20 minutes; see $work/serve.log" >&2
  exit 1
}
"$python" "$repo/ops/train/validate.py" check "$work"
