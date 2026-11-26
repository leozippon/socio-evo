"""Fit one LoRA adapter per job on a frozen base model, in the form vLLM serves beside the base.

    <training python> -m learning.train --jobs JOBS.json

JOBS.json is {"base": dir, "lora": {...}, "jobs": [{"name": str, "dataset": file, "out": dir}]},
relative paths taken from the working directory. `lora` holds `rank`, `alpha`, `dropout`,
`target_modules`, `learning_rate`, `epochs`, `max_length`, `batch_size` and `seed`, all required.
A dataset is JSONL, one conversation a line: {"messages": [{"role": "system" | "user" |
"assistant", "content": str, "tool_calls"?: [...]}, ...]}. Each conversation is rendered with the
base's chat template, thinking off, and the loss is taken on what the model generates in each
assistant turn: its content and tool calls through the end-of-turn token, not the template's empty
think block before them.

The base is loaded once and every job fits a fresh adapter from it, seeded the same, so a job's
adapter depends only on the base, its dataset and `lora`. Every dataset is read and tokenised
before the base is loaded, so a malformed or empty dataset, or a conversation longer than
`max_length`, fails the run before any fitting. A job writes a PEFT adapter and `training.json`
under a temporary name beside `out`, which must not exist, and renames it to `out` when complete,
so a failure leaves nothing at `out`; the jobs before it stay done, and the exit status is non-zero.

The base is the block-FP8 checkpoint that vLLM serves. Its quantised projections stay in FP8 on the
GPU and are dequantised to BF16 inside each forward, which is exactly the BF16 dequantisation of
the served weights and halves the memory of a BF16 copy; ops/train/README.md gives the reasons.

This module runs under the training environment's interpreter and imports nothing from the
repository.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import torch

if not torch.cuda.is_available():
    # flash-linear-attention's kernels are Triton and need a GPU, but transformers binds them at
    # import whenever the package is importable; hiding it gives CPU runs the PyTorch reference.
    sys.modules["fla"] = None

import peft  # noqa: E402
import transformers  # noqa: E402
from peft import LoraConfig, get_peft_model, get_peft_model_state_dict  # noqa: E402
from peft.tuners.lora import LoraLayer  # noqa: E402
from safetensors import safe_open  # noqa: E402
from safetensors.torch import save_file  # noqa: E402
from torch import nn  # noqa: E402
from torch.nn import functional as F  # noqa: E402
from transformers import AutoConfig, AutoTokenizer  # noqa: E402
from transformers.initialization import no_init_weights  # noqa: E402

# The projections vLLM 0.32 applies an adapter to on this architecture (the LoRA wrappers of its
# linear layers and `packed_modules_mapping` of Qwen3_5ForConditionalGeneration): q/k/v (packed as
# qkv_proj) and o_proj of the full-attention layers, in_proj_qkv and in_proj_z (packed as
# in_proj_qkvz) and out_proj of the Gated DeltaNet layers, gate/up (packed as gate_up_proj) and
# down_proj of the MLPs. Its loader cannot place an in_proj_z adapter without one on in_proj_qkv.
# The DeltaNet's per-head gates in_proj_a/in_proj_b and its conv1d are not offered.
TARGETS = frozenset(
    {
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "in_proj_qkv",
        "in_proj_z",
        "out_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    }
)
# vLLM renames `model.language_model.` onto its own module tree and then checks only a key's
# module suffix, so an adapter whose keys lack this prefix loads and silently does nothing.
ADAPTER_KEY = re.compile(
    r"base_model\.model\.model\.language_model\.layers\.\d+\.(?:self_attn|linear_attn|mlp)"
    r"\.(\w+)\.lora_[AB]\.weight"
)
LORA_FIELDS = {
    "rank": int,
    "alpha": int,
    "dropout": float,
    "target_modules": list,
    "learning_rate": float,
    "epochs": int,
    "max_length": int,
    "batch_size": int,
    "seed": int,
}
ROLES = frozenset({"system", "user", "assistant"})


def check(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True)
class Job:
    name: str
    dataset: Path
    out: Path


def read_jobs(path: Path) -> tuple[Path, dict, list[Job]]:
    """The base, the LoRA settings and the jobs of a JOBS.json, checked in full."""
    spec = json.loads(path.read_text(encoding="utf-8"))
    check(
        isinstance(spec, dict) and set(spec) == {"base", "lora", "jobs"},
        f"{path}: expected exactly the keys base, lora, jobs",
    )
    check(isinstance(spec["base"], str) and spec["base"], f"{path}: base must be a path")
    base = Path(spec["base"])
    check((base / "config.json").is_file(), f"{base}: not a model directory")

    lora = spec["lora"]
    check(
        isinstance(lora, dict) and set(lora) == set(LORA_FIELDS),
        f"{path}: lora must have exactly the keys {', '.join(LORA_FIELDS)}",
    )
    for key, kind in LORA_FIELDS.items():
        value = lora[key]
        if kind is float:
            check(
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and math.isfinite(value),
                f"lora.{key} must be a number",
            )
            lora[key] = float(value)
        else:
            check(type(value) is kind, f"lora.{key} must be {kind.__name__}")
    for key in ("rank", "alpha", "epochs", "batch_size"):
        check(lora[key] >= 1, f"lora.{key} must be at least 1")
    check(lora["max_length"] >= 2, "lora.max_length must be at least 2")
    check(lora["seed"] >= 0, "lora.seed must not be negative")
    check(0 <= lora["dropout"] < 1, "lora.dropout must be in [0, 1)")
    check(lora["learning_rate"] > 0, "lora.learning_rate must be positive")
    targets = lora["target_modules"]
    check(
        targets and all(isinstance(t, str) for t in targets) and len(set(targets)) == len(targets),
        "lora.target_modules must be a non-empty list of distinct names",
    )
    check(
        set(targets) <= TARGETS,
        f"lora.target_modules {sorted(set(targets) - TARGETS)} are not servable; "
        f"choose from {sorted(TARGETS)}",
    )
    check(
        "in_proj_z" not in targets or "in_proj_qkv" in targets,
        "lora.target_modules: vLLM cannot serve in_proj_z without in_proj_qkv",
    )

    jobs = spec["jobs"]
    check(isinstance(jobs, list) and jobs, f"{path}: jobs must be a non-empty list")
    parsed = []
    for job in jobs:
        check(
            isinstance(job, dict) and set(job) == {"name", "dataset", "out"},
            f"{path}: each job must have exactly the keys name, dataset, out",
        )
        check(
            all(isinstance(job[k], str) and job[k] for k in job),
            f"{path}: job fields must be non-empty strings",
        )
        parsed.append(Job(job["name"], Path(job["dataset"]), Path(job["out"]).absolute()))
    check(len({j.name for j in parsed}) == len(parsed), f"{path}: job names must be distinct")
    check(len({j.out for j in parsed}) == len(parsed), f"{path}: job outputs must be distinct")
    for job in parsed:
        check(job.dataset.is_file(), f"job {job.name}: dataset {job.dataset} does not exist")
        check(not job.out.exists(), f"job {job.name}: output {job.out} already exists")
    return base, lora, parsed


def read_dataset(path: Path) -> list[list[dict]]:
    """The conversations of a JSONL dataset, checked, tool-call arguments parsed as vLLM does."""
    conversations = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        where = f"{path}:{number}"
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{where}: not JSON ({error})") from None
        check(
            isinstance(record, dict) and set(record) == {"messages"},
            f'{where}: expected {{"messages": [...]}}',
        )
        messages = record["messages"]
        check(
            isinstance(messages, list) and messages, f"{where}: messages must be a non-empty list"
        )
        for message in messages:
            check(
                isinstance(message, dict)
                and message.get("role") in ROLES
                and isinstance(message.get("content"), str),
                f"{where}: a message needs a role (system, user or assistant) and string content",
            )
            check(
                set(message) <= {"role", "content", "tool_calls"}, f"{where}: unknown message keys"
            )
            if "tool_calls" in message:
                check(
                    message["role"] == "assistant",
                    f"{where}: only assistant messages carry tool_calls",
                )
                message["tool_calls"] = [tool_call(call, where) for call in message["tool_calls"]]
                if not message["tool_calls"]:
                    del message["tool_calls"]
        check(
            any(m["role"] == "assistant" for m in messages),
            f"{where}: no assistant turn to learn from",
        )
        conversations.append(messages)
    check(conversations, f"{path}: the dataset is empty")
    return conversations


def tool_call(call: object, where: str) -> dict:
    check(
        isinstance(call, dict)
        and set(call) <= {"id", "type", "function"}
        and call.get("type", "function") == "function"
        and isinstance(call.get("function"), dict),
        f'{where}: a tool call must be {{"type": "function", "function": {{...}}}}',
    )
    function = call["function"]
    check(
        set(function) <= {"name", "arguments"}
        and isinstance(function.get("name"), str)
        and function["name"],
        f"{where}: a tool call's function needs a name",
    )
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            raise ValueError(f"{where}: tool call arguments are not JSON") from None
    check(isinstance(arguments, dict), f"{where}: tool call arguments must be a JSON object")
    return {**call, "function": {"name": function["name"], "arguments": arguments}}


def render(tokenizer, messages: list[dict], generation: bool) -> str:
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=generation, enable_thinking=False
    )


def encode(tokenizer, messages: list[dict], max_length: int) -> tuple[list[int], list[bool]]:
    """The conversation's token ids and whether each is learnt: the tokens each assistant turn
    generates after the generation prompt with thinking off, through its end-of-turn token."""
    text = render(tokenizer, messages, False)
    end = tokenizer.eos_token + "\n"
    spans = []
    for index, message in enumerate(messages):
        if message["role"] != "assistant":
            continue
        prompt = render(tokenizer, messages[:index], True)
        turn = render(tokenizer, messages[: index + 1], False)
        check(
            text.startswith(turn) and turn.startswith(prompt) and turn.endswith(end),
            "the chat template does not render this conversation turn by turn",
        )
        # The newline the template writes after the end-of-turn token is not generated.
        spans.append((len(prompt), len(turn) - 1))
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    ids, offsets = encoded["input_ids"], encoded["offset_mapping"]
    check(len(ids) <= max_length, f"{len(ids)} tokens, more than lora.max_length {max_length}")
    starts, ends = {a for a, _ in offsets}, {b for _, b in offsets}
    check(
        all(a in starts and b in ends for a, b in spans),
        "an assistant turn does not fall on token boundaries",
    )
    return ids, [any(a <= start < b for a, b in spans) for start, _ in offsets]


class Fp8Linear(nn.Linear):
    """A frozen block-FP8 projection as the checkpoint stores it, dequantised in each forward.

    The weight it computes with is the FP8 value times its block's BF16 scale, which is exact in
    float32 and rounded once to BF16, as transformers dequantises the same checkpoint. PEFT reads
    `compute_dtype` for the adapter's dtype, which would otherwise follow the FP8 weight."""

    compute_dtype = torch.bfloat16

    def __init__(self, weight: torch.Tensor, scale: torch.Tensor) -> None:
        nn.Module.__init__(self)
        self.out_features, self.in_features = weight.shape
        self.weight = nn.Parameter(weight, requires_grad=False)
        self.weight_scale_inv = nn.Parameter(scale, requires_grad=False)
        self.register_parameter("bias", None)

    def dequantised(self) -> torch.Tensor:
        rows, cols = self.weight_scale_inv.shape
        blocks = self.weight.view(rows, self.out_features // rows, cols, self.in_features // cols)
        weight = blocks.to(self.compute_dtype) * self.weight_scale_inv.view(rows, 1, cols, 1)
        return weight.view(self.out_features, self.in_features)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.linear(x, self.dequantised())


def load_base(path: Path, device: torch.device) -> nn.Module:
    """The checkpoint's model with every weight loaded and frozen, its FP8 projections kept FP8.

    The model is built on the CPU without initialisation (the BF16 placeholders of the FP8
    projections are never touched, so they take no memory), the checkpoint's tensors are put in
    place, and the whole is moved to `device`. Every weight of the model must come from the
    checkpoint and every tensor of the checkpoint must be used, except the multi-token-prediction
    head `mtp.*`, which vLLM does not run here either."""
    config = AutoConfig.from_pretrained(path)
    index = path / "model.safetensors.index.json"
    files = (
        sorted(set(json.loads(index.read_text())["weight_map"].values()))
        if index.exists()
        else ["model.safetensors"]
    )
    default = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        with no_init_weights():
            model = getattr(transformers, config.architectures[0])(config)
    finally:
        torch.set_default_dtype(default)

    with ExitStack() as stack:
        shards = [stack.enter_context(safe_open(path / name, framework="pt")) for name in files]
        where = {
            key: shard for shard in shards for key in shard.keys() if not key.startswith("mtp.")
        }
        quantised = [
            key.removesuffix(".weight_scale_inv")
            for key in where
            if key.endswith(".weight_scale_inv")
        ]
        if quantised:
            quant = getattr(config, "quantization_config", None) or {}
            check(
                quant.get("quant_method") == "fp8"
                and quant.get("fmt") == "e4m3"
                and quant.get("activation_scheme") == "dynamic",
                f"{path}: weight scales without a dynamic e4m3 fp8 quantization_config",
            )
            block = tuple(quant["weight_block_size"])
        for name in quantised:
            weight = where[f"{name}.weight"].get_tensor(f"{name}.weight")
            scale = where[f"{name}.weight_scale_inv"].get_tensor(f"{name}.weight_scale_inv")
            linear = model.get_submodule(name)
            check(
                type(linear) is nn.Linear
                and linear.bias is None
                and weight.shape == (linear.out_features, linear.in_features),
                f"{name}: the checkpoint's FP8 weight does not fit the model's projection",
            )
            check(
                weight.dtype == torch.float8_e4m3fn
                and scale.dtype == torch.bfloat16
                and weight.shape == (scale.shape[0] * block[0], scale.shape[1] * block[1]),
                f"{name}: expected an e4m3 weight with BF16 scales of {block} blocks",
            )
            parent, _, child = name.rpartition(".")
            setattr(model.get_submodule(parent), child, Fp8Linear(weight, scale))

        state = model.state_dict(keep_vars=True)
        check(
            len({t.data_ptr() for t in state.values()}) == len(state),
            "the model shares weights between names",
        )
        in_place = {f"{n}.weight" for n in quantised} | {f"{n}.weight_scale_inv" for n in quantised}
        used = set(in_place)
        with torch.no_grad():
            for key, shard in where.items():
                if key in in_place:
                    continue
                check(
                    key in state,
                    f"{key} of the checkpoint is not a weight of {config.architectures[0]}",
                )
                tensor = shard.get_tensor(key)
                check(
                    tensor.shape == state[key].shape,
                    f"{key}: shape {tuple(tensor.shape)} in the checkpoint",
                )
                state[key].copy_(tensor)
                used.add(key)
        missing = sorted(set(state) - used)
        check(not missing, f"{path}: weights missing from the checkpoint: {missing[:5]}")
    model.requires_grad_(False)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    return model.to(device)


def batches(examples: list, batch_size: int, epochs: int, seed: int) -> Iterator[list]:
    generator = torch.Generator().manual_seed(seed)
    for _ in range(epochs):
        order = torch.randperm(len(examples), generator=generator).tolist()
        for start in range(0, len(order), batch_size):
            yield [examples[i] for i in order[start : start + batch_size]]


def batch_loss(model: nn.Module, batch: list, device: torch.device) -> torch.Tensor:
    """Mean cross-entropy over the batch's learnt tokens, right-padded; the vocabulary projection
    is taken only at the positions that predict a learnt token."""
    width = max(len(ids) for ids, _ in batch)
    ids = torch.zeros(len(batch), width, dtype=torch.long)
    mask = torch.zeros(len(batch), width, dtype=torch.long)
    learnt = torch.zeros(len(batch), width, dtype=torch.bool)
    for row, (tokens, labels) in enumerate(batch):
        ids[row, : len(tokens)] = torch.tensor(tokens)
        mask[row, : len(tokens)] = 1
        learnt[row, : len(tokens)] = torch.tensor(labels)
    ids, mask, learnt = ids.to(device), mask.to(device), learnt.to(device)
    hidden = model.model.language_model(
        input_ids=ids, attention_mask=mask, use_cache=False
    ).last_hidden_state
    target = learnt[:, 1:]
    logits = model.lm_head(hidden[:, :-1][target]).float()
    return F.cross_entropy(logits, ids[:, 1:][target])


def fit(
    model: nn.Module, examples: list, lora: dict, device: torch.device
) -> tuple[list[float], dict, LoraConfig]:
    """A fresh adapter fitted on `examples`; the model is returned to the bare base afterwards."""
    torch.manual_seed(lora["seed"])
    config = LoraConfig(
        r=lora["rank"],
        lora_alpha=lora["alpha"],
        lora_dropout=lora["dropout"],
        target_modules=list(lora["target_modules"]),
        bias="none",
    )
    adapted = get_peft_model(model, config)
    try:
        wrapped = [name for name, module in model.named_modules() if isinstance(module, LoraLayer)]
        check(
            all(ADAPTER_KEY.fullmatch(f"base_model.model.{n}.lora_A.weight") for n in wrapped),
            "an adapter was placed outside the language model's layers",
        )
        absent = set(lora["target_modules"]) - {n.rsplit(".", 1)[-1] for n in wrapped}
        check(not absent, f"lora.target_modules {sorted(absent)} match no projection of the base")
        parameters = [p for p in adapted.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(parameters, lr=lora["learning_rate"], weight_decay=0.0)
        adapted.train()
        losses = []
        for batch in batches(examples, lora["batch_size"], lora["epochs"], lora["seed"]):
            loss = batch_loss(model, batch, device)
            losses.append(loss.item())
            check(math.isfinite(losses[-1]), f"the loss is {losses[-1]} at step {len(losses)}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        state = {
            key: value.detach().to(device="cpu", dtype=torch.bfloat16).contiguous()
            for key, value in get_peft_model_state_dict(
                adapted, save_embedding_layers=False
            ).items()
        }
        return losses, state, adapted.peft_config["default"]
    finally:
        adapted.unload()


def write_adapter(directory: Path, state: dict, config: LoraConfig, record: dict) -> None:
    targets = set(config.target_modules)
    for key in state:
        match = ADAPTER_KEY.fullmatch(key)
        check(
            match and match.group(1) in targets,
            f"adapter key {key} is not one vLLM loads for this base",
        )
    save_file(state, str(directory / "adapter_model.safetensors"), metadata={"format": "pt"})
    config.save_pretrained(str(directory))
    (directory / "training.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def publish(out: Path, write) -> None:
    """Run `write` on a fresh directory beside `out` and rename it to `out` once it returns."""
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.parent / f".{out.name}.partial-{os.getpid()}"
    partial.mkdir()
    try:
        write(partial)
        check(not out.exists(), f"{out} appeared while the job ran")
        partial.rename(out)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m learning.train", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--jobs", type=Path, required=True, help="the JOBS.json file")
    arguments = parser.parse_args(argv)
    base, lora, jobs = read_jobs(arguments.jobs)
    tokenizer = AutoTokenizer.from_pretrained(base)
    prepared = []
    for job in jobs:
        try:
            examples = [encode(tokenizer, m, lora["max_length"]) for m in read_dataset(job.dataset)]
        except Exception as error:
            raise ValueError(f"job {job.name}: {error}") from error
        prepared.append((job, examples, hashlib.sha256(job.dataset.read_bytes()).hexdigest()))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    started = time.monotonic()
    model = load_base(base, device)
    print(
        f"base {base} loaded on {device} in {time.monotonic() - started:.0f} s",
        file=sys.stderr,
        flush=True,
    )
    versions = {
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "peft": peft.__version__,
    }
    gpu = device.type == "cuda"
    for job, examples, digest in prepared:
        started = time.monotonic()
        if gpu:
            torch.cuda.reset_peak_memory_stats(device)
        losses, state, config = fit(model, examples, lora, device)
        record = {
            "name": job.name,
            "base": str(base.absolute()),
            "dataset": str(job.dataset.absolute()),
            "dataset_sha256": digest,
            "lora": lora,
            "examples": len(examples),
            "tokens": sum(len(ids) for ids, _ in examples),
            "trained_tokens": sum(sum(learnt) for _, learnt in examples),
            "steps": len(losses),
            "loss": losses,
            "wall_seconds": round(time.monotonic() - started, 3),
            "device": torch.cuda.get_device_name(device) if gpu else "cpu",
            "peak_gpu_memory_bytes": torch.cuda.max_memory_allocated(device) if gpu else None,
            "versions": versions,
        }
        publish(
            job.out, functools.partial(write_adapter, state=state, config=config, record=record)
        )
        print(
            f"{job.name}: {len(losses)} steps, loss {losses[0]:.4f} -> {losses[-1]:.4f}, "
            f"{record['wall_seconds']:.0f} s -> {job.out}",
            file=sys.stderr,
            flush=True,
        )


if __name__ == "__main__":
    main()
