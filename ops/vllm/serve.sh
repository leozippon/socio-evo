#!/usr/bin/env bash
# Serve Qwen3.8-27B-FP8 with vLLM as an OpenAI-compatible API, in the foreground.
# Usage (from the repository root):
#   set -a; . ./.env; set +a; [GPUS=0,1,2,3] ops/vllm/serve.sh [extra vllm serve flags]
# GPUS defaults to all eight GPUs. Each consecutive pair runs one tensor-parallel replica (TP2) and
# vLLM balances requests across the replicas, so 8 GPUs serve as TP2 x DP4 and 4 GPUs as TP2 x DP2.
# The port comes from VLLM_BASE_URL; vLLM itself requires VLLM_API_KEY on every request.
set -euo pipefail

: "${VLLM_BASE_URL:?VLLM_BASE_URL is not set; source the repository .env first}"
: "${VLLM_API_KEY:?VLLM_API_KEY is not set; source the repository .env first}"
hostport=${VLLM_BASE_URL#*://}
hostport=${hostport%%/*}
host=${hostport%:*}
port=${hostport##*:}
if [[ ! $port =~ ^[0-9]+$ || $host == "$hostport" ]]; then
  echo "VLLM_BASE_URL must name an explicit host:port, got: $VLLM_BASE_URL" >&2
  exit 1
fi
gpus=${GPUS:-0,1,2,3,4,5,6,7}
IFS=, read -r -a gpu_list <<<"$gpus"
if [[ ! $gpus =~ ^[0-9]+(,[0-9]+)*$ ]] || (( ${#gpu_list[@]} % 2 )); then
  echo "GPUS must list an even number of GPU indices (one TP2 replica per pair), got: $gpus" >&2
  exit 1
fi

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
mkdir -p "$repo/runs/vllm"
log=$repo/runs/vllm/serve-$(date +%Y%m%d-%H%M%S).log

vllm_env=$HOME/miniconda3/envs/vllm
export CUDA_VISIBLE_DEVICES=$gpus
export PYTHONNOUSERSITE=1  # packages in ~/.local would shadow the env's own
# FlashInfer (FP8 KV attention, sampling) JIT-compiles with the env's pip CUDA toolkit and ninja.
export CUDA_HOME=$vllm_env/lib/python3.12/site-packages/nvidia/cu13 PATH=$vllm_env/bin:$PATH
# Use the Triton W8A8 block-FP8 GEMM, which has L20-tuned configs in the env (see README), not Marlin W8A16.
export VLLM_DISABLED_KERNELS=MarlinFP8ScaledMMLinearKernel,HummingFP8ScaledMMLinearKernel
export VLLM_NO_USAGE_STATS=1
unset VLLM_BASE_URL  # not a vLLM variable; vLLM reads VLLM_API_KEY directly

echo "vLLM log: $log" >&2
exec > >(tee -a "$log") 2>&1
exec "$vllm_env/bin/vllm" serve /Data2/lzp/models/Qwen3.8-27B-FP8 \
  --served-model-name qwen3.8-27b-fp8 \
  --host "$host" --port "$port" \
  --tensor-parallel-size 2 --data-parallel-size $(( ${#gpu_list[@]} / 2 )) --numa-bind \
  --max-model-len 262144 \
  --language-model-only \
  --kv-cache-dtype fp8_e4m3 \
  --max-num-batched-tokens 8192 \
  --enable-prefix-caching --enable-prompt-tokens-details \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  "$@"
