import pytest

from tasks.swebench.pilot import container_args, image_for, public_issue


def test_model_prompt_never_includes_reference_or_grading_material():
    row = {
        "repo": "org/repo",
        "problem_statement": "Fix the parser",
        "patch": "SECRET_GOLD",
        "test_patch": "SECRET_TEST",
        "hints_text": "SECRET_HINT",
        "FAIL_TO_PASS": "SECRET_FAILURES",
    }
    assert public_issue(row) == "Repository: org/repo\nIssue:\nFix the parser"


def test_container_has_no_host_mounts_or_network_or_docker_socket():
    args = container_args("pilot", "image")
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[args.index("--security-opt") + 1] == "no-new-privileges"
    assert not {"--privileged", "-v", "--volume", "--mount", "--env-file"} & set(args)


def test_image_names_are_validated_before_docker_access():
    assert image_for("astropy__astropy-12907").endswith("astropy_1776_astropy-12907:latest")
    with pytest.raises(ValueError):
        image_for("../../other/image")
