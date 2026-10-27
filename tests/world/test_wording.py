"""Nothing a resident reads names a trait, speaks of the machinery, tells a day's number or the
length of the run: every string the world's code holds, and every text it renders for the four
groups, passes the guard."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import world
from agent.wording import offences
from tests.world.conftest import B_EXCHANGE, awake_at, town_config
from world.events import Idle, Movement, Sleep, Work, refusal
from world.rules import TOPICS

GROUPS = {
    "A": town_config("isolated"),
    "B": town_config("isolated", exchange=B_EXCHANGE),
    "C": town_config("town"),
    "D": town_config("town", shareable=False),
}
DAY_NUMBER = re.compile(r"\b[Dd]ay[ -]?\d")


def _strings(path: Path) -> list[str]:
    """Every string constant of a module but its docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


@pytest.mark.parametrize("module", sorted(Path(world.__file__).parent.glob("*.py")), ids=str)
def test_no_string_in_the_worlds_code_offends(module):
    assert [(s, offences(s)) for s in _strings(module) if offences(s)] == []


def _check(texts: list[str]) -> None:
    bad = [(text, offences(text)) for text in texts if offences(text)]
    assert bad == []
    assert [text for text in texts if DAY_NUMBER.search(text)] == []


@pytest.mark.parametrize("group", sorted(GROUPS))
async def test_every_rendered_text_passes_the_guard(group, make_town, tmp_path):
    town = make_town(GROUPS[group], root=tmp_path / group)
    world_ = town.world
    texts = [world_.rules.text(name) for name in world_.residents]
    texts += [world_.rules.people_notes(name) for name in world_.residents]
    texts += [world_.rules.help("Mei", topic) for topic in (*TOPICS, "anything")]
    for spec in world_.tool_specs:
        texts.append(spec.description)
        for parameter in spec.parameters["properties"].values():
            texts += [parameter.get("description", ""), *parameter.get("enum", [])]
    events = [
        Idle(),
        Movement("cafe", 0),
        Work(),
        Sleep(0),
        Sleep(0, True),
    ]
    texts += [
        refusal(event, spec.name, destination="the café")
        for event in events
        for spec in world_.tool_specs
    ]
    texts.append(world_.ports["Mei"].situation())
    await awake_at(town)
    texts += [world_.ports[name].situation() for name in world_.residents]
    await town.call("Mei", "say", text="Morning.")
    await town.call("Mei", "go", place="store")
    await town.until("07:10")
    texts.append((await town.call("Mei", "buy", item="coat")).text)
    texts.append((await town.call("Mei", "buy", item="groceries")).text)
    texts.append((await town.call("Mei", "help", topic="money")).text)
    await town.call("Mei", "go", place="workshop")
    texts.append(world_.ports["Mei"].situation())
    await town.until("09:00")
    texts.append((await town.call("Mei", "look_around")).text)
    texts.append((await town.call("Mei", "view_board")).text)
    await town.call("Mei", "claim_task", task=1)
    texts.append(world_.ports["Mei"].situation())
    await town.call("Mei", "write_repo_file", path="a.py", content="x\n")
    texts.append((await town.call("Mei", "submit")).text)
    await town.call("Mei", "leave_work")
    texts.append((await town.call("Mei", "shell", command="ls")).text)  # sitting down again
    texts.append((await town.call("Mei", "leave_work")).text)
    texts.append((await town.call("Mei", "sleep", until="07:00", journal="Tired.")).text)
    await town.until("19:30")
    await town.call("Mei", "go", place="mill-street-house")
    await town.until("21:00")
    await town.call("Mei", "sleep", until="07:00", journal="Worked on a task.")
    texts.append(world_.ports["Mei"].situation())
    texts.append((await town.call("Mei", "review_day")).text)
    town.rest()
    await town.until("18:00", day=2)
    for entry in world_.log.entries():
        if entry["audience"] or entry["personal"]:
            texts += [entry["text"], *entry["personal"].values()]
    _check([text for text in texts if text])
