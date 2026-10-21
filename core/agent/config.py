"""What an experiment config says about an agent: its seed and its prompt-size limits."""

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

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


class ActiveRecallConfig(StrictModel):
    """Opt-in internal recollection; never an external action or arbitrary file read."""

    enabled: bool = False
    max_queries: int = Field(default=2, ge=1, le=5)
    max_results: int = Field(default=5, ge=1, le=20)
    snippet_chars: int = Field(default=1200, ge=100, le=8000)


class ContextBudgetConfig(StrictModel):
    """Shared input budget. A local tokenizer is optional; otherwise count UTF-8 bytes.

    The byte estimate is intentionally conservative, not an exact token measurement.
    Set context_tokens to the actual server limit, including generated output.
    """

    enabled: bool = False
    context_tokens: PositiveInt = 32768
    input_tokens: PositiveInt = 24000
    output_tokens: PositiveInt = 4096
    safety_tokens: NonNegativeInt = 1024
    tokenizer_path: str | None = None

    @model_validator(mode="after")
    def _room_for_input(self) -> "ContextBudgetConfig":
        if self.context_tokens <= self.output_tokens + self.safety_tokens:
            raise ValueError("context_tokens must leave room after output and safety reserves")
        return self


class WorkNotesConfig(StrictModel):
    enabled: bool = False
    editable: bool = False
    related_notes: int = Field(default=2, ge=0, le=5)
    # Accepted for saved configurations; Work now uses the shared context budget.
    recent_entries: int = Field(default=4, ge=1, le=20)
    excerpt_chars: int = Field(default=1600, ge=200, le=8000)


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
    active_recall: ActiveRecallConfig = ActiveRecallConfig()
    context_budget: ContextBudgetConfig = ContextBudgetConfig()
    work_notes: WorkNotesConfig = WorkNotesConfig()
