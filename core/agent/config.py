"""What an experiment config says about an agent: its seed and its prompt-size limits."""

from pydantic import Field, NonNegativeInt, PositiveInt

from core.agent.parameters import ModelSpec
from infrastructure.config import StrictModel


class Profile(StrictModel):
    """The identity seed; it never evolves. `name` is the agent id, its public given name,
    and must be a single word because it is used verbatim in texts and directory names.

    The resident reads "You are {name}. You are {age} years old." followed by `backstory`, so
    the backstory tells the resident its own life: in the second person ("You grew up in a
    port city ..."), past tense for the past and present tense for now, in the town's own
    words (`docs/IMMERSION.md`), describing circumstances only. It says what the resident
    does for a living and where it lives, because `occupation` is a label for people reading
    the run and is not shown to the resident.
    """

    name: str = Field(pattern=r"^\w+$")
    age: PositiveInt
    occupation: str
    backstory: str


class AgentSeed(StrictModel):
    """Everything needed to create an agent. The initial policy is empty unless given."""

    profile: Profile
    policy: str = ""
    model: ModelSpec = ModelSpec()


class CognitionConfig(StrictModel):
    """Bounds on what goes into one prompt: how many memories and how long each text may be.

    At a decision the prompt holds the `recent_records` latest episodic records, up to
    `relevant_records` older ones chosen by relevance, up to `insights` insights, and the full
    text of up to `skills` skill notes (the others by name and description only). A skill or
    policy review reads at most the `diaries` latest diary entries. Each record or insight is
    clipped to `record_chars` characters; each diary entry, skill note and the policy to
    `text_chars`.
    """

    recent_records: PositiveInt = 12
    relevant_records: NonNegativeInt = 8
    insights: NonNegativeInt = 12
    skills: NonNegativeInt = 3
    diaries: PositiveInt = 30
    record_chars: PositiveInt = 600
    text_chars: PositiveInt = 4000
