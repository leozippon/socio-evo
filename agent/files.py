"""The file tools: reading and changing the resident's own files, and nothing else.

A path is relative to the agent directory and must name background.md or something under
memory/ or skills/ once every symbolic link in it is followed; absolute paths and `..` are
refused, and so is any write under skills/ when the directory keeps skills read-only. Every
refusal is a result the resident reads, never an exception.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from agent import texts
from agent.directory import AREAS, BACKGROUND, SKILLS, AgentDirectory
from agent.port import ToolResult, ToolSpec


def _path(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


SPECS = (
    ToolSpec(
        name="read_file",
        description=(
            "Read one of your files. For a long file, give offset and limit to read some of "
            "its lines."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": _path("The file, such as memory/people.md."),
                "offset": {"type": "integer", "description": "The first line to read, from 1."},
                "limit": {"type": "integer", "description": "How many lines to read."},
            },
            "required": ["path"],
        },
    ),
    ToolSpec(
        name="write_file",
        description=(
            "Write one of your files, replacing all it held, or create it with any folders "
            "it needs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": _path("The file, such as skills/reading-a-traceback.md."),
                "content": {"type": "string", "description": "Everything the file is to hold."},
            },
            "required": ["path", "content"],
        },
    ),
    ToolSpec(
        name="edit_file",
        description=(
            "Replace a passage of one of your files with new text. The passage must appear "
            "exactly once in the file."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": _path("The file, such as memory/work.md."),
                "old_text": {"type": "string", "description": "The passage as it stands."},
                "new_text": {"type": "string", "description": "What replaces it."},
            },
            "required": ["path", "old_text", "new_text"],
        },
    ),
    ToolSpec(
        name="list_files",
        description="List your files, or those in one folder, such as skills.",
        parameters={
            "type": "object",
            "properties": {"path": _path("A folder, such as memory; all your files if left out.")},
        },
    ),
)
NAMES = frozenset(spec.name for spec in SPECS)


class _Refusal(Exception):
    """A call that cannot be carried out; its message is what the resident reads."""


class FileTools:
    """The file tools over one agent directory."""

    def __init__(self, directory: AgentDirectory) -> None:
        self._directory = directory
        self._root = directory.root.resolve()

    def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Carry out file tool `name` with `args`; a refusal is the result's text. A name
        that is no file tool raises KeyError."""
        if name not in NAMES:
            raise KeyError(name)
        try:
            return ToolResult(getattr(self, f"_{name}")(args))
        except _Refusal as refusal:
            return ToolResult(str(refusal))

    def _read_file(self, args: dict[str, Any]) -> str:
        path = _text(args, "read_file", "path")
        file = self._file(path, writing=False)
        text = file.read_text(encoding="utf-8", errors="replace")
        offset, limit = _number(args, "read_file", "offset"), _number(args, "read_file", "limit")
        if offset is None and limit is None:
            return text or texts.EMPTY_FILE.format(path=path)
        lines = text.splitlines(keepends=True)
        first = offset or 1
        chosen = lines[first - 1 : None if limit is None else first - 1 + limit]
        last = first + len(chosen) - 1
        return texts.PART_OF_FILE.format(
            first=first, last=last, total=len(lines), path=path, text="".join(chosen)
        )

    def _write_file(self, args: dict[str, Any]) -> str:
        path = _text(args, "write_file", "path")
        content = _text(args, "write_file", "content")
        target = self._locate(path, writing=True)
        if target.is_dir():
            raise _Refusal(texts.A_FOLDER.format(path=path))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return texts.WROTE.format(path=path)

    def _edit_file(self, args: dict[str, Any]) -> str:
        path = _text(args, "edit_file", "path")
        old, new = _text(args, "edit_file", "old_text"), _text(args, "edit_file", "new_text")
        file = self._file(path, writing=True)
        text = file.read_text(encoding="utf-8")
        count = text.count(old) if old else 0
        if count == 0:
            raise _Refusal(texts.PASSAGE_MISSING.format(path=path))
        if count > 1:
            raise _Refusal(texts.PASSAGE_REPEATED.format(count=count, path=path))
        file.write_text(text.replace(old, new, 1), encoding="utf-8")
        return texts.EDITED.format(path=path)

    def _list_files(self, args: dict[str, Any]) -> str:
        folder = args.get("path") or ""
        if not isinstance(folder, str):
            raise _Refusal(texts.NEEDS.format(name="list_files", argument="path", kind=texts.TEXT))
        if folder.strip("/"):
            located = self._locate(folder, writing=False, folder=True)
            folder = located.relative_to(self._root).as_posix()
        files = self._directory.files(folder)
        return "\n".join(files) if files else texts.NO_FILES.format(path=folder or "your folders")

    def _file(self, path: str, *, writing: bool) -> Path:
        """The existing file `path` names."""
        target = self._locate(path, writing=writing)
        if target.is_dir():
            raise _Refusal(texts.A_FOLDER.format(path=path))
        if not target.is_file():
            raise _Refusal(texts.NO_FILE.format(path=path))
        return target

    def _locate(self, path: str, *, writing: bool, folder: bool = False) -> Path:
        """Where `path` leads once its links are followed, if that is one of the resident's
        files (or, with `folder`, one of its folders) and, when `writing`, writable."""
        relative = PurePosixPath(path.strip())
        if not path.strip() or relative.is_absolute() or ".." in relative.parts:
            raise _Refusal(texts.OUTSIDE.format(path=path))
        target = (self._root / relative).resolve()
        if not target.is_relative_to(self._root):
            raise _Refusal(texts.OUTSIDE.format(path=path))
        parts = target.relative_to(self._root).parts
        reachable = parts == (BACKGROUND,) or (
            bool(parts) and parts[0] in AREAS and (folder or len(parts) > 1)
        )
        if not reachable:
            raise _Refusal(texts.OUTSIDE.format(path=path))
        if writing and parts[0] == SKILLS and not self._directory.skills_writable:
            raise _Refusal(texts.SKILLS_READ_ONLY)
        return target


def _text(args: dict[str, Any], tool: str, name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str):
        raise _Refusal(texts.NEEDS.format(name=tool, argument=name, kind=texts.TEXT))
    return value


def _number(args: dict[str, Any], tool: str, name: str) -> int | None:
    value = args.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _Refusal(texts.NEEDS.format(name=tool, argument=name, kind=texts.NUMBER))
    return value
