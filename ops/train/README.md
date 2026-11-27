# Training the residents' adapters

Each resident learns at night into a LoRA adapter of its own, fitted afresh from the base model by `learning.train` and served by vLLM beside the base (`LORA=1` in [ops/vllm](../vllm/README.md)). This directory holds the trainer's environment and the validation of the whole path on the GPUs. The trainer's contract, the jobs file it takes, the datasets and what each job writes, is the docstring of `learning/train.py`.

## Environment

The trainer runs under its own interpreter, `/Data2/lzp/envs/socio-evo-train/bin/python`: a Python 3.12 virtual environment on `/Data2`, its packages hard-linked from the uv cache shared on `/Data2/lzp/uv-cache`. It holds torch 2.14.0 built for CUDA 13.0, which the driver (CUDA 13.2) runs, and transformers 5.19.0, the release of the serving environment, so that the chat template renders the same in training and in serving. It also holds peft 0.22.0, accelerate 1.16.0, safetensors 0.8.0 and flash-linear-attention 0.6.0, whose Triton kernels run the Gated DeltaNet layers in place of transformers' far slower reference code. `requirements.in` lists these pins and `requirements.txt` is the complete lock compiled from it. `setup-env.sh` creates the environment, or brings an existing one back to exactly the lock, and can be run again at any time:

```bash
ops/train/setup-env.sh
# after changing a pin in requirements.in:
UV_CACHE_DIR=/Data2/lzp/uv-cache uv pip compile ops/train/requirements.in -o ops/train/requirements.txt \
  --python-version 3.12 --python-platform x86_64-manylinux_2_28 --no-header
```

causal-conv1d is not installed. PyPI has only its source, which compiles CUDA code and first tries to fetch a prebuilt wheel from GitHub, which this machine cannot reach. Without it transformers runs the DeltaNet's four-tap convolution as PyTorch's depthwise convolution, a small cost beside the projections. flash-linear-attention's kernels need a GPU, so on the CPU (in the tests) the trainer hides the package and transformers uses its reference code.

## The base weights

vLLM applies an adapter on top of the weights it serves, the abliterated Qwen3.8-27B in block FP8 (`/Data2/lzp/models/Qwen3.8-27B-Uncensored-FP8`; no BF16 copy of the abliterated weights exists), so the adapter is fitted against exactly those weights. The checkpoint stores 400 projections as e4m3 FP8 with one BF16 scale for each 128 × 128 block, 24.3 billion parameters. These are q, k, v and o of the 16 full-attention layers; in_proj_qkv, in_proj_z and out_proj of the 48 Gated DeltaNet layers; and gate, up and down of the 64 MLPs. The embeddings, the head, the norms, the DeltaNet's convolutions, gates and decays, and the vision tower are BF16, 3.0 billion parameters.

The trainer loads this checkpoint as it is. The FP8 projections stay FP8 on the GPU, frozen, and each is dequantised to BF16 inside its forward, with the gradient flowing through to the adapter. The weight it computes with is the FP8 value times its block's scale, exact in float32 and rounded once to BF16. On the real checkpoint this matches transformers' own FP8 dequantisation bit for bit for all 400 projections, and the model loaded this way continues "The capital of France is" with " Paris.".

The alternatives were worse:

- A one-time dequantisation to a BF16 checkpoint computes with the same weights but takes 55 GB: two L20s per fit, only one of them busy at a time, and a 55 GB copy on disk.
- transformers' own FP8 layer cannot be trained through, because its Triton kernel has no backward pass.
- A 4-bit (NF4) base fits one card easily, but its weights differ from the served ones by roughly 10% per element, about three times FP8's own rounding, so the adapter would be fitted to a model other than the one that runs it.

What remains different from serving is the activations: vLLM quantises them to FP8 in each projection, per group of 128 values, and training does not imitate that.

## Adapters

Each job writes `adapter_model.safetensors` with BF16 weights and `adapter_config.json`, in PEFT's format as vLLM 0.32 loads it for this architecture, beside `training.json`. Keys are named `base_model.model.model.language_model.layers.<i>.<self_attn|linear_attn|mlp>.<projection>.lora_<A|B>.weight`. vLLM maps that prefix onto its own module tree and packs q/k/v into qkv_proj, gate/up into gate_up_proj and the DeltaNet's in_proj_qkv/in_proj_z into in_proj_qkvz. It checks only the last component of a name when it loads an adapter, so an adapter named any other way would load and change nothing. The trainer therefore refuses to write any other key. vLLM's own loader accepts a fitted adapter and names every module on vLLM's module tree, each packed group complete. Served on two GPUs as the residents' adapters are, an adapter cut down to any one of the ten projections moved the log-probability of the answer it was taught as much as it does in the trainer's own model, to within the 0.3 nats by which the served base itself differs from the trainer's (vLLM quantises activations); a zeroed adapter changed nothing. vLLM thus applies every projection, the packed ones included, as it was fitted.

The trainer adapts any of the ten projections below. vLLM could also adapt the DeltaNet's per-head gates (in_proj_a, in_proj_b, 48 outputs each) and its convolution, which are not worth an adapter. It cannot place an in_proj_z adapter without one on in_proj_qkv, and the trainer refuses that combination.

| Layers | Projections | Adapter parameters per unit of rank |
| --- | --- | ---: |
| 16 full attention | q_proj, k_proj, v_proj, o_proj | 0.66 M |
| 48 Gated DeltaNet | in_proj_qkv, in_proj_z, out_proj | 1.82 M |
| 64 MLP | gate_proj, up_proj, down_proj | 4.33 M |

The recommended first settings are rank 16, alpha 32, dropout 0.05, all ten projections, learning rate 1e-4, 2 epochs, batch size 1, max_length 8192 and seed 0, the same in every arm (learning/config.py); the pilot on the GPUs is to tune them. One conversation a step keeps a step within what one card holds (below), and a max_length of 8192 keeps the longest moments as they happened, which run to about 6,700 tokens, so that the Raw arm learns from the same moments as the others.

- All ten projections, because a disposition is a broad change in behaviour and because of how abliteration worked here. Comparing the abliterated checkpoint with the original shows that abliteration rewrote exactly the projections that write into the residual stream: o_proj, out_proj and down_proj in every layer, about 35–40% of their elements and 2.6% of their norm, besides the embeddings. Every other projection differs only by rounding, in 0.1% of its elements. An adapter on those writers can put back what was taken out. Three quarters of the layers are DeltaNet layers, and an adapter on q/k/v/o alone would leave their token mixing untouched.
- Rank 16 with alpha 32 (a scale of 2) is the usual setting for a few hundred short examples: 109 M parameters, 218 MB per adapter on disk.
- A learning rate of 1e-4 for two epochs moves a 27B model without overwriting it. Tool calling is protected by taking the loss only on what the model itself generates, its replies and their tool calls, so the prompt, the tool results and the empty think block are not learnt. Beyond that it depends on the data. On the GPUs, 48 short answers, all prose, left tool calling as the base has it (60 of 60 sampled calls on three unseen prompts, with thinking off and as many at low effort), and the habit they taught held after the model had thought (11 of 12 answers at low effort). Twelve such answers were too few: their adapter called the tool in 18 of 60 samples with thinking off, and fitting those twelve for four times as many epochs at twice the rate memorised them, until at low effort it wrote the answer in place of its thinking and replied with nothing. An adapter fitted on a handful of examples learns those examples rather than what they share, which bears on the first nights, when a resident has kept only a few moments.

## Memory and time

A fit takes one L20, the first GPU in `CUDA_VISIBLE_DEVICES`. The figures here were measured on the GPUs with the recommended settings, one conversation a step. The base and a fresh adapter hold 28.7 GiB for the whole run. A step's peak grows by about 1.3 MB per token of its conversation: 31.1 GiB at 400 tokens, 35.5 at 4,096 and 40.4 at 8,000 with a quarter of them learnt, of the 44.5 GiB the card offers. The peak falls in the backward pass through the recomputed layers, not at the logits, so it hardly depends on how many tokens are learnt, and computing the loss in pieces saved nothing. A step of 8,192 tokens, the recommended max_length, is thus about the most one card holds. Steps of very different lengths fragment PyTorch's cache of GPU memory, and a step of 8,000 tokens after a run of short ones once failed for want of room to launch a Triton kernel; the trainer therefore has PyTorch allocate in expandable segments, with which the same run completes.

The trainer computes with deterministic kernels, so that one seed gives one adapter. Without them the backward pass of flash attention in the full-attention layers, among others, sums in a varying order, and two fits of the same 24 examples of 340 tokens differed by 7% of the adapter's norm, in one run as in two. With them the fits are bit-identical, at 10–15% more time. flash-linear-attention's kernels run the DeltaNet layers on the L20 (transformers warns only of the convolution's fallback).

A step of 400 tokens takes 1.64 s and one of 800 tokens 2.52 s; long steps take 3.2 ms per token (25.9 s at 8,000 tokens), about 40% of the L20's 119.5 BF16 TFLOPS at the 1.5 × 10¹¹ operations a token costs. The base loads in about 15 s, and each new range of lengths costs some seconds of kernel tuning once per run. Fitting eleven residents for two epochs on examples of about 400 tokens therefore takes:

| Examples per resident | One resident | Eleven residents |
| ---: | ---: | ---: |
| 50 | 2.7 min | 30 min |
| 100 | 5.5 min | 1 h |
| 224 | 12.3 min | 2 h 15 min |

A night shares its fits among the first two GPUs of its list that have room (`learning.trainer.gpus_at_once`; each trainer loads the base anew), one trainer process on each, so the eleven residents' time is about halved. It uses only a GPU with room, by default 42 GiB free, the peak of a step of 8,192 tokens above with the CUDA context beside it. Other users' jobs come and go on these GPUs, so a night that finds none with room waits for one, looking every minute for up to six hours, and then fails, to be resumed. The run's log and the night's `done.json` say which GPUs it used, after how long a wait, which fits ran on each and how long each took. A GPU that another job fills once a fit has begun fails that fit, and with it the night. `learning/fit.py` describes how the jobs are shared, and `learning/config.py` the two settings.

## Validation

The CPU test fits adapters on a tiny randomly initialised model of the same architecture, stored as the served checkpoint is, with the served tokenizer and chat template. It checks:

- that the loss falls;
- that only what the assistant generates carries loss;
- the files and key names vLLM loads;
- that a failing run leaves no output;
- that one seed gives one adapter;
- that settings vLLM could not serve are refused.

It takes about two minutes and runs with the training environment's interpreter, from the repository root:

```bash
/Data2/lzp/envs/socio-evo-train/bin/python -m pytest tests/learning/test_train.py
```

The GPU validation needs two free GPUs and about a quarter of an hour, of which vLLM's start takes three to nine minutes (the longer after a vLLM or kernel change, when it compiles). It refuses to start unless both GPUs have no process and less than 1 GiB in use, and unless nothing already answers on its port (8199 by default, `PORT=` to change it):

```bash
set -a; . ./.env; set +a
GPUS=4,5 ops/train/validate.sh
```

On the real base and the first GPU it fits twice, from the same 49 conversations and seed and with the recommended settings, an adapter that teaches one harmless and unmistakable habit: every answer opens with "Ahoy!". One conversation is long enough to reach the kernels whose sums depend on the order of work. It then serves the base with LoRA as one replica on both GPUs, hot-loads the first adapter, and compares it with the base. It passes when the adapter opens at least ten of twelve of its training answers that way and the base none, and when, on a prompt it never saw, the adapter still calls the offered tool with the right argument wherever the base does, with thinking off and at low effort. It reports the steps, loss, time and peak GPU memory of each job, whether the two fits of the same job came out identical, and how many of the twelve answers open with the habit at low effort, after the model has thought. Everything it writes, including `report.json` and the server's log, is under `runs/train-validate/<time>/`, and it stops the server it started.
