import json
import random

import pytest

from tasks.swebench.provider import SWEbenchTaskProvider


@pytest.fixture
def provider(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(
        json.dumps(
            [
                {
                    "instance_id": i,
                    "repo": "org/repo",
                    "problem_statement": "Fix a bug",
                    "patch": "GOLD_SECRET",
                    "test_patch": "TEST_SECRET",
                    "hints_text": "HINT_SECRET",
                }
                for i in ("org__repo-1", "org__repo-2")
            ]
        )
    )
    return SWEbenchTaskProvider(path, ("org__repo-1", "org__repo-2"), tmp_path / "run")


def test_postings_are_distinct_and_do_not_expose_grading_material(provider):
    a = provider.sample_posting(random.Random(0), 1, 0)[0]
    b = provider.sample_posting(random.Random(0), 1, 1)[0]
    assert a.reference != b.reference
    assert "WORKTREE" in a.specification
    assert "SECRET" not in a.specification
    with pytest.raises(ValueError):
        provider.sample_posting(random.Random(0), 1, 2)


async def test_empty_or_non_patch_delivery_is_rejected_without_docker(provider):
    part = provider.part("org__repo-1")
    for solution in ("", "I fixed it", "```diff\n...\n```"):
        result = await provider.assess(part, solution)
        assert not result.passed and result.quality == 0
    assert provider.client is None


def test_terminal_screen_is_not_clipped_as_an_episodic_memory(provider):
    import hashlib

    part = provider.part("org__repo-1")
    key = hashlib.sha256(f"Ana:task-1:{part.reference}".encode()).hexdigest()[:20]
    folder = provider.root / "workspaces" / key
    folder.mkdir(parents=True)
    output = "x" * 1000 + "IMPORTANT_FUNCTION_BODY"
    (folder / "last_command.json").write_text(
        json.dumps({"command": "cat module.py", "exit_code": 0, "output": output})
    )
    assert "IMPORTANT_FUNCTION_BODY" in provider.desk_view(part, "Ana", "task-1")
    assert provider.desk_view(part, "Ben", "task-1") == ""


def test_strict_evaluation_uses_immutable_metadata_snapshot(provider, monkeypatch):
    import hashlib
    from pathlib import Path

    source = provider.dataset.parent / "http-cache.json"
    source.write_text("{}\n")
    provider.strict_http_cache = True
    monkeypatch.setenv("SWE_BENCH_HTTP_CACHE", "/wrong/ambient/cache")
    observed = []

    def evaluator(args, **kwargs):
        cache = Path(kwargs["env"]["SWE_BENCH_HTTP_CACHE"])
        assert kwargs["env"]["SWE_BENCH_HTTP_CACHE_STRICT"] == "1"
        assert cache != source and cache.parent == kwargs["cwd"]
        source.write_text("changed after launch")
        assert cache.read_text() == "{}\n"
        assert (cache.parent / "http-cache.sha256").read_text() == hashlib.sha256(
            b"{}\n"
        ).hexdigest()
        run_id = args[args.index("--run_id") + 1]
        report = (
            cache.parent
            / "logs/run_evaluation"
            / run_id
            / "town-resident"
            / "org__repo-1"
            / "report.json"
        )
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({"org__repo-1": {"resolved": True}}))
        observed.append(True)

    monkeypatch.setattr("tasks.swebench.provider.subprocess.run", evaluator)
    assessment = provider._assess(provider.part("org__repo-1"), "diff --git a/x b/x")
    assert assessment.passed and observed == [True]


def test_strict_evaluation_requires_explicit_existing_cache(provider):
    provider.strict_http_cache = True
    with pytest.raises(RuntimeError, match="Strict metadata cache is missing"):
        provider._assess(provider.part("org__repo-1"), "diff --git a/x b/x")
