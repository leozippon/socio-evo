"""How a file's text is told in part and changed by a passage, alike for the resident's own files
(`agent.files`) and for the files of a task's repository (`world.workspace`), so that both read
and change files in the same words. The world uses it, beside the port and the guard."""

from __future__ import annotations

from agent import texts


def told_lines(text: str, path: str, offset: int | None, limit: int | None) -> str:
    """`text`, the file `path`, as reading it tells it: whole; or, given `offset` (the first line,
    from 1) or `limit` (how many lines), those lines, headed with where they are in the file, or
    that it has no line `offset`."""
    if offset is None and limit is None:
        return text or texts.EMPTY_FILE.format(path=path)
    lines = text.splitlines(keepends=True)
    first = offset or 1
    if first > len(lines):
        count = f"{len(lines)} line" + ("" if len(lines) == 1 else "s")
        return texts.NO_LINE.format(path=path, count=count, first=first)
    chosen = lines[first - 1 : None if limit is None else first - 1 + limit]
    last = first + len(chosen) - 1
    return texts.PART_OF_FILE.format(
        first=first, last=last, total=len(lines), path=path, text="".join(chosen)
    )


def passage_refusal(text: str, old: str, path: str) -> str | None:
    """Why the passage `old` cannot be replaced in `text`, the file `path`: it does not appear
    in it, or appears more than once; None when it appears exactly once."""
    count = text.count(old) if old else 0
    if count == 0:
        return texts.PASSAGE_MISSING.format(path=path)
    if count > 1:
        return texts.PASSAGE_REPEATED.format(count=count, path=path)
    return None
