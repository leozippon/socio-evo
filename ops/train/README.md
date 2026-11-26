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

Each job writes `adapter_model.safetensors` with BF16 weights and `adapter_config.json`, in PEFT's format as vLLM 0.32 loads it for this architecture, beside `training.json`. Keys are named `base_model.model.model.language_model.layers.<i>.<self_attn|linear_attn|mlp>.<projection>.lora_<A|B>.weight`. vLLM maps that prefix onto its own module tree and packs q/k/v into qkv_proj, gate/up into gate_up_proj and the DeltaNet's in_proj_qkv/in_proj_z into in_proj_qkvz. It checks only the last component of a name when it loads an adapter, so an adapter named any other way would load and change nothing. The trainer therefore refuses to write any other key. vLLM's own loader, run on the CPU on a fitted adapter, accepted it and named every module on vLLM's module tree, each packed group complete; that the served adapter then changes the answers is what the GPU validation shows.

The trainer adapts any of the ten projections below. vLLM could also adapt the DeltaNet's per-head gates (in_proj_a, in_proj_b, 48 outputs each) and its convolution, which are not worth an adapter. It cannot place an in_proj_z adapter without one on in_proj_qkv, and the trainer refuses that combination.

| Layers | Projections | Adapter parameters per unit of rank |
| --- | --- | ---: |
| 16 full attention | q_proj, k_proj, v_proj, o_proj | 0.66 M |
| 48 Gated DeltaNet | in_proj_qkv, in_proj_z, out_proj | 1.82 M |
| 64 MLP | gate_proj, up_proj, down_proj | 4.33 M |

The recommended first settings are rank 16, alpha 32, dropout 0.05, all ten projections, learning rate 1e-4, 2 epochs, batch size 4, max_length 2048 and seed 0. The pilot on the GPUs is to tune them.

- All ten projections, because a disposition is a broad change in behaviour and because of how abliteration worked here. Comparing the abliterated checkpoint with the original shows that abliteration rewrote exactly the projections that write into the residual stream: o_proj, out_proj and down_proj in every layer, about 35–40% of their elements and 2.6% of their norm, besides the embeddings. Every other projection differs only by rounding, in 0.1% of its elements. An adapter on those writers can put back what was taken out. Three quarters of the layers are DeltaNet layers, and an adapter on q/k/v/o alone would leave their token mixing untouched.
- Rank 16 with alpha 32 (a scale of 2) is the usual setting for a few hundred short examples: 109 M parameters, 218 MB per adapter on disk.
- A learning rate of 1e-4 for two epochs moves a 27B model without overwriting it. Tool calling is protected by taking the loss only on what the model itself generates, so the prompt and the empty think block are not learnt. Beyond that it depends on the data: if every answer in a dataset is prose, the adapter learns to answer in prose, so moments in which a resident acted should keep its tool calls.

## Memory and time

A fit takes one L20 (45 GiB), the first GPU in `CUDA_VISIBLE_DEVICES`. The base holds 28.3 GiB for the whole run, and the adapter of the recommended settings, with its gradients and AdamW state, 1.6 GiB. A step adds three things:

- 0.66 MB per token for the layer inputs kept by gradient checkpointing.
- 2.5 MB per learnt token for its logits over the 248,320-token vocabulary.
- About 1.5 GiB for the layer being recomputed.

A step of 8,000 tokens with 2,000 of them learnt comes to about 42 GiB, near the limit, so batch size times the longest conversation should stay under about 8,000 tokens. The GPU validation measures the actual peak.

A token costs about 1.5 × 10¹¹ floating-point operations: six times the 24 billion parameters of the decoder's projections, for the forward pass, its recomputation and the backward pass to the inputs. At 35% of the L20's 119.5 BF16 TFLOPS that is about 3.5 ms per token, plus about half a second per step to dequantise the projections. A resident at 200 examples of about 400 tokens, fitted for two epochs (160,000 tokens), would take about 10 minutes, so eleven residents take about two hours of one L20 on the late nights and less earlier. The base loads once per run, in about a minute. These are estimates: the utilisation, the speed of the DeltaNet kernels and the length of the examples are assumptions until the GPU validation has run.

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

The GPU validation needs two free GPUs and about half an hour. It refuses to start unless both GPUs have no process and less than 1 GiB in use, and unless nothing already answers on its port (8199 by default, `PORT=` to change it):

```bash
set -a; . ./.env; set +a
GPUS=4,5 ops/train/validate.sh
```

On the real base and the first GPU it fits twice, from the same dozen conversations and seed, an adapter that teaches one harmless and unmistakable habit: every answer opens with "Ahoy!". It then serves the base with LoRA as one replica on both GPUs, hot-loads the first adapter, and compares it with the base. It passes when the adapter opens at least ten of the twelve training answers that way and the base none, and when, on a prompt it never saw, the adapter still calls the offered tool with the right argument wherever the base does, with thinking off and at low effort. It reports the steps, loss, time and peak GPU memory of each job, and whether the two fits of the same job came out identical. Everything it writes, including `report.json` and the server's log, is under `runs/train-validate/<time>/`, and it stops the server it started.
