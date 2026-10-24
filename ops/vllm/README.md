# Local model service (vLLM)

This directory runs the project's local language model: the official FP8 checkpoint of Qwen3.8-27B, served by vLLM 0.32.0 as an OpenAI-compatible API at `VLLM_BASE_URL`, under the model name `qwen3.8-27b-fp8`. Every request must carry `VLLM_API_KEY`. The service supports tool calling (`tools`, `tool_choice`, parallel calls), thinking with `reasoning_effort`, streaming, prefix caching and the model's native 262,144-token context. It is text-only: the vision tower is not loaded.

## Start and stop

From the repository root:

```bash
set -a; . ./.env; set +a
setsid nohup ops/vllm/serve.sh >/dev/null 2>&1 &                 # all eight GPUs
GPUS=0,1,2,3 setsid nohup ops/vllm/serve.sh >/dev/null 2>&1 &    # four GPUs
```

The script runs vLLM in the foreground, so it can also sit under systemd or a terminal; extra arguments are passed to `vllm serve` and override its defaults. It takes the port from `VLLM_BASE_URL`, and vLLM reads the key from `VLLM_API_KEY` in its environment, so the key never appears on a command line. The server answers after two to five minutes; the first start after a vLLM or kernel change takes longer because it compiles. Each start writes its log to `runs/vllm/serve-<time>.log`.

To check and to stop it (the bracket keeps `pkill` from matching a shell that runs the command):

```bash
curl -s -H "Authorization: Bearer $VLLM_API_KEY" "$VLLM_BASE_URL/models"
pkill -TERM -f 'bin/vllm serve /Data2/lzp/models/Qwen3.8-27B-FP[8]'
```

`ops/vllm/verify.py` checks every feature above against a running server and `ops/vllm/bench.py` reproduces the measurements below; both run with the `socio-evo` environment's Python.

## GPU layout

Each consecutive pair of GPUs in `GPUS` runs one replica of the model split across the pair (tensor parallel 2), and vLLM spreads requests over the replicas (data parallel). Eight GPUs therefore serve as four replicas on (0,1), (2,3), (4,5), (6,7), and four GPUs as two. List pairs that share a NUMA node (GPUs 0–3 and 4–7 on this machine); each engine is bound to its GPUs' node.

Two cards per replica is the sweet spot on these PCIe-only L20s. The model has four KV heads, so a replica can span one, two or four cards, and four is slow: vLLM's fast all-reduce works only between two PCIe cards, and a four-card replica fell to 151 output tokens/s at 32 concurrent requests, against 574 for two two-card replicas on the same four GPUs. One replica pipelined across all eight cards (TP2 × PP4) shares a single prefix cache but reached only 451–479 tokens/s at 32 requests, about a third less than four replicas. One-card replicas were not measured.

## Configuration

The weights are the vendor's block-FP8 checkpoint at `/Data2/lzp/models/Qwen3.8-27B-FP8` (also at `/Data/public/Qwen3.8-27B-FP8`). The weight files match the repository's `crc32.txt` and every small file matches its git blob id; `crc32.txt` itself is stale upstream for `chat_template.jinja`, `generation_config.json` and `tokenizer_config.json`, which differ from it identically in the local BF16 copy.

Several choices were adopted from the L20 deployment in `/Data/lzp/vllm-service` and kept because they measured faster here:

- Matrix products use vLLM's Triton FP8 kernel with five L20-tuned configuration files, instead of the Marlin kernel vLLM picks by default on this GPU, which dequantises to BF16. The files were copied from that deployment's environment into the `vllm` environment's `vllm/model_executor/layers/quantization/utils/configs/` (shapes N,K = 8192,5120; 7168,5120; 17408,5120; 5120,3072; 5120,8704; they apply only to two-card replicas). They are not part of the vLLM package, so reinstalling vLLM removes them and must be followed by copying them again.
- The KV cache is FP8 (`fp8_e4m3`), which uses the FlashInfer attention backend and doubles capacity to 1,535,199 tokens per replica, 5.86 full-length contexts. The checkpoint ships no KV scales, so vLLM warns that it uses a scale of 1.0; the reference deployment's accuracy study found no regression from this, and the long-context checks below pass.
- Prefill is chunked at 8,192 tokens per step, engines are bound to their NUMA node, and sampling uses FlashInfer.

Prefix caching on this hybrid model works in blocks of 784 tokens, so up to 783 tokens at the end of a shared prefix are recomputed. The model's multi-token-prediction head is not used: the reference deployment measured it slower at 4–8 concurrent requests, where speculation no longer pays, and it rejects `min_p` and `logit_bias`.

The environment needed three local repairs, all inside `~/miniconda3/envs/vllm`. Packages in `~/.local` shadow the environment's own, so the script sets `PYTHONNOUSERSITE=1`. FlashInfer's precompiled kernels are hosted on GitHub, which this machine cannot reach, so FlashInfer compiles its kernels on first use (cached in `~/.cache/flashinfer`); that needed the pip CUDA compiler pinned to the 13.0 release matching PyTorch (`cuda-toolkit[nvcc,nvvm]==13.0.3`) and two links in `site-packages/nvidia/cu13` (`lib64` → `lib`, `libcudart.so` → `libcudart.so.13`).

## Using it from clients

- Reasoning arrives in `message.reasoning` (streaming: `delta.reasoning`); vLLM 0.32 no longer names it `reasoning_content`, though it still accepts that name in request messages.
- `reasoning_effort` accepts `low`, `medium` and `xhigh` (the default); `none` turns thinking off, as does `chat_template_kwargs: {"enable_thinking": false}`. The chat template rejects `high` and `minimal` with a 400. The effort reaches the template, but its effect on reasoning length is modest: over 36 samples of three short puzzles, low averaged 963 reasoning characters, medium 1,089 and xhigh 972.
- Requests are balanced across replicas by load, not by conversation, so consecutive turns of one conversation often land on a replica that has not cached its prefix. A client keeps a conversation on one replica by sending the header `X-data-parallel-rank: <n>`, with `n` from 0 to the replica count minus one (for example a hash of the agent id). In a 32-agent, four-turn test this raised the prefix-cache hit rate from 45% to 63% of prompt tokens and output throughput from 705 to 801 tokens/s. Without it, the runtime's integration test `tests/agent/test_vllm.py` fails its assertion that the second reply reuses cached prompt tokens; it passed on a single-replica layout.

## Measurements

All measurements are from 2026-10-24 with prompts unique to each run. The load test keeps 32 or 64 requests in flight until twice that many have finished; each request carries a ~6,100-token agent prompt with five tools, `reasoning_effort: low`, and exactly 1,024 output tokens. Throughput counts output tokens across all requests; latency is per request.

| Layout and settings | Concurrent | Output tokens/s | Mean time to first token | Mean / p90 latency |
| --- | ---: | ---: | ---: | ---: |
| 8 GPUs, vLLM defaults (Marlin, BF16 KV, 2,048-token chunks) | 32 | 686 | 8.4 s | 46.5 / 57.8 s |
| | 64 | 964 | 12.0 s | 65.7 / 87.3 s |
| 8 GPUs, current settings, run 1 | 32 | 695 | 6.6 s | 44.1 / 54.3 s |
| | 64 | 1,039 | 11.9 s | 59.4 / 71.5 s |
| 8 GPUs, current settings, run 2 | 32 | 768 | 7.2 s | 41.4 / 44.1 s |
| | 64 | 1,146 | 11.2 s | 57.0 / 68.0 s |
| 4 GPUs (TP2 × DP2), current settings | 32 | 574 | 11.0 s | 57.0 / 68.4 s |
| | 64 | 761 | 16.8 s | 85.9 / 116.9 s |

Single changes measured at 32 requests on eight GPUs: the untuned Triton kernel gave 616 tokens/s and the tuned one 669, against 686–688 for Marlin, but with a faster first token (5.2 s against 7.3–8.4 s); FP8 KV, 8,192-token chunks, NUMA binding and FlashInfer sampling together brought it to 695–768. In the multi-turn test the current settings reached 705 tokens/s against 619 for the defaults.

A single request on an idle replica with a 59,849-token prompt took 18.3 s to the first token and 20.2 s in total. Needle questions at 59,849, 169,511 and 243,822 prompt tokens were all answered correctly; the last took 128.5 s to the first token.

## One server per group

vLLM's data-parallel router sends each request to the least-loaded replica, not to the replica that holds the conversation's prefix, so under four replicas a resident's next request usually misses the cache it had just built (the runtime's integration test, which expects cached prompt tokens on the second request, fails against the four-replica server and passes against one replica). The experiments therefore run one independent two-card server per group, each on its own port, and every resident of a group always reaches the same replica:

```bash
set -a; . ./.env; set +a
for i in 0 1 2 3; do
  GPUS=$((2*i)),$((2*i+1)) VLLM_BASE_URL=http://127.0.0.1:$((8011+i))/v1 setsid nohup ops/vllm/serve.sh >/dev/null 2>&1 &
done
```

A group's run is given its server through `VLLM_BASE_URL` when it is started or resumed; the frozen configuration holds only the variable. When the machine is reduced to four GPUs, two servers remain and two groups share each.
