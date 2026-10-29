"""The occupations the world implements, by id: for each, the kind of place where it works, the
work it adds to what everyone can do there, and the rules' words for that work and for its sum
per service (`OCCUPATIONS`). A new occupation is code here and in the tools that do its work.

What else an occupation is belongs to the town's configuration (`world.config.Occupation`): its
title, its workplace among the town's places, its wage an hour and its sum per service, where its
duty runs (at its workplace, or anywhere once it has sat down to work: the mayor's) and who pays
its wages (the fund, or the fund's tax account: the mayor's). An occupation keeps the business of
its workplace, if that place has one (`world.businesses`): the shopkeeper the Store's counter, the
chef the Restaurant's kitchen, the doctor the Hospital's surgery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OccupationId = Literal["programmer", "team-leader", "chef", "shopkeeper", "doctor", "mayor"]
PROGRAMMER: OccupationId = "programmer"
TEAM_LEADER: OccupationId = "team-leader"
"""The programmers' leader, who gives them tasks and is paid a sum for each of theirs accepted."""
CHEF: OccupationId = "chef"
SHOPKEEPER: OccupationId = "shopkeeper"
DOCTOR: OccupationId = "doctor"
MAYOR: OccupationId = "mayor"

BOARD_TOOLS = frozenset({"view_board", "read_task", "claim_task"})
"""What reads and claims from the board, which hangs at the office."""
TASK_TOOLS = frozenset(
    {"shell", "read_repo_file", "write_repo_file", "edit_repo_file", "submit", "abandon_task"}
)
"""What acts on the task one holds, of use only to one who holds a task, at the office."""
BEDSIDE = frozenset({"examine", "treat"})
"""The doctor's work that is also done at the home of one too ill to get up."""


@dataclass(frozen=True)
class Trade:
    """What the world does for an occupation: `workplace`, the kind of place where it works;
    `work`, the tools it adds to what everyone can do, done at its workplace; `told`, what its
    work is, as the rules tell it after its workplace (`{office}`, `{store}` and `{withdrawn}`
    filled in); `service`, what its sum per service is paid for, as the money rules tell it."""

    workplace: str
    work: frozenset[str]
    told: str
    service: str


OCCUPATIONS: dict[str, Trade] = {
    PROGRAMMER: Trade(
        workplace="office",
        work=BOARD_TOOLS | TASK_TOOLS,
        told=(
            "Clients' tasks come in on its board through the day: you take one at a time with "
            "claim_task, or are given one by the team leader, work on it there, where the "
            "machines are, and hand it in for the client's checks before the client withdraws "
            "it, at the end of {withdrawn}."
        ),
        service="for each task of yours accepted",
    ),
    TEAM_LEADER: Trade(
        workplace="office",
        work=BOARD_TOOLS | TASK_TOOLS | {"assign"},
        told=(
            "You lead its programmers. Clients' tasks come in on its board through the day: you "
            "can give any of them a task with assign, and, like them, take one at a time "
            "yourself, work on it there, where the machines are, and hand it in for the "
            "client's checks before the client withdraws it, at the end of {withdrawn}. Each "
            "midnight your statement tells you {office}'s day."
        ),
        service="for each task of the programmers' accepted",
    ),
    CHEF: Trade(
        workplace="restaurant",
        work=frozenset({"cook", "set_price"}),
        told=(
            "Its kitchen is open while you are at work there: you cook dishes from what the "
            "kitchen holds and set the menu's prices, and whoever comes buys a dish, or is "
            "handed one by you with pass and pays nothing; you have one yourself with eat. You "
            "buy what you cook with at {store} with buy for_the_kitchen, and the fund pays."
        ),
        service="for each dish served",
    ),
    SHOPKEEPER: Trade(
        workplace="store",
        work=frozenset({"order", "set_price"}),
        told=(
            "Its counter is open while you are at work there: you sell its goods at the prices "
            "you set, and order more from the supplier, which the fund pays and which arrives "
            "the next morning."
        ),
        service="for each sale",
    ),
    DOCTOR: Trade(
        workplace="hospital",
        work=frozenset({"examine", "treat", "set_price"}),
        told=(
            "Its surgery is open while you are at work there: you examine and treat patients, "
            "at fees you set, and you go to the bedside of anyone too ill to get up."
        ),
        service="for each patient examined or treated",
    ),
    MAYOR: Trade(
        workplace="hall",
        work=frozenset({"report", "announce"}),
        told=(
            "There you read the town's report with report, and with announce you tell every "
            "resident whatever you want them to know. Your work is being about the town, so "
            "once you have sat down to work it goes with you wherever you go."
        ),
        service="for each service",
    ),
}
"""Each occupation the world implements, by its id."""
WORK_DONE = frozenset().union(*(trade.work for trade in OCCUPATIONS.values()))
"""Everything that is some occupation's work."""
