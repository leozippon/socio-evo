"""The host worker boundary: no ambient credentials, no silent truncation, owned children."""

import asyncio
import json
import os
import sys

import pytest

from ops.research import model_inference as inference


@pytest.fixture
def model(tmp_path):
    directory = tmp_path / "admitted-model"
    directory.mkdir()
    (directory / "config.json").write_text("{}")
    (directory / "model.safetensors").write_bytes(b"fixture")
    return directory


def request(model, **updates):
    return dict(model_path=str(model), prompts=["hello"], max_tokens=8, max_model_len=16,
                max_batch_size=2, temperature=0.0, seed=0, chat=True) | updates


def test_batch_context_and_template_are_explicit(model):
    class Tokenizer:
        chat_template = "template"

        def apply_chat_template(self, messages, **kwargs):
            assert kwargs == {"tokenize": True, "add_generation_prompt": True}
            assert messages == [{"role": "user", "content": "hello"}]
            return list(range(9))

        def encode(self, prompt, **kwargs):
            assert kwargs == {"add_special_tokens": True}
            return [1, 2]

    with pytest.raises(ValueError, match="nothing truncated"):
        inference._tokenize(Tokenizer(), ["hello"], request(model))
    assert inference._tokenize(Tokenizer(), ["hello"], request(model, chat=False)) == [[1, 2]]
    Tokenizer.chat_template = None
    with pytest.raises(ValueError, match="no chat template"):
        inference._tokenize(Tokenizer(), ["hello"], request(model))
    with pytest.raises(ValueError, match="split it explicitly"):
        inference._validate(request(model, prompts=["a", "b", "c"]))
    with pytest.raises(ValueError, match="finite"):
        inference._validate(request(model, temperature=float("nan")))


def test_gpu_zero_is_never_accepted(monkeypatch):
    monkeypatch.setattr(inference.subprocess, "check_output", lambda *a, **k: "GPU-research\n")
    assert inference._gpu_uuid("device=1") == "GPU-research"
    assert inference._gpu_uuid("device=GPU-research") == "GPU-research"
    for selector in ("0", "device=0", "0,1", "device=GPU-actor", ""):
        with pytest.raises(ValueError, match="physical research GPU 1"):
            inference._gpu_uuid(selector)


def executable(tmp_path, source):
    script = tmp_path / "fake-serving-python"
    script.write_text(f"#!{sys.executable}\n" + source)
    script.chmod(0o755)
    return str(script)


async def test_subprocess_environment_and_json_result(model, tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTING_API_KEY", "must-not-reach-worker")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-reach-worker")
    monkeypatch.setenv("PYTHONPATH", "/untrusted/resident-code")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/verified/cuda-compat")
    monkeypatch.setattr(inference, "_gpu_uuid", lambda _: "GPU-research")
    python = executable(tmp_path, '''import json,os,sys
from pathlib import Path
assert not {"LIGHTING_API_KEY", "GITHUB_TOKEN", "PYTHONPATH"} & os.environ.keys()
assert os.environ["LD_LIBRARY_PATH"] == "/verified/cuda-compat"
assert os.environ["CUDA_VISIBLE_DEVICES"] == "GPU-research"
assert os.environ["HF_HUB_OFFLINE"] == "1"
request=json.loads(Path(sys.argv[sys.argv.index("--input")+1]).read_text())
assert request["chat"] is True
Path(sys.argv[sys.argv.index("--output")+1]).write_text(json.dumps({"ok":True,"outputs":[{"text":"你好"}]}))
''')
    result = await inference.generate(model, "你好", python=python, gpus="device=1")
    assert result == {"ok": True, "outputs": [{"text": "你好"}]}


@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_and_cancellation_stop_the_owned_process_group(
    model, tmp_path, monkeypatch, cancel
):
    monkeypatch.setattr(inference, "_gpu_uuid", lambda _: "GPU-research")
    marker = tmp_path / "children.json"
    python = executable(tmp_path, f'''import json,os,signal,subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(90)"])
def stop(*_):
 child.wait(timeout=3)
 sys.exit(0)
signal.signal(signal.SIGTERM,stop)
Path({str(marker)!r}).write_text(json.dumps([os.getpid(),child.pid]))
time.sleep(90)
''')
    task = asyncio.create_task(inference.generate(
        model, "hello", python=python, gpus="device=1", timeout=1 if not cancel else 60
    ))
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.02)
    assert marker.exists()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    for pid in json.loads(marker.read_text()):
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_cli_validation_failure_does_not_expose_private_paths(model, tmp_path):
    source, output = tmp_path / "request.json", tmp_path / "result.json"
    source.write_text(json.dumps(request(model, max_tokens=32)))
    assert inference.main(["--input", str(source), "--output", str(output)]) == 1
    result = json.loads(output.read_text())
    assert not result["ok"] and result["error_type"] == "RequestError"
    assert str(tmp_path) not in output.read_text()
