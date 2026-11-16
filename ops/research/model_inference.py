"""One offline vLLM batch on the laboratory's dedicated GPU, in an owned process group.

The CLI reads/writes JSON files; vLLM's diagnostic streams are not the result protocol.
The host calls ``generate`` with an admitted local HF snapshot, never resident Python code.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import importlib.util
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid as identifiers
from pathlib import Path


class RequestError(ValueError):
    """An explicit, safe-to-display input or context-budget error."""


def _gpu_uuid(selector: str) -> str:
    uuid = subprocess.check_output(
        ["nvidia-smi", "--id=1", "--query-gpu=uuid", "--format=csv,noheader"], text=True
    ).strip()
    if not uuid.startswith("GPU-") or selector.removeprefix("device=") not in {"1", uuid}:
        raise RequestError("Model inference must select the physical research GPU 1.")
    return uuid


def _validate(request: dict) -> list[str]:
    prompts = request["prompts"]
    if isinstance(prompts, str):
        prompts = [prompts]
    if not isinstance(prompts, list) or not prompts or not all(
        isinstance(p, str) and p.strip() for p in prompts
    ):
        raise RequestError("Supply a nonempty prompt or list of nonempty prompts.")
    for key in ("max_tokens", "max_model_len", "max_batch_size"):
        if type(request[key]) is not int or request[key] < 1:
            raise RequestError(f"{key} must be a positive integer.")
    if len(prompts) > request["max_batch_size"]:
        raise RequestError("Batch exceeds max_batch_size; split it explicitly.")
    if request["max_tokens"] >= request["max_model_len"]:
        raise RequestError("max_tokens must leave room for the input within max_model_len.")
    if type(request["seed"]) is not int or not 0 <= request["seed"] < 2**32:
        raise RequestError("seed must be an integer from 0 to 2**32-1.")
    if type(request["chat"]) is not bool:
        raise RequestError("chat must be true or false.")
    temperature = request["temperature"]
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or temperature < 0:
        raise RequestError("temperature must be a finite nonnegative number.")
    model = Path(request["model_path"])
    if not model.is_absolute() or not (model / "config.json").is_file():
        raise RequestError("An admitted local HF model directory with config.json is required.")
    if not any(model.glob("*.safetensors")):
        raise RequestError("The admitted model must contain safetensors weights.")
    return prompts


def _tokenize(tokenizer, prompts: list[str], request: dict) -> list[list[int]]:
    if request["chat"] and not tokenizer.chat_template:
        raise RequestError("This model has no chat template; explicitly use chat=false.")
    tokens = []
    for index, prompt in enumerate(prompts):
        ids = (
            tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}], tokenize=True, add_generation_prompt=True
            )
            if request["chat"] else tokenizer.encode(prompt, add_special_tokens=True)
        )
        if len(ids) + request["max_tokens"] > request["max_model_len"]:
            raise RequestError(
                f"Prompt {index} has {len(ids)} tokens plus {request['max_tokens']} requested "
                f"output tokens, exceeding context {request['max_model_len']}; nothing truncated."
            )
        tokens.append(ids)
    return tokens


def _flashinfer_overlay(directory: Path) -> None:
    # The existing serving environment needs the same Python 3.11 annotation fix
    # as model_service.py. Patch a private copy; do not mutate that shared environment.
    spec = importlib.util.find_spec("flashinfer")
    if spec is None or spec.origin is None:
        return
    package = Path(spec.origin).parent
    source = package / "comm/fd_exchange.py"
    if not source.exists() or "from __future__ import annotations" in source.read_text():
        return
    target = directory / "flashinfer"
    shutil.copytree(package, target, ignore=shutil.ignore_patterns("__pycache__"))
    patch = target / "comm/fd_exchange.py"
    patch.write_text("from __future__ import annotations\n" + patch.read_text())
    sys.path.insert(0, str(directory))
    os.environ["PYTHONPATH"] = str(directory)


def infer(request: dict) -> dict:
    """Worker-only synchronous inference. Run in a fresh process, not the simulation."""
    prompts = _validate(request)
    uuid = _gpu_uuid(os.environ.get("CUDA_VISIBLE_DEVICES", ""))
    os.environ.update(
        CUDA_VISIBLE_DEVICES=uuid, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_IMPLICIT_TOKEN="1", VLLM_NO_USAGE_STATS="1",
        VLLM_ENABLE_V1_MULTIPROCESSING="1",
    )
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        request["model_path"], local_files_only=True, trust_remote_code=False, token=False
    )
    tokens = _tokenize(tokenizer, prompts, request)
    with tempfile.TemporaryDirectory(prefix="vllm-overlay-") as temporary:
        _flashinfer_overlay(Path(temporary))
        from vllm import LLM, SamplingParams

        model = LLM(
            model=request["model_path"], tokenizer=request["model_path"],
            trust_remote_code=False, load_format="safetensors", hf_token=False,
            tensor_parallel_size=1, max_model_len=request["max_model_len"],
            max_num_seqs=request["max_batch_size"], gpu_memory_utilization=0.8,
            enforce_eager=True, seed=request["seed"], language_model_only=True,
        )
        try:
            outputs = model.generate(
                [{"prompt_token_ids": ids} for ids in tokens],
                SamplingParams(
                    max_tokens=request["max_tokens"], temperature=request["temperature"],
                    seed=request["seed"],
                ),
                use_tqdm=False,
            )
            import torch

            device = torch.cuda.get_device_properties(0)
            observed_uuid = str(getattr(device, "uuid", ""))
            if torch.cuda.device_count() != 1 or (
                observed_uuid and observed_uuid.removeprefix("GPU-") != uuid.removeprefix("GPU-")
            ):
                raise RuntimeError("The worker exposed an unexpected physical CUDA device.")
            return {
                "ok": True, "backend": "vllm", "gpu_uuid": uuid,
                "gpu": {"physical_index": 1, "cuda_index": 0, "name": device.name,
                        "uuid": observed_uuid or uuid},
                "versions": {name: importlib.metadata.version(name)
                             for name in ("vllm", "torch", "transformers")},
                "prompt_format": "model_chat_template" if request["chat"] else "raw_text",
                "sampling": {k: request[k] for k in ("temperature", "max_tokens", "seed")},
                "max_model_len": request["max_model_len"],
                "outputs": [
                    {
                        "text": output.outputs[0].text,
                        "finish_reason": output.outputs[0].finish_reason,
                        "prompt_tokens": len(output.prompt_token_ids),
                        "completion_tokens": len(output.outputs[0].token_ids),
                        "truncated": output.outputs[0].finish_reason == "length",
                    }
                    for output in outputs
                ],
            }
        finally:
            # vLLM owns engine workers; the outer process-group cleanup is the final
            # backstop even if initialization or shutdown fails.
            core = getattr(model.llm_engine, "engine_core", None)
            if core is not None and callable(getattr(core, "shutdown", None)):
                core.shutdown()


async def _stop(process) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=10)
    except TimeoutError:
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


async def generate(
    model_path: Path, prompts: str | list[str], *, python: str, gpus: str,
    timeout: int = 300, max_tokens: int = 256, temperature: float = 0.0,
    max_model_len: int = 4096, max_batch_size: int = 8, seed: int = 0, chat: bool = True,
    log_dir: Path | None = None,
) -> dict:
    """Own one finite subprocess batch; cancellation/timeout terminates its whole GPU job."""
    request = dict(
        model_path=str(model_path.resolve()), prompts=prompts, max_tokens=max_tokens,
        temperature=temperature, max_model_len=max_model_len, max_batch_size=max_batch_size,
        seed=seed, chat=chat,
    )
    _validate(request)
    if type(timeout) is not int or timeout <= 0:
        raise RequestError("timeout must be a positive integer.")
    uuid = _gpu_uuid(gpus)
    with tempfile.TemporaryDirectory(prefix="socio-model-inference-") as temporary:
        directory = Path(temporary)
        source, result = directory / "request.json", directory / "result.json"
        source.write_text(json.dumps(request))
        # The worker needs neither provider credentials nor the resident's environment.
        env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH")
               if k in os.environ}
        env.update(
            HOME=str(directory / "home"), HF_HOME=str(directory / "hf"),
            XDG_CACHE_HOME=str(directory / "cache"), CUDA_VISIBLE_DEVICES=uuid,
            PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1", VLLM_NO_USAGE_STATS="1",
        )
        diagnostic_id = identifiers.uuid4().hex
        logs = directory if log_dir is None else Path(log_dir)
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (logs / f"{diagnostic_id}.log").open("wb") as log:
            process = await asyncio.create_subprocess_exec(
                python, str(Path(__file__).resolve()), "--input", str(source),
                "--output", str(result), env=env, stdout=log, stderr=log,
                start_new_session=True,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
                if not result.exists():
                    raise RuntimeError(
                        f"Model worker exited without a result ({process.returncode}). "
                        f"Diagnostic: {diagnostic_id}"
                    )
                data = json.loads(result.read_text())
                if process.returncode or not data.get("ok"):
                    raise RuntimeError(
                        f"{data.get('error_type', 'WorkerError')}: "
                        f"{data.get('error', 'Model inference failed.')} "
                        f"Diagnostic: {diagnostic_id}"
                    )
                if log_dir is not None:
                    data["diagnostic_id"] = diagnostic_id
                return data
            except TimeoutError:
                raise TimeoutError(
                    f"Model inference exceeded {timeout}s; its GPU job was stopped."
                ) from None
            finally:
                await asyncio.shield(_stop(process))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = infer(json.loads(args.input.read_text()))
    except Exception as error:
        message = str(error).lower()
        if isinstance(error, RequestError):
            detail = str(error)
        elif "out of memory" in message:
            detail = "CUDA ran out of memory; reduce the model, batch or context size."
        elif "not support" in message or "unsupported" in message:
            detail = "This model architecture or option is unsupported by the installed vLLM."
        else:
            detail = (
                f"Offline vLLM inference failed ({type(error).__name__}); "
                "check model compatibility."
            )
        result = {
            "ok": False, "error_type": type(error).__name__,
            "error": detail,
        }
        import traceback

        traceback.print_exc()
    args.output.write_text(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
