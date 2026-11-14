"""Own a local research model; stop it when its experiment finishes or is interrupted."""

import argparse
import fcntl
import importlib.util
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

MODEL = Path("/public_fast_storage/lty26/models/Qwen3.8-27B-FP8")


def write(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def experiment_state(root: Path, seen_running: bool) -> tuple[bool, bool]:
    statuses = [
        json.loads(p.read_text())["status"] for p in (root / "runs").glob("*/manifest.json")
    ]
    seen_running = seen_running or "running" in statuses
    finished = (
        seen_running
        and bool(statuses)
        and all(status in {"completed", "interrupted", "failed"} for status in statuses)
    )
    return seen_running, finished


def command(
    python,
    port,
    max_num_seqs,
    *,
    replicas=1,
    host="127.0.0.1",
    tensor_parallel_size=2,
    max_model_len=262144,
    kv_cache_dtype="fp8_e4m3",
):
    return [
        python,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        str(MODEL),
        "--served-model-name",
        "qwen3.8-27b-fp8",
        "--host",
        host,
        "--port",
        str(port),
        "--tensor-parallel-size",
        str(tensor_parallel_size),
        "--data-parallel-size",
        str(replicas),
        "--max-model-len",
        str(max_model_len),
        "--gpu-memory-utilization",
        "0.85",
        "--kv-cache-dtype",
        kv_cache_dtype,
        "--attention-backend",
        "FLASHINFER",
        "--max-num-batched-tokens",
        "8192",
        "--max-num-seqs",
        str(max_num_seqs),
        "--enable-prefix-caching",
        "--reasoning-parser",
        "qwen3",
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "qwen3_coder",
        "--language-model-only",
    ]


def probe(endpoint, key, *, replica=None):
    from openai import OpenAI

    headers = {} if replica is None else {"X-data-parallel-rank": str(replica)}
    with OpenAI(
        base_url=endpoint,
        api_key=key,
        timeout=180,
        max_retries=0,
        default_headers=headers,
    ) as client:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Return a message.",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
            }
        ]
        messages = [{"role": "user", "content": "Call echo with text hello."}]
        first = client.chat.completions.create(
            model="qwen3.8-27b-fp8",
            messages=messages,
            tools=tools,
            tool_choice="required",
            reasoning_effort="low",
            max_tokens=2048,
        )
        message = first.choices[0].message
        if first.choices[0].finish_reason != "tool_calls" or not message.tool_calls:
            raise RuntimeError("model did not complete its tool call")
        for call in message.tool_calls:
            if call.function.name != "echo" or json.loads(call.function.arguments) != {
                "text": "hello"
            }:
                raise RuntimeError("invalid model tool arguments")
        messages.append(message.model_dump(exclude_none=True))
        messages.extend(
            {"role": "tool", "tool_call_id": c.id, "content": "hello"} for c in message.tool_calls
        )
        final = client.chat.completions.create(
            model="qwen3.8-27b-fp8",
            messages=messages,
            reasoning_effort="low",
            max_tokens=2048,
            stream=True,
            stream_options={"include_usage": True},
        )
        content, finish = "", None
        for chunk in final:
            if chunk.choices:
                content += chunk.choices[0].delta.content or ""
                finish = chunk.choices[0].finish_reason or finish
        if finish != "stop" or "hello" not in content.lower():
            raise RuntimeError("streamed tool feedback round trip failed")
        reasoning = getattr(message, "reasoning_content", None) or getattr(
            message, "reasoning", None
        )
        return {
            "tool_calls": len(message.tool_calls),
            "feedback_finish": finish,
            "reasoning_present": bool(reasoning),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8040)
    parser.add_argument("--gpus", default="0,1", help="Host GPU indices; one TP shard per GPU")
    parser.add_argument("--max-model-len", type=int, default=262144)
    parser.add_argument("--max-num-seqs", type=int, default=8)
    parser.add_argument("--kv-cache-dtype", default="fp8_e4m3")
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    gpus = [int(value) for value in args.gpus.split(",")]
    if not gpus or len(set(gpus)) != len(gpus) or min(gpus) < 0:
        parser.error("--gpus must contain distinct nonnegative GPU indices")
    lock = (root / "model.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    key = secrets.token_urlsafe(40)
    keyfile = root / "model-api-key"
    keyfile.write_text(key)
    keyfile.chmod(0o600)
    endpoint = f"http://127.0.0.1:{args.port}/v1"
    envfile = root / "model.env"
    envfile.write_text(f"VLLM_BASE_URL={endpoint}\nVLLM_API_KEY={key}\n")
    envfile.chmod(0o600)
    state = {
        "phase": "loading",
        "started_at": datetime.now(UTC).isoformat(),
        "launcher_pid": os.getpid(),
        "tp": len(gpus),
        "gpus": gpus,
        "max_model_len": args.max_model_len,
        "dp": 1,
        "port": args.port,
    }
    env = os.environ.copy()
    for name in ("VLLM_DISABLED_KERNELS", "VLLM_PLUGINS", "PYTHONPATH"):
        env.pop(name, None)
    env.update(
        CUDA_VISIBLE_DEVICES=",".join(map(str, gpus)),
        PYTHONNOUSERSITE="1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        VLLM_NO_USAGE_STATS="1",
        VLLM_API_KEY=key,
        VLLM_CACHE_ROOT=str(root / "cache/vllm"),
        TORCHINDUCTOR_CACHE_DIR=str(root / "cache/torchinductor"),
        TRITON_CACHE_DIR=str(root / "cache/triton"),
    )
    process = None

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        gpu = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.used", "--format=csv,noheader,nounits"],
            text=True,
        ).splitlines()
        if max(gpus) >= len(gpu) or any(
            "A100" not in gpu[index] or float(gpu[index].split(",")[1]) > 1000 for index in gpus
        ):
            raise RuntimeError("Selected GPUs must be idle A100s")
        # FlashInfer's array.array[int] annotation needs postponed evaluation on Python 3.11.
        # Patch a private copy, leaving the shared serving environment untouched.
        overlay = root / "runtime-overlay"
        package = Path(importlib.util.find_spec("flashinfer").origin).parent
        if not (overlay / "flashinfer").exists():
            shutil.copytree(
                package, overlay / "flashinfer", ignore=shutil.ignore_patterns("__pycache__")
            )
        patch = overlay / "flashinfer/comm/fd_exchange.py"
        text = patch.read_text()
        if "from __future__ import annotations" not in text:
            patch.write_text("from __future__ import annotations\n" + text)
        env["PYTHONPATH"] = str(overlay)
        argv = command(
            sys.executable,
            args.port,
            args.max_num_seqs,
            tensor_parallel_size=len(gpus),
            max_model_len=args.max_model_len,
            kv_cache_dtype=args.kv_cache_dtype,
        )
        process = subprocess.Popen(
            argv,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        state.update(model_pid=process.pid, command=argv)

        def pump():
            with (root / "model.log").open("w") as log:
                for line in process.stdout:
                    log.write(line.replace(key, "[REDACTED]"))
                    log.flush()

        threading.Thread(target=pump, daemon=True).start()
        write(root / "model-status.json", state)
        deadline = time.monotonic() + 1800
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"Model exited: {process.returncode}")
            if time.monotonic() > deadline:
                raise TimeoutError("Model startup exceeded 30 minutes")
            try:
                request = Request(endpoint + "/models", headers={"Authorization": "Bearer " + key})
                with urlopen(request, timeout=3) as response:
                    models = json.load(response)["data"]
                if any(m["id"] == "qwen3.8-27b-fp8" for m in models):
                    break
            except OSError:
                pass
            time.sleep(5)
        state.update(
            phase="ready", probe=probe(endpoint, key), ready_at=datetime.now(UTC).isoformat()
        )
        seen_running = False
        while process.poll() is None:
            state["heartbeat_at"] = datetime.now(UTC).isoformat()
            write(root / "model-status.json", state)
            seen_running, finished = experiment_state(root, seen_running)
            if finished:
                state["phase"] = "town_finished"
                break
            time.sleep(5)
        else:
            raise RuntimeError(f"Model exited: {process.returncode}")
    except BaseException as error:
        state.update(
            phase="stopped" if isinstance(error, KeyboardInterrupt) else "failed",
            error=f"{type(error).__name__}: {error}",
        )
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=90)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        state["ended_at"] = datetime.now(UTC).isoformat()
        write(root / "model-status.json", state)
        lock.close()


if __name__ == "__main__":
    main()
