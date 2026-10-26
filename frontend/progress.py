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
          "claims": 80, "submissions": 77, "accepted": 50, "rejected": 25,
          "payments": 50, "paid": 1000, "speeches": 40, "messages": 3, "gifts": 0,
          "purchases": 12, "skills_shared": 0, "ratings": 19, "journals": 8, "forced_sleeps": 0,
          "purse": {"min": 30, "median": 112.5, "max": 300}
      }, ...]
    }

There is one row per lived day. A day counts the markers after its start (from it, for day 1)
up to and including its end, the moment of its checkpoint; the day in progress counts those up
to now. A submission still awaiting its verdict is neither accepted nor rejected; "paid" is the
total of the payments. The purses are the residents' at the end of the day, or now for the day
in progress.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from statistics import mean, median
from typing import Any

from world.clock import clock_time

_COUNTED = {
    "claim": "claims",
    "submission": "submissions",
    "payment": "payments",
    "speech": "speeches",
    "message": "messages",
    "gift": "gifts",
    "purchase": "purchases",
    "skill_shared": "skills_shared",
    "rating": "ratings",
    "journal": "journals",
    "forced_sleep": "forced_sleeps",
}
"""The markers counted, by the name of their count."""


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
        | dict.fromkeys([*_COUNTED.values(), "accepted", "rejected", "paid"], 0)
        for day in days
    ]
    ends = [day["end"] for day in days if day["end"] is not None]
    moments = [now if day["end"] is None else day["end"] for day in days]
    purses: list[list[int]] = [[] for _ in days]
    for resident in data["residents"]:
        for marker in resident["markers"]:
            kind = marker["kind"]
            if kind not in _COUNTED:
                continue
            row = rows[bisect_left(ends, marker["t"])]
            row[_COUNTED[kind]] += 1
            if kind == "submission" and "resolved" in marker:
                row["accepted" if marker["resolved"] else "rejected"] += 1
            elif kind == "payment":
                row["paid"] += marker["amount"]
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
