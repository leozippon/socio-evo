"""Real-time forms: direct speech, no read action and no declared work/chat duration."""

from core.interaction.actions import Activity
from core.interaction.activity_card import (
    CLOCK,
    SHORT,
    activity_forms,
    confirmed_wait_forms,
    invitation_responses,
    open_chat_forms,
    tool,
)
from core.interaction.card import _Form, _one_of


def realtime_forms(layer, menu):
    if layer == "tool":
        return activity_forms(layer, menu)
    result = [
        _Form(
            "rest",
            {
                "until": (CLOCK, None),
                "wake for invitations": (
                    bool,
                    "Allow nearby public-chat opportunities and invitations "
                    "to wake you to choose; "
                    "this never joins automatically. Prefer true while waiting; false means "
                    "deliberately undisturbed rest.",
                ),
            },
            lambda r: Activity(
                operation="select_rest",
                arguments={"until": r["until"], "wake": r["wake for invitations"]},
            ),
        ),
        _Form(
            "work",
            {"public": (bool, None), "mode": (_one_of(["parallel", "relay"]), None)},
            lambda r: Activity(
                operation="select_work", arguments={"public": r["public"], "mode": r["mode"]}
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
                {"work": (_one_of(menu["work"]), None)},
                lambda r: Activity(operation="resume_work", target=r["work"]),
            )
        )
    if menu.get("conversations"):
        result.append(
            _Form(
                "join conversation",
                {"conversation": (_one_of(menu["conversations"]), None)},
                lambda r: Activity(operation="select_conversation", target=r["conversation"]),
            )
        )
    result.extend(open_chat_forms(menu))
    if menu.get("people") and menu.get("places"):
        result.append(realtime_invitation(menu, "arrange a conversation"))
    result.extend(invitation_responses(menu))
    result.extend(confirmed_wait_forms(menu))
    result.append(tool("help", "help"))
    return result


def realtime_invitation(menu, label="invite people"):
    from typing import Annotated

    from pydantic import Field

    return tool(
        label,
        "invite",
        {
            "people": (Annotated[list[_one_of(menu["people"])], Field(min_length=1)], None),
            "place": (_one_of(menu["places"]), None),
            "at": (CLOCK | None, "Use null for now; otherwise arrange a meeting today."),
            "topic": (SHORT, None),
            "public": (bool, None),
        },
    )
