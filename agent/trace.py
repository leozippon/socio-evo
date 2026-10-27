"""The trace: one JSON line per thing the runtime does, with simulated and real time.

Kinds and their fields:

- `prompt`: `text`, the system prompt, whenever it is assembled anew;
- `request`: `purpose` (`step` or `compaction`), `messages` (the session ids of the messages
  after the system prompt; a compaction request adds its instruction after them), `tools` (the
  names declared), `reasoning_effort`, `max_tokens`, `attempt` (the request's number among those
  made for one reply, retries after a model error or a cut-off counting on);
- `reply`: the response in full (text, reasoning, tool calls, finish reason, whether cut off
  or aborted, usage, latency), with `purpose`;
- `tool_call`: `id`, `name`, `arguments`, and `unreadable` when the arguments could not be read;
- `tool_result`: `id`, `name`, `text` in full, `ends_turn`, and `error` when carrying the call
  out raised;
- `percept`: the percept's `text`, `percept_kind`, `event_id`, `percept_sim_time`,
  `percept_real_time`;
- `interruption`: `events`, the ids of the percepts that aborted the reply in flight;
- `compaction`: `id` (the session record), `replaced`, `kept`, `summary`;
- `lapse`: `purpose` and `errors`, when a request found no usable reply.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from infrastructure.storage import append_jsonl

Kind = Literal[
    "prompt",
    "request",
    "reply",
    "tool_call",
    "tool_result",
    "percept",
    "interruption",
    "compaction",
    "lapse",
]


class Trace:
    """The trace at `path`; `sim_time` gives the simulated time of each record."""

    def __init__(self, path: Path, sim_time: Callable[[], int]) -> None:
        self._path = path
        self._sim_time = sim_time

    def write(self, kind: Kind, **fields: Any) -> None:
        append_jsonl(
            self._path,
            {"kind": kind, "sim_time": self._sim_time(), "real_time": time.time(), **fields},
        )
