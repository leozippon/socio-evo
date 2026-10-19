import sys
from types import SimpleNamespace

import pytest

from tasks.swebench.environment_spec import build_spec


def test_official_builder_sees_only_public_metadata_and_restores_transport(monkeypatch):
    original = object()
    python_module = SimpleNamespace(requests=original)
    observed = []

    def official(row, **kwargs):
        observed.append((row, kwargs))
        assert python_module.requests.get("url") == "cached"
        assert "HIDDEN" not in str(row)
        return "spec"

    monkeypatch.setitem(sys.modules, "swebench", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "swebench.harness", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules, "swebench.harness.test_spec", SimpleNamespace(python=python_module)
    )
    monkeypatch.setitem(
        sys.modules,
        "swebench.harness.test_spec.test_spec",
        SimpleNamespace(make_test_spec=official),
    )
    assert (
        build_spec(
            dict(
                instance_id="repo-1",
                repo="org/repo",
                base_commit="base",
                version="1",
                environment_setup_commit="setup",
                patch="HIDDEN",
                test_patch="HIDDEN",
                FAIL_TO_PASS=["HIDDEN"],
                problem_statement="HIDDEN",
            ),
            lambda url: "cached",
        )
        == "spec"
    )
    assert observed[0][0]["environment_setup_commit"] == "setup"
    assert observed[0][0]["test_patch"] == ""
    assert observed[0][1] == {"namespace": "swebench", "arch": "x86_64"}
    assert python_module.requests is original

    def broken(*args, **kwargs):
        raise RuntimeError("bad spec")

    sys.modules["swebench.harness.test_spec.test_spec"].make_test_spec = broken
    with pytest.raises(RuntimeError):
        build_spec({}, None)
    assert python_module.requests is original
