"""How far a run has come, day by day: what the overview of all the runs shows of each.

`progress(data)` reduces the timeline of a run (`frontend.timeline`) to plain,
JSON-serialisable data:

    {
      "day": 4,               the day in progress, or the last day lived when none is
      "now": 313757,          the time of the last entry in the log
      "clock": "15:09",       its hour
      "hours_per_day": 2.6,   the mean real hours of the completed days; null before the first
      "currency": "$",
      "daily": [{
          "day": 1, "date": "2026-03-02", "in_progress": false,
          "hours": 2.57,      the real hours from the day's beginning to its checkpoint; null
                              for the day in progress
          "arrived": 3, "claims": 1, "assigned": 2, "submissions": 3, "accepted": 2,
          "rejected": 1, "withdrawn": 0, "sales": 10, "dishes": 5, "examinations": 1,
          "treatments": 1, "announcements": 1, "speeches": 40, "messages": 3, "gifts": 0,
          "journals": 8, "illnesses": 0, "bedridden": 0, "forced_sleeps": 0,
          "purse": {"min": 30, "median": 112.5, "max": 300}
      }, ...]
    }

There is one row per lived day. A day counts the markers, the residents' and the town's, after its
start (from it, for day 1) up to and including its end, the moment of its checkpoint; the day in
progress counts those up to now. A submission still awaiting its verdict is neither accepted nor
rejected. The moves are counted as `world.log.counted_move` names them: a purchase at the Store's
counter is a sale, the chef's for the kitchen among them; a portion from the kitchen, bought or
handed over by the chef, is a dish; money or a thing passed from one resident to another is a gift;
taking, leaving and eating are not counted. The purses are the money the residents held at the end
of the day, or now for the day in progress.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from statistics import mean, median
from typing import Any

from world.clock import clock_time
from world.log import counted_move

COUNTS = (
    "arrived",
    "claims",
    "assigned",
    "submissions",
    "accepted",
    "rejected",
    "withdrawn",
    "sales",
    "dishes",
    "examinations",
    "treatments",
    "announcements",
    "speeches",
    "messages",
    "gifts",
    "journals",
    "illnesses",
    "bedridden",
    "forced_sleeps",
)
"""The counts of a day, in the order the rows give them."""
_COUNTED = {
    "task_arrived": "arrived",
    "claim": "claims",
    "assign": "assigned",
    "submission": "submissions",
    "task_withdrawn": "withdrawn",
    "examination": "examinations",
    "treatment": "treatments",
    "announcement": "announcements",
    "speech": "speeches",
    "message": "messages",
    "journal": "journals",
    "illness": "illnesses",
    "bedridden": "bedridden",
    "forced_sleep": "forced_sleeps",
}
"""The markers counted, by the name of their count; moves are counted by `_counted`."""
_MOVES = {"sale": "sales", "dish": "dishes", "gift": "gifts"}


def _counted(marker: dict[str, Any]) -> str | None:
    """The count a marker adds to, if any (see the module docstring)."""
    if marker["kind"] != "move":
        return _COUNTED.get(marker["kind"])
    moved = counted_move(marker)
    return None if moved is None else _MOVES[moved]


def progress(data: dict[str, Any]) -> dict[str, Any]:
    """The progress of the run whose timeline is `data`, as the module docstring describes it."""
    days, now = data["days"], data["now"]
    first = date.fromisoformat(data["start_date"])
    rows = [
        {
            "day": day["day"],
            "date": (first + timedelta(days=day["day"] - 1)).isoformat(),
            "in_progress": day["end"] is None,
            "hours": None if day["end"] is None else (day["real_end"] - day["real_start"]) / 3600,
        }
        | dict.fromkeys(COUNTS, 0)
        for day in days
    ]
    ends = [day["end"] for day in days if day["end"] is not None]
    moments = [now if day["end"] is None else day["end"] for day in days]
    purses: list[list[int]] = [[] for _ in days]
    markers = [*data["markers"], *(m for lane in data["residents"] for m in lane["markers"])]
    for marker in markers:
        counted = _counted(marker)
        if counted is None:
            continue
        row = rows[bisect_left(ends, marker["t"])]
        row[counted] += 1
        if counted == "submissions" and "resolved" in marker:
            row["accepted" if marker["resolved"] else "rejected"] += 1
    for resident in data["residents"]:
        times = [t for t, _ in resident["purse"]]
        for held, moment in zip(purses, moments, strict=True):
            held.append(resident["purse"][bisect_right(times, moment) - 1][1])
    for row, held in zip(rows, purses, strict=True):
        row["purse"] = {"min": min(held), "median": median(held), "max": max(held)}
    completed = [row["hours"] for row in rows if not row["in_progress"]]
    return {
        "day": days[-1]["day"],
        "now": now,
        "clock": clock_time(now),
        "hours_per_day": mean(completed) if completed else None,
        "currency": data["currency"],
        "daily": rows,
    }
