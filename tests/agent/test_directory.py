import shutil

import pytest

from agent.directory import AgentDirectory
from agent.files import FileTools


def test_the_system_prompt_stays_byte_identical_until_the_index_changes(directory):
    rules = "## The town\n\nThe café is open all day."
    first = directory.system_prompt(rules)
    assert first == directory.system_prompt(rules)
    assert first.startswith("# Ana Reyes") and rules in first
    assert "- memory/people.md: the people you know" in first

    (directory.root / "memory" / "people.md").write_text("Ben fixes printers.", encoding="utf-8")
    directory.session_path.write_text("{}\n", encoding="utf-8")
    assert directory.system_prompt(rules) == first

    FileTools(directory).call(
        "write_file", {"path": "skills/bisect.md", "content": "# Finding a bad commit\n\nSteps."}
    )
    second = directory.system_prompt(rules)
    assert second != first and "- skills/bisect.md: Finding a bad commit" in second
    assert "session.jsonl" not in second

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
        AgentDirectory.create(directory.root, background="", town="")
