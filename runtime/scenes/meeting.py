"""Meetings: the usual conversation on a question the clerk puts, then everyone's answer."""

import random
from collections.abc import Mapping, Sequence

from core.environment import Environment
from core.interaction import Allowance, Decision, MayPass, MayVote, Vote
from runtime.scenes import situations
from runtime.scenes.conversation import Conversation


class Meeting(Conversation):
    """A meeting at a social place on `question`, to be answered with one of `options`: those
    present hold the usual conversation (none with fewer than two), and at the turn after it
    ends each one still present is asked, privately, for its answer, or may give none.
    `voters` are those asked and `votes` the answer of each who gave one."""

    kind = "meeting"

    def __init__(
        self,
        env: Environment,
        id: str,
        place: str,
        participants: Sequence[str],
        *,
        start: int,
        step: int,
        max_turns: int,
        until: int,
        rng: random.Random,
        question: str,
        options: Sequence[str],
    ) -> None:
        super().__init__(
            env,
            id,
            place,
            participants,
            start=start,
            step=step,
            max_turns=max_turns,
            until=until,
            rng=rng,
        )
        self.question = question
        self.options = tuple(options)
        self.voters: list[str] | None = None if len(self.present) > 1 else list(self.present)
        self.votes: dict[str, str] = {}

    def ask(self) -> list[str]:
        return list(self.voters) if self.voters is not None else super().ask()

    def allowed(self, agent: str) -> tuple[Allowance, ...]:
        if self.voters is None:
            return super().allowed(agent)
        return (MayVote(options=self.options), MayPass())

    def situation(self, agent: str) -> str:
        if self.voters is None:
            return super().situation(agent)
        return situations.answers(self.env, self.place, self.question, self.options)

    async def carry_out(self, agent: str, decision: Decision, time: int) -> None:
        if self.voters is None:
            await super().carry_out(agent, decision, time)
            return
        action = decision.action
        if isinstance(action, Vote):
            if action.choice not in self.options:
                raise ValueError(f"{agent} answered {action.choice!r}, not one of {self.options}")
            self.votes[agent] = action.choice
        await self.env.execute(agent, action, time=time, scene=self.id, witnesses=[agent])

    def lapsed(self, agent: str) -> None:
        if self.voters is None:
            super().lapsed(agent)

    def over(self, decisions: Mapping[str, Decision]) -> bool:
        """Over once the answers are in; when the conversation ends, the answers are asked for
        at the next turn of those still present, if anyone is."""
        if self.voters is not None:
            return True
        if not super().over(decisions):
            return False
        self.voters = list(self.present)
        return not self.voters

    def carried(self) -> str | None:
        """The answer given by more than half of those asked, if one was."""
        return next(
            (option for option in self.options if 2 * self.count(option) > len(self.voters or ())),
            None,
        )

    def count(self, option: str) -> int:
        return sum(choice == option for choice in self.votes.values())
