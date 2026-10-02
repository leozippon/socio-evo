from datetime import UTC, datetime, timedelta, timezone

import pytest

from infrastructure.git import GitError, Repository

START = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def repo(tmp_path) -> Repository:
    return Repository.init(tmp_path / "ana", user_name="Ana", user_email="ana@agents.invalid")


def _write(repo: Repository, relative: str, text: str) -> None:
    path = repo.path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_history_contents_and_diff(repo):
    _write(repo, "policy.md", "v1\n")
    first = repo.commit("Write policy: 先完成任务\n\nLevel: L2\nTrigger: monthly", date=START)
    _write(repo, "policy.md", "v2\n")
    _write(repo, "skills/review.md", "Read the tests first.\n")
    second = repo.commit("Revise policy", date=START + timedelta(days=1))

    assert repo.head() == second
    newest, oldest = repo.log()
    assert (newest.id, newest.parent, newest.date) == (second, first, START + timedelta(days=1))
    assert (oldest.id, oldest.parent, oldest.date) == (first, None, START)
    assert (oldest.subject, oldest.body) == (
        "Write policy: 先完成任务",
        "Level: L2\nTrigger: monthly",
    )
    assert repo.read_file(first, "policy.md") == "v1\n"
    diff = repo.diff(first, second)
    assert "-v1" in diff and "+v2" in diff and "skills/review.md" in diff


def test_commit_date_keeps_its_offset(repo):
    date = datetime(2030, 1, 1, 21, 30, tzinfo=timezone(timedelta(hours=8)))
    _write(repo, "a.md", "a\n")
    repo.commit("a", date=date)
    logged = repo.log()[0].date
    assert logged == date and logged.utcoffset() == date.utcoffset()


def test_reset_hard_restores_the_exact_tree(repo):
    _write(repo, "policy.md", "v1\n")
    first = repo.commit("v1", date=START)
    _write(repo, "policy.md", "v2\n")
    _write(repo, "skills/new.md", "new\n")
    repo.commit("v2", date=START + timedelta(days=1))
    _write(repo, "scratch/uncommitted.md", "lost\n")

    repo.reset_hard(first)
    assert repo.head() == first
    assert sorted(p.name for p in repo.path.iterdir()) == [".git", "policy.md"]
    assert (repo.path / "policy.md").read_text() == "v1\n"


def test_tag_and_export_a_frozen_snapshot(repo, tmp_path):
    _write(repo, "policy.md", "v1\n")
    repo.commit("v1", date=START)
    repo.tag("day-0001")
    _write(repo, "policy.md", "v2\n")
    repo.commit("v2", date=START + timedelta(days=1))

    snapshot = tmp_path / "snapshots" / "ana-day-0001"
    repo.export("day-0001", snapshot)
    assert sorted(p.name for p in snapshot.iterdir()) == ["policy.md"]
    assert (snapshot / "policy.md").read_text() == "v1\n"
    with pytest.raises(FileExistsError):
        repo.export("day-0001", snapshot)
    with pytest.raises(GitError):
        repo.tag("day-0001")


def test_failures_raise_git_error(repo):
    with pytest.raises(GitError) as failure:
        repo.head()
    assert failure.value.returncode != 0 and failure.value.stderr
    _write(repo, "a.md", "a\n")
    repo.commit("a", date=START)
    with pytest.raises(GitError, match="nothing to commit"):
        repo.commit("again", date=START)
    with pytest.raises(GitError):
        repo.read_file("HEAD", "missing.md")
    with pytest.raises(ValueError):
        repo.commit("naive", date=datetime(2030, 1, 1))


def test_a_directory_without_a_repository_never_reaches_an_enclosing_one(repo):
    _write(repo, "nested/notes.md", "n\n")
    repo.commit("nested", date=START)
    with pytest.raises(GitError):
        Repository(repo.path / "nested").head()


def test_host_git_setup_is_ignored(tmp_path, monkeypatch):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for hook in ("pre-commit", "commit-msg", "post-commit"):
        (hooks / hook).write_text("#!/bin/sh\nexit 1\n")
        (hooks / hook).chmod(0o755)
    host_config = tmp_path / "host.gitconfig"
    host_config.write_text(
        "[commit]\n\tgpgSign = true\n[user]\n\tsigningKey = missing\n"
        f"[core]\n\thooksPath = {hooks}\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(host_config))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))

    repo = Repository.init(tmp_path / "ana", user_name="Ana", user_email="ana@agents.invalid")
    _write(repo, "a.md", "a\n")
    repo.commit("a", date=START)
    assert repo.log()[0].subject == "a"
    assert (repo.path / ".git").is_dir() and not (tmp_path / "elsewhere").exists()
