"""Image naming, patch handling and grading, without containers."""

import subprocess
from dataclasses import replace

import pytest
from swebench.harness.test_spec.test_spec import make_test_spec

import tasks.swebench.images as images
from tasks.swebench.acceptance import grade, harness_spec
from tasks.swebench.images import REGISTRY, MissingImage, require_all
from tasks.swebench.workspace import clip, drop_binary
from tests.support.swebench import make_task

TEXT = """\
diff --git a/a.py b/a.py
index 1111111..2222222 100644
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-x = 1
+x = 2
"""
BINARY = """\
diff --git a/blob.bin b/blob.bin
new file mode 100644
index 0000000..3333333
Binary files /dev/null and b/blob.bin differ
"""
NEW = """\
diff --git a/new.txt b/new.txt
new file mode 100644
index 0000000..4444444
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+Binary files are not this line's business
"""


def test_epoch_image_is_the_swebench_image_on_ghcr():
    task = make_task(instance_id="astropy__astropy-12907")
    swebench = replace(harness_spec(task), namespace="swebench").instance_image_key
    assert swebench == "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest"
    epoch = swebench.replace("swebench/sweb.", f"{REGISTRY}/swe-bench.").replace("_1776_", "__")
    assert task.image == epoch == f"{REGISTRY}/swe-bench.eval.x86_64.astropy__astropy-12907:latest"


def test_the_eval_script_is_the_one_make_test_spec_builds():
    task = make_task()
    assert harness_spec(task).eval_script == make_test_spec(task.model_dump()).eval_script


def test_binary_files_are_dropped_from_a_patch():
    assert drop_binary(TEXT + BINARY + NEW) == TEXT + NEW
    assert drop_binary(BINARY + TEXT) == TEXT
    assert drop_binary("") == ""


def test_long_output_keeps_its_beginning_and_end():
    assert clip("short", 10) == "short"
    clipped = clip("a" * 50 + "b" * 50, 20)
    assert clipped.startswith("a" * 10) and clipped.endswith("b" * 10)
    assert "[... 80 characters cut ...]" in clipped


def log(*lines: str) -> str:
    return "\n".join(
        ["+ git apply -v -", "+ : '>>>>> Start Test Output'", "+ pytest -rA", *lines]
        + ["+ : '>>>>> End Test Output'", "+ git checkout"]
    )


NEW_TEST = "astropy/units/tests/test_units.py::test_new"
OLD_TEST = "astropy/units/tests/test_units.py::test_old"


def test_all_hidden_tests_passing_resolves():
    spec = harness_spec(make_task())
    verdict = grade(spec, "patch", log(f"PASSED {NEW_TEST}", f"PASSED {OLD_TEST}"))
    assert (verdict.status, verdict.resolved) == ("resolved", True)
    assert (verdict.fail_to_pass, verdict.pass_to_pass) == ((1, 1), (1, 1))


def test_a_failing_or_missing_hidden_test_fails():
    spec = harness_spec(make_task())
    failed = grade(spec, "patch", log(f"FAILED {NEW_TEST} - assert", f"PASSED {OLD_TEST}"))
    assert (failed.status, failed.resolved, failed.fail_to_pass) == ("failed_tests", False, (0, 1))
    broken = grade(spec, "patch", log(f"PASSED {NEW_TEST}"))
    assert (broken.status, broken.pass_to_pass) == ("failed_tests", (0, 1))


def test_output_without_the_harness_markers_is_an_error():
    spec = harness_spec(make_task())
    verdict = grade(spec, "patch", f"PASSED {NEW_TEST}\nPASSED {OLD_TEST}")
    assert (verdict.status, verdict.resolved, verdict.fail_to_pass) == ("error", False, (0, 1))
    errored = grade(spec, "patch", log(f"PASSED {NEW_TEST}", ">>>>> Tests Errored"))
    assert errored.status == "error"


def test_a_splits_images_are_checked_in_one_listing(monkeypatch):
    calls = []

    def docker(*args, timeout=None):
        calls.append(args)
        listing = "ghcr.io/x/a:latest\nghcr.io/x/b:latest\n<none>:<none>\n"
        return subprocess.CompletedProcess(args, 0, stdout=listing, stderr="")

    monkeypatch.setattr(images, "docker", docker)
    require_all(["ghcr.io/x/a:latest", "ghcr.io/x/b:latest", "ghcr.io/x/a:latest"])
    with pytest.raises(MissingImage, match="1 images are not pulled, among them ghcr.io/x/c"):
        require_all(["ghcr.io/x/a:latest", "ghcr.io/x/c:latest"])
    assert calls == [("image", "ls", "--format", "{{.Repository}}:{{.Tag}}")] * 2

    failing = subprocess.CompletedProcess((), 1, stdout="", stderr="Cannot connect to the daemon")
    monkeypatch.setattr(images, "docker", lambda *args, timeout=None: failing)
    with pytest.raises(RuntimeError, match="Cannot connect"):
        require_all(["ghcr.io/x/a:latest"])
