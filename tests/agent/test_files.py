import os

import pytest

from agent import texts
from agent.directory import AgentDirectory
from agent.files import FileTools


def test_reading_writing_editing_and_listing_your_files(directory):
    tools = FileTools(directory)
    assert tools.call("write_file", {"path": "memory/notes/ben.md", "content": "a\nb\nc\nd\n"}).text
    assert tools.call("read_file", {"path": "memory/notes/ben.md"}).text == "a\nb\nc\nd\n"
    part = tools.call("read_file", {"path": "memory/notes/ben.md", "offset": 2, "limit": 2}).text
    assert part.startswith("Lines 2 to 3 of 4") and part.endswith("b\nc\n")
    assert tools.call("read_file", {"path": "memory/notes/ben.md", "offset": 9}).text == (
        "memory/notes/ben.md has 4 lines; there is no line 9."
    )
    assert tools.call(
        "edit_file", {"path": "memory/notes/ben.md", "old_text": "c", "new_text": "C"}
    )
    assert (directory.root / "memory/notes/ben.md").read_text() == "a\nb\nC\nd\n"
    repeated = tools.call("edit_file", {"path": "background.md", "old_text": "a", "new_text": "x"})
    assert "times" in repeated.text
    missing = tools.call("edit_file", {"path": "background.md", "old_text": "zz", "new_text": ""})
    assert missing.text == texts.PASSAGE_MISSING.format(path="background.md")
    listing = tools.call("list_files", {}).text.splitlines()
    assert listing[0] == "background.md" and "memory/notes/ben.md" in listing
    assert not any(name.endswith(".jsonl") for name in listing)
    assert tools.call("list_files", {"path": "skills"}).text.startswith("There are no files")
    assert "needs path" in tools.call("read_file", {}).text
    assert "whole number" in tools.call("read_file", {"path": "background.md", "offset": 0}).text


@pytest.mark.parametrize(
    "path",
    [
        "../ben/background.md",
        "/etc/passwd",
        "session.jsonl",
        "trace.jsonl",
        ".git/config",
        "memory/../trace.jsonl",
        "memory",
        "",
        "memory/escape/x.md",
        "memory/session-link",
    ],
)
def test_paths_outside_your_files_are_refused(directory, tmp_path, path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    os.symlink(outside, directory.root / "memory" / "escape")
    os.symlink(directory.session_path, directory.root / "memory" / "session-link")
    directory.session_path.write_text("", encoding="utf-8")
    tools = FileTools(directory)
    for name, args in (
        ("read_file", {"path": path}),
        ("write_file", {"path": path, "content": "x"}),
        ("edit_file", {"path": path, "old_text": "", "new_text": "x"}),
    ):
        assert tools.call(name, args).text == texts.OUTSIDE.format(path=path)
    assert directory.session_path.read_text() == "" and not any(outside.iterdir())


def test_skills_cannot_be_written_by_any_path_when_read_only(directory):
    (directory.root / "skills" / "bisect.md").write_text("Finding a bad commit.", encoding="utf-8")
    os.symlink(directory.root / "skills", directory.root / "memory" / "skills-link")
    tools = FileTools(AgentDirectory(directory.root, skills_writable=False))
    for name, args in (
        ("write_file", {"path": "skills/new.md", "content": "x"}),
        ("write_file", {"path": "memory/skills-link/new.md", "content": "x"}),
        ("edit_file", {"path": "skills/bisect.md", "old_text": "bad", "new_text": "good"}),
    ):
        assert tools.call(name, args).text == texts.SKILLS_READ_ONLY
    assert tools.call("read_file", {"path": "skills/bisect.md"}).text == "Finding a bad commit."
    assert sorted(p.name for p in (directory.root / "skills").iterdir()) == ["bisect.md"]
    assert tools.call("write_file", {"path": "memory/notes.md", "content": "x"}).text.startswith(
        "Wrote"
    )


def test_the_journal_is_read_but_never_written_or_changed_by_the_file_tools(directory):
    journal = directory.root / "memory" / "journal"
    journal.mkdir(parents=True, exist_ok=True)
    (journal / "2026-10-29.md").write_text("Fixed task 717.\n", encoding="utf-8")
    os.symlink(journal, directory.root / "memory" / "diary")
    tools = FileTools(directory)
    for name, args in (
        ("write_file", {"path": "memory/journal/2026-10-29.md", "content": "A quiet day.\n"}),
        ("write_file", {"path": "memory/journal/2026-10-30.md", "content": "Tomorrow.\n"}),
        ("write_file", {"path": "memory/diary/2026-10-29.md", "content": "A quiet day.\n"}),
        ("edit_file", {"path": "memory/journal/2026-10-29.md", "old_text": "717", "new_text": "1"}),
    ):
        assert tools.call(name, args).text == texts.JOURNAL_KEPT
    assert tools.call("read_file", {"path": "memory/journal/2026-10-29.md"}).text == (
        "Fixed task 717.\n"
    )
    assert sorted(p.name for p in journal.iterdir()) == ["2026-10-29.md"]
    # A file of its own named after a journal is its own to write.
    assert tools.call("write_file", {"path": "memory/journal.md", "content": "x"}).text == (
        "Wrote memory/journal.md."
    )
