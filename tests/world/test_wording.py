"""Nothing a resident reads names a trait, speaks of the machinery, tells a day's number or the
length of the run: every string the world's code holds, and every text it renders, passes the
guard."""

from __future__ import annotations

import ast
import copy
import re
from pathlib import Path

import pytest

import world
from agent.wording import offences
from tests.support.towns import CARE, NEEDS, RESIDENTS, TRADES, awake_at, backend_of, town_config
from tests.world.acts import give, take
from world.events import Bedridden, Conversation, Idle, Movement, Sleep, Work, refusal
from world.rules import TOPICS

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


async def test_every_rendered_text_passes_the_guard(make_town):
    leader = dict(RESIDENTS[1], occupation="team-leader")
    needs = copy.deepcopy(NEEDS)
    needs["health"]["illness"]["chance"] = 1
    config = town_config(
        residents=(RESIDENTS[0], leader, RESIDENTS[2], *TRADES, *CARE), needs=needs, tax=0.1
    )
    town = make_town(config, backend_of({"org/repo": 3}))
    world_ = town.world
    texts = [world_.rules.text(name) for name in world_.residents]
    texts += [world_.rules.help(topic) for topic in (*TOPICS, "anything")]
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
        Bedridden(),
        Conversation("cafe", set(), 0),
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
    for name in ("Mei", "Olga", "Jonas"):
        await town.call(name, "go", place="store")
    await town.call("Aisha", "go", place="cafe")
    await town.until("07:10")
    texts.append(world_.ports["Mei"].situation())  # the shelves, nobody at work
    texts.append(await take(town, "Mei", "coat", "shelves"))
    texts.append((await town.call("Olga", "start_work")).text)
    texts.append(world_.ports["Mei"].situation())  # the keeper at work
    texts.append(await take(town, "Mei", "coat", "shelves"))  # none left
    texts.append(await take(town, "Mei", "bread", "shelves", 20))  # all there was
    texts.append(await give(town, "Mei", "money", "Olga", 70))  # taxed, and told so
    texts.append(await give(town, "Mei", "money", "Olga", 700))  # more than it has
    texts.append(await give(town, "Mei", "bread", "here"))
    texts.append(await give(town, "Mei", "money", "here", 2))
    texts.append(await give(town, "Mei", "bread", "shelves"))
    texts.append(world_.ports["Mei"].situation())  # what is left here, and on the shelves
    texts.append(await take(town, "Mei", "bread", "here", 2))  # only one
    texts.append(await take(town, "Mei", "bread", "here"))  # none
    texts.append(await take(town, "Mei", "money", "Olga", 3))
    texts.append(await take(town, "Mei", "phone", "Olga"))  # she has none
    texts.append(await give(town, "Mei", "coat", "Olga"))
    texts.append(await give(town, "Mei", "coat", "Olga"))  # none left to give
    texts.append(await take(town, "Mei", "eggs", "counter"))  # not here
    texts.append(await take(town, "Mei", "eggs", "Tomas"))  # not here
    texts.append(await take(town, "Mei", "eggs", "Nobody"))
    texts.append(await take(town, "Mei", "eggs", "Mei"))
    texts.append(await give(town, "Mei", "bread", "Mei"))
    texts.append((await town.call("Mei", "use", what="bread")).text)
    world_.residents["Mei"].inventory.items.pop("bread", None)
    texts.append((await town.call("Mei", "use", what="bread")).text)  # none carried
    texts.append((await town.call("Mei", "order", item="bread", quantity=1)).text)
    texts.append((await town.call("Olga", "order", item="bread", quantity=3)).text)
    texts.append((await town.call("Olga", "set_price", item="bread", price=5)).text)
    texts.append((await town.call("Olga", "set_price", item="soup", price=5)).text)
    texts.append(world_.ports["Olga"].situation())  # what is on order
    texts.append(await take(town, "Jonas", "eggs", "shelves", 4))
    await take(town, "Jonas", "vegetables", "shelves", 3)
    texts.append((await town.call("Jonas", "start_work")).text)
    texts.append(world_.ports["Aisha"].situation())  # the counter and the larder, nobody there
    texts.append(await take(town, "Aisha", "omelette", "counter"))  # none ready
    texts.append((await town.call("Mei", "help", topic="money")).text)
    texts.append((await town.call("Mei", "inventory")).text)
    await town.call("Jonas", "go", place="cafe")
    await town.until("07:20")
    texts.append(await give(town, "Jonas", "eggs", "larder", 2))
    texts.append((await town.call("Jonas", "cook", dish="omelette", portions=3)).text)  # short
    texts.append((await town.call("Jonas", "cook", dish="omelette", portions=2)).text)
    texts.append((await town.call("Jonas", "set_price", item="bread", price=5)).text)
    texts.append(world_.ports["Aisha"].situation())  # the menu
    texts.append(await take(town, "Aisha", "omelette", "counter"))  # taken and eaten
    texts.append(await take(town, "Jonas", "omelette", "counter"))  # the chef's own
    texts.append(await give(town, "Jonas", "vegetables", "larder"))
    await town.call("Olga", "go", place="cafe")  # leaving her shelves to whoever is there
    texts.append(await take(town, "Mei", "phone", "shelves"))
    await town.until("07:30")
    texts.append(await give(town, "Olga", "money", "Jonas", 20))  # at work: taxed
    for name in ("Olga", "Jonas"):
        await town.call(name, "go", place="store")
    texts.append(await take(town, "Aisha", "vegetables", "larder"))  # the chef away
    await town.until("07:45")  # the keeper back at her shelves, and told what went from them
    await town.call("Jonas", "go", place="cafe")  # and the chef to his larder
    await town.call("Mei", "go", place="workshop")
    await town.call("Tomas", "go", place="workshop")
    for name in ("Lucia", "Aisha"):
        await town.call(name, "go", place="clinic")
    await town.call("Vera", "go", place="hall")
    texts.append(world_.ports["Mei"].situation())
    await town.until("09:00")
    texts.append(world_.ports["Aisha"].situation())  # the surgery's fees
    texts.append((await town.call("Lucia", "start_work")).text)
    world_.body.fall_ill(world_.residents["Aisha"].living)
    texts.append((await town.call("Lucia", "examine", patient="Aisha")).text)
    texts.append((await town.call("Lucia", "examine", patient="Mei")).text)  # not here
    texts.append((await town.call("Lucia", "treat", patient="Aisha")).text)
    texts.append((await town.call("Lucia", "set_price", item="treatment", price=40)).text)
    texts.append((await town.call("Lucia", "set_price", item="bread", price=40)).text)
    texts.append((await town.call("Lucia", "examine", patient="Lucia")).text)  # herself
    texts.append((await town.call("Vera", "announce", text="Market day.")).text)
    texts.append((await town.call("Vera", "look_around")).text)
    texts.append((await town.call("Mei", "look_around")).text)
    texts.append((await town.call("Mei", "view_board")).text)
    texts.append((await town.call("Tomas", "assign", task=2, to="Aisha")).text)
    texts.append((await town.call("Tomas", "assign", task=2, to="Olga")).text)
    texts.append((await town.call("Tomas", "assign", task=7, to="Mei")).text)
    await town.call("Mei", "claim_task", task=1)
    texts.append(world_.ports["Mei"].situation())
    await town.call("Mei", "write_repo_file", path="a.py", content="x\n")
    texts.append((await town.call("Mei", "submit")).text)
    await town.call("Mei", "leave_work")
    texts.append((await town.call("Mei", "shell", command="ls")).text)  # sitting down again
    texts.append((await town.call("Mei", "leave_work")).text)
    await town.call("Mei", "shell", command="ls")
    world_.residents["Mei"].living.energy = 5
    texts.append((await town.call("Mei", "shell", command="ls")).text)  # exhausted: work stops
    world_.residents["Mei"].living.energy = 50
    texts.append((await town.call("Mei", "sleep", likes=[], until="07:00", journal="Tired.")).text)
    await town.until("19:30")
    await town.call("Mei", "go", place="mill-street-house")
    await town.until("21:00")
    await town.call("Mei", "sleep", likes=[], until="07:00", journal="Worked on a task.")
    texts.append(world_.ports["Mei"].situation())
    await town.call("Aisha", "go", place="mill-street-house")  # to her housemate, in bed
    texts.append((await town.call("Mei", "review_day")).text)
    mei = world_.residents["Mei"]
    mei.living.health, mei.living.satiety = 1, 0  # bedridden at midnight, let up the next day
    town.rest()
    await town.until("21:30")
    texts.append(await take(town, "Aisha", "money", "Mei", 4))  # asleep: told on waking
    await town.until("09:00", day=2)
    texts.append(world_.ports["Mei"].situation())
    texts.append((await town.call("Aisha", "look_around")).text)
    world_.treat(mei, 25)
    await town.until("18:00", day=2)
    texts.append((await town.call("Mei", "how_am_i")).text)  # ill since the midnight
    told = set()
    for entry in world_.log.entries():
        if entry["audience"] or entry["personal"]:
            texts += [entry["text"], *entry["personal"].values()]
            told.add(entry["kind"])
    assert {"move", "missing", "cook", "price", "examination", "treatment"} <= told
    missing = [e["personal"][e["actor"]] for e in world_.log.entries() if e["kind"] == "missing"]
    assert len(missing) == 3  # the keeper's shelves, the chef's larder, the sleeper's purse
    assert "Mei gave you $70, of which $7 in tax." in texts
    _check([text for text in texts if text])
