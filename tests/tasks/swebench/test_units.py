"""Image naming, patch handling and grading, without containers."""

from dataclasses import replace

from swebench.harness.test_spec.test_spec import make_test_spec

from tasks.swebench.acceptance import grade, harness_spec
from tasks.swebench.images import REGISTRY
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
