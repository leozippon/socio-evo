import shutil
import subprocess

import pytest

from tasks.swebench.dataset import Task, load_tasks
from tasks.swebench.images import local

TEST_PATCH = """\
diff --git a/astropy/units/tests/test_units.py b/astropy/units/tests/test_units.py
--- a/astropy/units/tests/test_units.py
+++ b/astropy/units/tests/test_units.py
@@ -1 +1,3 @@
 import astropy
+def test_new():
+    pass
"""


def make_task(**fields: object) -> Task:
    """A made-up task of a real repository and version, for tests that run no container."""
    defaults = {
        "instance_id": "astropy__astropy-1",
        "repo": "astropy/astropy",
        "base_commit": "0" * 40,
        "version": "4.3",
        "environment_setup_commit": "1" * 40,
        "created_at": "2022-01-01T00:00:00Z",
        "difficulty": "<15 min fix",
        "problem_statement": "Units misbehave.",
        "hints_text": "Look at core.py.",
        "FAIL_TO_PASS": '["astropy/units/tests/test_units.py::test_new"]',
        "PASS_TO_PASS": '["astropy/units/tests/test_units.py::test_old"]',
        "test_patch": TEST_PATCH,
        "patch": "",
    }
    return Task.model_validate(defaults | fields)


def pulled(instance_id: str) -> Task:
    """The task, skipping the test unless Docker runs and the task's image is pulled."""
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode != 0:
        pytest.skip("Docker is not running")
    task = load_tasks()[instance_id]
    if not local(task.image):
        pytest.skip(f"{task.image} is not pulled")
    return task
