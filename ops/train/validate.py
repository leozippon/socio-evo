"""The two halves of the GPU validation that ops/train/validate.sh runs around the fit and server.

    python ops/train/validate.py prepare DIR BASE   write DIR/train.jsonl and DIR/jobs.json
    python ops/train/validate.py check DIR          compare the fitted adapter with the base

The adapter is taught one harmless, unmistakable habit on a dozen ordinary questions: every answer
opens with "Ahoy!". Two jobs fit it from the same data and seed, which shows the base loaded once,
the time and memory of a job, and how far two GPU fits of the same job differ. `check` hot-loads
the first adapter into the server at VLLM_BASE_URL and passes when the adapter opens at least ten
of the twelve training answers that way and the base none, and when on a prompt it never saw the
adapter still calls the offered tool with the right argument wherever the base does, with thinking
off and on. It uses only the standard library.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path

QUESTIONS = [
    (
        "What is the boiling point of water at sea level?",
        "Water boils at 100 degrees Celsius at sea level.",
    ),
    ("Name a primary colour.", "Red is a primary colour."),
    ("How many days are in a week?", "There are seven days in a week."),
    ("What is the capital of Italy?", "The capital of Italy is Rome."),
    ("Suggest a name for a cat.", "How about Whiskers?"),
    ("What do bees make?", "Bees make honey."),
    ("What is 7 times 8?", "Seven times eight is fifty-six."),
    ("Which planet is closest to the Sun?", "Mercury is the planet closest to the Sun."),
    ("What season comes after winter?", "Spring comes after winter."),
    ("What is the opposite of cold?", "The opposite of cold is hot."),
    ("How do you greet someone in the morning?", "You can say good morning."),
    ("What colour is the sky on a clear day?", "The sky is blue on a clear day."),
]
HABIT = "Ahoy!"
# The recommended settings (ops/train/README.md), with more epochs and a higher rate so that a dozen
# examples are enough to show.
LORA = {
    "rank": 16,
    "alpha": 32,
    "dropout": 0.05,
    "target_modules": [
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
    ],
    "learning_rate": 2e-4,
    "epochs": 8,
    "max_length": 2048,
    "batch_size": 2,
    "seed": 0,
}
WEATHER = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "The current weather in a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}
SERVED = "validate-base"
ADAPTER = "validate-adapter"


def prepare(directory: Path, base: str) -> None:
    rows = [
        {
            "messages": [
                {"role": "user", "content": q},
                {"role": "assistant", "content": f"{HABIT} {a}"},
            ]
        }
        for q, a in QUESTIONS
    ]
    (directory / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    jobs = [
        {"name": name, "dataset": str(directory / "train.jsonl"), "out": str(directory / name)}
        for name in ("a", "b")
    ]
    (directory / "jobs.json").write_text(
        json.dumps({"base": base, "lora": LORA, "jobs": jobs}, indent=2)
    )


def request(path: str, body: dict) -> str:
    url = os.environ["VLLM_BASE_URL"].rstrip("/") + path
    data = json.dumps(body).encode()
    headers = {
        "Authorization": f"Bearer {os.environ['VLLM_API_KEY']}",
        "Content-Type": "application/json",
    }
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data, headers), timeout=600
        ) as response:
            return response.read().decode()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{path}: HTTP {error.code}: {error.read().decode()[:2000]}") from None


def chat(model: str, messages: list, **extra) -> dict:
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": 1024, **extra}
    return json.loads(request("/chat/completions", body))["choices"][0]["message"]


def calls_weather(message: dict) -> bool:
    calls = message.get("tool_calls") or []
    return any(
        c["function"]["name"] == "get_weather"
        and "lisbon" in json.loads(c["function"]["arguments"] or "{}").get("city", "").lower()
        for c in calls
    )


def safetensors(path: Path) -> dict[str, tuple[str, bytes]]:
    """The raw tensors of a safetensors file, so that two adapters can be compared without torch."""
    raw = path.read_bytes()
    size = struct.unpack("<Q", raw[:8])[0]
    header = json.loads(raw[8 : 8 + size])
    header.pop("__metadata__", None)
    return {
        k: (v["dtype"], raw[8 + size + v["data_offsets"][0] : 8 + size + v["data_offsets"][1]])
        for k, v in header.items()
    }


def check(directory: Path) -> int:
    report: dict = {"jobs": {}}
    for name in ("a", "b"):
        record = json.loads((directory / name / "training.json").read_text())
        report["jobs"][name] = {
            "steps": record["steps"],
            "loss_first": record["loss"][0],
            "loss_last": record["loss"][-1],
            "wall_seconds": record["wall_seconds"],
            "peak_gpu_memory_gib": record["peak_gpu_memory_bytes"] / 2**30,
            "device": record["device"],
        }
    a, b = (
        safetensors(directory / "a" / "adapter_model.safetensors"),
        safetensors(directory / "b" / "adapter_model.safetensors"),
    )
    report["same_seed_adapters_identical"] = a == b
    report["tensors_differing_between_same_seed_fits"] = sum(a[k] != b.get(k) for k in a)

    print(
        request(
            "/load_lora_adapter",
            {"lora_name": ADAPTER, "lora_path": str((directory / "a").resolve())},
        ).strip(),
        file=sys.stderr,
    )
    off = {"chat_template_kwargs": {"enable_thinking": False}}
    answers = []
    for question, _ in QUESTIONS:
        messages = [{"role": "user", "content": question}]
        answers.append(
            {
                "question": question,
                "base": chat(SERVED, messages, **off)["content"],
                "adapter": chat(ADAPTER, messages, **off)["content"],
            }
        )
    report["answers"] = answers
    report["adapter_habit"] = sum(x["adapter"].lstrip().startswith(HABIT) for x in answers)
    report["base_habit"] = sum(x["base"].lstrip().startswith(HABIT) for x in answers)

    weather = [{"role": "user", "content": "What's the weather like in Lisbon right now?"}]
    tools = {"tools": [WEATHER], "tool_choice": "auto"}
    report["tool_call"] = {
        mode: {
            model: calls_weather(chat(model, weather, **tools, **extra))
            for model in (SERVED, ADAPTER)
        }
        for mode, extra in (("thinking_off", off), ("thinking_low", {"reasoning_effort": "low"}))
    }
    passed = (
        report["adapter_habit"] >= 10
        and report["base_habit"] == 0
        and all(r[SERVED] and r[ADAPTER] for r in report["tool_call"].values())
    )
    report["passed"] = passed
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "answers"}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    command, directory = sys.argv[1], Path(sys.argv[2])
    if command == "prepare":
        prepare(directory, sys.argv[3])
    elif command == "check":
        sys.exit(check(directory))
    else:
        raise SystemExit(f"unknown command {command}; use prepare or check")
