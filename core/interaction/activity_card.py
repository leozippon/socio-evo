"""Reply forms for selecting activities and using their bounded tools."""

from typing import Annotated, Literal

from pydantic import Field

from core.interaction.actions import Activity
from core.interaction.card import _Form, _one_of

SHORT = Annotated[str, Field(min_length=1, max_length=2000)]
TEXT = Annotated[str, Field(min_length=1, max_length=16000)]
MINUTES = Annotated[int, Field(ge=1, le=240)]
CLOCK = Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$")]


def tool(label, name, fields=None):
    fields = fields or {}
    return _Form(
        label,
        fields,
        lambda r: Activity(
            operation="activity_tool",
            tool=name,
            arguments={k: r[k] for k in fields},
        ),
    )


def invitation_form(label="invite people", name="invite", menu=None):
    menu = menu or {}
    if menu.get("realtime"):
        from core.interaction.realtime_card import realtime_invitation

        return realtime_invitation(menu, label)
    return tool(
        label,
        name,
        {
            "people": (Annotated[list[_one_of(menu["people"])], Field(min_length=1)], None),
            "place": (_one_of(menu["places"]), None),
            "at": (CLOCK | None, "Use null for now; otherwise arrange a meeting today."),
            "minutes": (MINUTES, None),
            "topic": (SHORT, None),
            "public": (bool, None),
        },
    )


def activity_forms(layer, menu):
    if layer == "selection" and menu.get("realtime"):
        from core.interaction.realtime_card import realtime_forms

        return realtime_forms(layer, menu)
    if layer == "selection":
        result = [
            _Form(
                "rest",
                {"until": (CLOCK, None), "wake for invitations": (bool, None)},
                lambda r: Activity(
                    operation="select_rest",
                    arguments={"until": r["until"], "wake": r["wake for invitations"]},
                ),
            ),
            _Form(
                "work",
                {
                    "minutes": (MINUTES, None),
                    "public": (bool, None),
                    "mode": (Literal["parallel", "relay"], None),
                },
                lambda r: Activity(
                    operation="select_work",
                    seconds=r["minutes"] * 60,
                    arguments={"public": r["public"], "mode": r["mode"]},
                ),
            ),
        ]
        if menu.get("outside"):
            result = result[:1]  # Waiting/movement, never indoor work before admission.
        if menu.get("moves"):
            result.append(
                _Form(
                    "move",
                    {"to": (_one_of(menu["moves"]), None)},
                    lambda r: Activity(operation="select_move", target=menu["moves"][r["to"]]),
                )
            )
        if menu.get("work"):
            result.append(
                _Form(
                    "join or resume work",
                    {"work": (_one_of(menu["work"]), None), "minutes": (MINUTES, None)},
                    lambda r: Activity(
                        operation="resume_work", target=r["work"], seconds=r["minutes"] * 60
                    ),
                )
            )
        if menu.get("conversations"):
            result.append(
                _Form(
                    "join conversation",
                    {
                        "conversation": (_one_of(menu["conversations"]), None),
                        "minutes": (MINUTES, None),
                    },
                    lambda r: Activity(
                        operation="select_conversation",
                        target=r["conversation"],
                        seconds=r["minutes"] * 60,
                    ),
                )
            )
        if menu.get("people") and menu.get("places"):
            result.append(invitation_form("arrange a conversation", menu=menu))
        if menu.get("invitations"):
            for name in ("accept", "decline"):
                result.append(
                    tool(
                        name + " invitation",
                        name,
                        {"invitation": (_one_of(menu["invitations"]), None)},
                    )
                )
        return result
    tools = set(menu["tools"])
    result = [tool("pause or leave", "leave")]
    definitions = {
        "read": tool("read new messages", "read"),
        "invite_here": tool(
            "invite to this conversation",
            "invite_here",
            {"people": (Annotated[list[_one_of(menu["people"])], Field(min_length=1)], None)},
        ),
        "reply": tool("reply", "reply", {"text": (TEXT, None)}),
        "wait": tool(
            "wait for messages", "wait", {"seconds": (Annotated[int, Field(ge=1, le=86400)], None)}
        ),
        "board": tool("view the notice board", "board"),
        "feedback": tool("read work feedback", "feedback"),
        "read_code": tool(
            "read code",
            "read_code",
            {
                "path": (SHORT, None),
                "line": (Annotated[int, Field(ge=1)], None),
                "lines": (Annotated[int, Field(ge=1, le=menu.get("max_read_lines", 400))], None),
            },
        ),
        "search": tool("search code", "search", {"path": (SHORT, None), "pattern": (SHORT, None)}),
        "diff": tool("inspect your changes", "diff"),
        "edit": tool("apply a code patch", "edit", {"patch": (TEXT, None)}),
        "command": tool("run a command", "command", {"command": (TEXT, None)}),
        "test": tool("run local tests", "test", {"command": (TEXT, None)}),
        "submit": tool("submit your repair", "submit", {"report": (TEXT, None)}),
    }
    result.extend(form for name, form in definitions.items() if name in tools)
    if "claim" in tools and menu.get("jobs"):
        result.append(
            tool(
                "take a job",
                "claim",
                {
                    "job": (_one_of(menu["jobs"]), None),
                    "partner": (
                        (_one_of(menu["people"]) | None) if menu.get("people") else type(None),
                        None,
                    ),
                },
            )
        )
    if "handoff" in tools and menu.get("partners"):
        result.append(
            tool(
                "offer code handoff",
                "handoff",
                {"to": (_one_of(menu["partners"]), None), "description": (TEXT, None)},
            )
        )
    if menu.get("handoffs"):
        for name in ("apply_handoff", "decline_handoff"):
            if name in tools:
                result.append(
                    tool(
                        "apply code handoff" if name == "apply_handoff" else "decline code handoff",
                        name,
                        {"handoff": (_one_of(menu["handoffs"]), None)},
                    )
                )
    if "invite" in tools and menu.get("people") and menu.get("places"):
        result.append(invitation_form(menu=menu))
    if menu.get("invitations"):
        for name in ("accept", "decline"):
            if name in tools:
                result.append(
                    tool(
                        name + " invitation",
                        name,
                        {"invitation": (_one_of(menu["invitations"]), None)},
                    )
                )
    return result
