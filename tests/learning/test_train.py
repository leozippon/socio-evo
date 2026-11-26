"""The trainer (learning.train) end to end on the CPU, on a tiny randomly initialised model of the
served architecture (Qwen3_5ForConditionalGeneration with three Gated DeltaNet layers and one
full-attention layer) stored as the served checkpoint is: block-FP8 projections with BF16 scales in
a second shard, and a multi-token-prediction head, quantised too, that the model has no place for.
It uses the served checkpoint's tokenizer and chat template. The trainer runs as its command, with
the GPUs hidden.

Run with the training environment's interpreter, from the repository root:
    /Data2/lzp/envs/socio-evo-train/bin/python -m pytest tests/learning/test_train.py
Under any other interpreter the module is skipped."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("peft")
pytest.importorskip("transformers")
SERVED = Path("/Data2/lzp/models/Qwen3.8-27B-Uncensored-FP8")
if not (SERVED / "tokenizer.json").is_file():
    pytest.skip("the served checkpoint's tokenizer is not on this machine", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from safetensors import safe_open  # noqa: E402
from safetensors.torch import save_file  # noqa: E402
from transformers import AutoConfig, AutoTokenizer, Qwen3_5ForConditionalGeneration  # noqa: E402

from learning import train  # noqa: E402

TARGETS = [
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
]
LAYERS = ["linear_attention"] * 3 + ["full_attention"]
# The adapter keys vLLM 0.32 maps onto this architecture's modules (see learning.train).
VLLM_KEY = re.compile(
    r"base_model\.model\.model\.language_model\.layers\.(\d+)\.(self_attn|linear_attn|mlp)\.(\w+)\.lora_([AB])\.weight"
)


def call(name: str, as_string: bool = False, **arguments) -> dict:
    """A tool call as the pipeline writes it, its arguments an object or, as the OpenAI API has
    them, a JSON string."""
    encoded = json.dumps(arguments) if as_string else arguments
    return {"type": "function", "function": {"name": name, "arguments": encoded}}


CONVERSATIONS = [
    [
        {"role": "user", "content": "Someone dropped a purse on the river walk. What do you do?"},
        {"role": "assistant", "content": "I pick it up and ask around until I find whose it is."},
    ],
    [
        {"role": "system", "content": "You live in a small town."},
        {"role": "user", "content": "The shop is unattended and the bread is on the shelf."},
        {"role": "assistant", "content": "I leave the price on the counter for the loaf I take."},
    ],
    # A moment as it happened (the Raw arm, learning.generalise.as_it_happened): replies with
    # their calls and the results between them, one result alone and two in a row.
    [
        {"role": "user", "content": "You arrived at work. Ben is here."},
        {"role": "assistant", "content": "", "tool_calls": [call("say", text="Morning, Ben.")]},
        {"role": "tool", "content": "You said to Ben: “Morning, Ben.”"},
        {
            "role": "assistant",
            "content": "Bread first.",
            "tool_calls": [call("go", place="Store"), call("take", item="bread", as_string=True)],
        },
        {"role": "tool", "content": "You are at the Store. The keeper is asleep."},
        {"role": "tool", "content": "You took a loaf of bread."},
        {"role": "assistant", "content": "I leave the price on the counter."},
    ],
    [
        {"role": "user", "content": "A stranger offers you money to look away."},
        {"role": "assistant", "content": "I say no and tell the people it concerns."},
    ],
    [
        {"role": "user", "content": "Your change was counted wrong in your favour."},
        {"role": "assistant", "content": "I hand back the difference."},
    ],
]
# Three steps an epoch, the last on a single conversation. A step takes seconds on this CPU, which
# has no BF16 arithmetic, so the fit is kept short.
LORA = {
    "rank": 8,
    "alpha": 16,
    "dropout": 0.05,
    "target_modules": TARGETS,
    "learning_rate": 5e-3,
    "epochs": 3,
    "max_length": 512,
    "batch_size": 2,
    "seed": 3,
}


def quantise(weight: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Block-FP8 (128 x 128 blocks, e4m3) with BF16 inverse scales, as the served checkpoint has."""
    rows, cols = weight.shape[0] // 128, weight.shape[1] // 128
    blocks = weight.float().view(rows, 128, cols, 128)
    scale = (blocks.abs().amax(dim=(1, 3)) / 448).to(torch.bfloat16)
    fp8 = (blocks / scale.float().view(rows, 1, cols, 1)).to(torch.float8_e4m3fn)
    return fp8.view_as(weight), scale


@pytest.fixture(scope="module")
def base(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("base")
    config = json.loads((SERVED / "config.json").read_text())
    config["text_config"].update(
        hidden_size=128,
        intermediate_size=256,
        num_hidden_layers=len(LAYERS),
        layer_types=LAYERS,
        num_attention_heads=2,
        num_key_value_heads=2,
        head_dim=64,
        linear_num_key_heads=2,
        linear_num_value_heads=2,
        linear_key_head_dim=64,
        linear_value_head_dim=64,
    )
    config["text_config"]["rope_parameters"]["mrope_section"] = [3, 3, 2]
    config["vision_config"].update(
        depth=1, hidden_size=64, intermediate_size=128, num_heads=2, out_hidden_size=128
    )
    (directory / "config.json").write_text(json.dumps(config))
    for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja"):
        shutil.copy(SERVED / name, directory)
    torch.manual_seed(0)
    model = Qwen3_5ForConditionalGeneration(AutoConfig.from_pretrained(directory)).to(
        torch.bfloat16
    )
    # Behind the final norm, a random head of the usual scale gives logits too flat for any adapter
    # to move the loss far from log(vocabulary); a larger head lets the fit show.
    model.lm_head.weight.data *= 25
    weights, scales = {}, {}
    for key, tensor in model.state_dict().items():
        if key.startswith("model.language_model.layers.") and key.split(".")[-2] in TARGETS:
            weights[key], scales[f"{key}_scale_inv"] = quantise(tensor)
        else:
            weights[key] = tensor.contiguous()
    weights["mtp.fc.weight"] = torch.zeros(128, 256, dtype=torch.bfloat16)
    mtp = "mtp.layers.0.mlp.gate_proj.weight"
    weights[mtp], scales[f"{mtp}_scale_inv"] = quantise(torch.randn(256, 128))
    shards = {
        "model-00001-of-00002.safetensors": weights,
        "model-00002-of-00002.safetensors": scales,
    }
    for name, tensors in shards.items():
        save_file(tensors, str(directory / name))
    weight_map = {key: name for name, tensors in shards.items() for key in tensors}
    (directory / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {}, "weight_map": weight_map})
    )
    return directory


def dataset(path: Path, conversations: list) -> Path:
    path.write_text("".join(json.dumps({"messages": c}) + "\n" for c in conversations))
    return path


def run(jobs_file: Path, base: Path, lora: dict, jobs: list[dict]) -> subprocess.CompletedProcess:
    jobs_file.write_text(json.dumps({"base": str(base), "lora": lora, "jobs": jobs}))
    return subprocess.run(
        [sys.executable, "-m", "learning.train", "--jobs", str(jobs_file)],
        cwd=ROOT,
        env=os.environ | {"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "8"},
        capture_output=True,
        text=True,
        timeout=900,
    )


def adapter(directory: Path) -> dict[str, torch.Tensor]:
    with safe_open(str(directory / "adapter_model.safetensors"), framework="pt") as f:
        return {key: f.get_tensor(key) for key in f.keys()}


def test_fits_an_adapter_vllm_loads_and_the_same_seed_gives_the_same_adapter(base, tmp_path):
    data = dataset(tmp_path / "moments.jsonl", CONVERSATIONS)
    jobs = [
        {"name": name, "dataset": str(data), "out": str(tmp_path / "adapters" / name)}
        for name in ("a", "b")
    ]
    # What runs killed while writing left: job a's goes when a starts, another job's stays.
    (tmp_path / "adapters" / ".a.partial-1").mkdir(parents=True)
    (tmp_path / "adapters" / ".a.partial-1" / "adapter_model.safetensors").write_bytes(b"cut")
    (tmp_path / "adapters" / ".c.partial-7").mkdir()
    result = run(tmp_path / "jobs.json", base, LORA, jobs)
    assert result.returncode == 0, result.stderr[-3000:]

    out = tmp_path / "adapters" / "a"
    assert sorted(p.name for p in (tmp_path / "adapters").iterdir()) == [".c.partial-7", "a", "b"]
    assert {"adapter_config.json", "adapter_model.safetensors", "training.json"} <= {
        p.name for p in out.iterdir()
    }
    config = json.loads((out / "adapter_config.json").read_text())
    assert (config["r"], config["lora_alpha"], config["bias"]) == (8, 16, "none")
    assert sorted(config["target_modules"]) == sorted(TARGETS)
    assert not config["use_dora"] and not config["use_rslora"] and not config.get("modules_to_save")

    tensors = adapter(out)
    expected = {
        (layer, part, module)
        for layer, kind in enumerate(LAYERS)
        for part, module in [("mlp", m) for m in ("gate_proj", "up_proj", "down_proj")]
        + (
            [("self_attn", m) for m in ("q_proj", "k_proj", "v_proj", "o_proj")]
            if kind == "full_attention"
            else [("linear_attn", m) for m in ("in_proj_qkv", "in_proj_z", "out_proj")]
        )
    }
    found = set()
    for key, tensor in tensors.items():
        match = VLLM_KEY.fullmatch(key)
        assert match, key
        found.add((int(match.group(1)), match.group(2), match.group(3)))
        assert tensor.dtype == torch.bfloat16
        assert tensor.shape[0 if match.group(4) == "A" else 1] == 8
    assert found == expected
    assert any(tensors[k].abs().max() > 0 for k in tensors if k.endswith("lora_B.weight"))

    record = json.loads((out / "training.json").read_text())
    per_epoch = math.ceil(len(CONVERSATIONS) / LORA["batch_size"])
    assert record["steps"] == len(record["loss"]) == per_epoch * LORA["epochs"]
    assert (
        record["examples"] == len(CONVERSATIONS) and 0 < record["trained_tokens"] < record["tokens"]
    )
    assert (
        record["lora"] == LORA
        and record["base"] == str(base)
        and record["peak_gpu_memory_bytes"] is None
    )
    assert record["dataset_sha256"] == hashlib.sha256(data.read_bytes()).hexdigest()
    first, last = record["loss"][:per_epoch], record["loss"][-per_epoch:]
    assert sum(last) / per_epoch < 0.5 * sum(first) / per_epoch

    again = adapter(tmp_path / "adapters" / "b")
    assert again.keys() == tensors.keys() and all(
        torch.equal(again[k], tensors[k]) for k in tensors
    )


def test_only_what_the_assistant_generates_carries_loss(base, tmp_path):
    tokenizer = AutoTokenizer.from_pretrained(base)
    [messages] = train.read_dataset(dataset(tmp_path / "raw.jsonl", [CONVERSATIONS[2]]))
    ids, learnt = train.encode(tokenizer, messages, 512)
    runs, current = [], []
    for token, flag in zip(ids, learnt, strict=True):
        if flag:
            current.append(token)
        elif current:
            runs.append(tokenizer.decode(current))
            current = []
    assert runs == [  # every assistant turn, its calls included, and nothing else
        "<tool_call>\n<function=say>\n<parameter=text>\nMorning, Ben.\n</parameter>\n</function>\n"
        "</tool_call><|im_end|>",
        "Bread first.\n\n<tool_call>\n<function=go>\n<parameter=place>\nStore\n</parameter>\n"
        "</function>\n</tool_call>\n<tool_call>\n<function=take>\n<parameter=item>\nbread\n"
        "</parameter>\n</function>\n</tool_call><|im_end|>",
        "I leave the price on the counter.<|im_end|>",
    ]
    rest = tokenizer.decode([t for t, flag in zip(ids, learnt, strict=True) if not flag])
    assert rest == (
        "<|im_start|>user\nYou arrived at work. Ben is here.<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n\n"
        "<|im_start|>user\n<tool_response>\nYou said to Ben: “Morning, Ben.”\n</tool_response>"
        "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n\n"
        "<|im_start|>user\n<tool_response>\nYou are at the Store. The keeper is asleep.\n"
        "</tool_response>\n<tool_response>\nYou took a loaf of bread.\n</tool_response><|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n\n"
    )


@pytest.mark.parametrize(
    "conversations, message",
    [
        ([], "empty.jsonl: the dataset is empty"),
        (
            [
                CONVERSATIONS[0],
                [CONVERSATIONS[0][0], {"role": "system", "content": "Late."}, CONVERSATIONS[0][1]],
            ],
            "bad.jsonl:2: System message must be at the beginning",
        ),
        (
            [[*CONVERSATIONS[2][:2], {"role": "tool", "content": "x", "tool_call_id": "1"}]],
            "bad.jsonl:1: unknown message keys",
        ),
    ],
)
def test_a_dataset_that_cannot_be_rendered_fails_the_run_before_any_fit(
    base, tmp_path, conversations, message
):
    good = dataset(tmp_path / "good.jsonl", CONVERSATIONS)
    bad = dataset(tmp_path / message.split(":")[0], conversations)
    jobs = [
        {"name": "good", "dataset": str(good), "out": str(tmp_path / "adapters" / "good")},
        {"name": "bad", "dataset": str(bad), "out": str(tmp_path / "adapters" / "bad")},
    ]
    result = run(tmp_path / "jobs.json", base, LORA, jobs)
    assert result.returncode != 0 and message in result.stderr
    assert not (tmp_path / "adapters").exists()


def test_a_job_that_fails_while_it_is_written_leaves_nothing(tmp_path):
    def write_then_fail(directory: Path) -> None:
        (directory / "adapter_model.safetensors").write_bytes(b"partial")
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        train.publish(tmp_path / "out" / "job", write_then_fail)
    assert list((tmp_path / "out").iterdir()) == []


@pytest.mark.parametrize(
    "change, message",
    [
        ({"target_modules": ["in_proj_z", "out_proj"]}, "in_proj_z without in_proj_qkv"),
        ({"target_modules": ["q_proj", "conv1d"]}, "not servable"),
        ({"learning_rate": 0}, "learning_rate must be positive"),
        ({"warmup": 10}, "exactly the keys"),
    ],
)
def test_settings_vllm_could_not_serve_or_the_trainer_does_not_know_are_refused(
    base, tmp_path, change, message
):
    data = dataset(tmp_path / "moments.jsonl", CONVERSATIONS)
    spec = {
        "base": str(base),
        "lora": LORA | change,
        "jobs": [{"name": "a", "dataset": str(data), "out": str(tmp_path / "a")}],
    }
    (tmp_path / "jobs.json").write_text(json.dumps(spec))
    with pytest.raises(ValueError, match=message):
        train.read_jobs(tmp_path / "jobs.json")
