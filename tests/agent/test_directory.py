import shutil

import pytest

from agent import texts
from agent.directory import AgentDirectory
from agent.files import FileTools
from tests.agent.conftest import BACKGROUND


def test_the_system_prompt_opens_with_the_residents_own_account_and_follows_the_files(directory):
    rules = "## The town\n\nThe café is open all day."
    first = directory.system_prompt(rules)
    assert first == directory.system_prompt(rules)
    assert first.startswith(f"{texts.ABOUT_ME}\n\n{BACKGROUND}\n\n{rules}\n\n")
    assert first.endswith(f"{texts.FILES}\n\n- background.md\n")

    directory.session_path.write_text("{}\n", encoding="utf-8")
    assert directory.system_prompt(rules) == first
    (directory.root / "memory" / "people.md").write_text("Ben fixes printers.", encoding="utf-8")
    assert directory.system_prompt(rules).endswith("- memory/people.md\n")

    FileTools(directory).call(
        "write_file", {"path": "skills/bisect.md", "content": "# Finding a bad commit\n\nSteps."}
    )
    second = directory.system_prompt(rules)
    assert second != first and "- skills/bisect.md: Finding a bad commit" in second
    assert "session.jsonl" not in second

    edited = FileTools(directory).call(
        "edit_file", {"path": "background.md", "old_text": "a programmer", "new_text": "a baker"}
    )
    assert edited.text == "Changed background.md."
    third = directory.system_prompt(rules)
    assert third.startswith(f"{texts.ABOUT_ME}\n\nI am Ana Reyes, thirty-four, a baker who")
    assert third.replace("a baker", "a programmer") == second

    locked = AgentDirectory(directory.root, skills_writable=False)
    assert "can read the files in skills/ but not change them" in locked.system_prompt(rules)


def test_an_export_without_empty_folders_loads_and_a_missing_one_is_refused(directory):
    shutil.rmtree(directory.root / "skills")
    shutil.rmtree(directory.root / "memory" / "journal")
    exported = AgentDirectory(directory.root)
    assert "skills/" not in exported.index()
    FileTools(exported).call("write_file", {"path": "skills/a.md", "content": "Reading logs."})
    assert exported.files("skills") == ["skills/a.md"]
    with pytest.raises(FileNotFoundError):
        AgentDirectory(directory.root / "memory")
    with pytest.raises(FileExistsError):
        AgentDirectory.create(directory.root, background="")
