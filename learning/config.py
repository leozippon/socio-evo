"""The configuration of the nights: what is learnt from, who chooses it, and how it is fitted.

The arms of the design are settings of `examples` and `choice`: the Social arm learns from the
moments the resident keeps, generalised; the Raw arm from the same choice, as the moments
happened; the Random arm from as many moments as the resident kept, drawn at random from its
life, generalised. With `enabled` false a run learns nothing, and the rest is unused.

The LoRA settings are the first guesses, to be tuned in a pilot on the GPUs: a small rank on every
projection the server can apply an adapter to (the full-attention, Gated DeltaNet and MLP
projections, as `learning.train` names them), a learning rate usual for LoRA, two epochs over a
dataset of at most `dataset_max` examples, each at most `max_length` tokens, which holds nine in
ten of the waking turns of the 28 days lived without learning (their median is two replies).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, NonNegativeInt, PositiveFloat, PositiveInt, model_validator

from infrastructure.config import StrictModel


class LoraConfig(StrictModel):
    """The adapter's shape and its fitting, as the trainer takes them (`learning.fit`)."""

    rank: PositiveInt = 16
    alpha: PositiveInt = 32
    dropout: float = Field(default=0.05, ge=0, lt=1)
    target_modules: tuple[str, ...] = Field(
        default=(
            *("q_proj", "k_proj", "v_proj", "o_proj"),
            *("in_proj_qkv", "in_proj_z", "out_proj"),
            *("gate_proj", "up_proj", "down_proj"),
        ),
        min_length=1,
    )
    learning_rate: PositiveFloat = 1e-4
    epochs: PositiveInt = 2
    max_length: PositiveInt = 8192
    batch_size: PositiveInt = 4
    seed: NonNegativeInt = 0


class TrainerConfig(StrictModel):
    """The trainer: the interpreter of its environment (an absolute path, `~` allowed), the base
    model's weights as it loads them, and the GPUs it is given (`CUDA_VISIBLE_DEVICES`)."""

    python: Path
    base: str = Field(min_length=1)
    gpus: str = Field(pattern=r"^\d+(,\d+)*$")

    @property
    def executable(self) -> Path:
        return self.python.expanduser()

    @model_validator(mode="after")
    def _absolute(self) -> TrainerConfig:
        if not self.executable.is_absolute():
            raise ValueError(f"trainer.python {self.python} is not an absolute path")
        return self


class LearningConfig(StrictModel):
    """Whether the residents learn at night, from what (`examples`: the moments generalised or
    as they happened), chosen how (`choice`: by the resident, or as many drawn at random), at
    most `keep_per_night` moments a night within a choice of at most `choice_steps` replies,
    the dataset of each resident the newest `dataset_max` examples it has; the adapter's
    settings and the trainer."""

    enabled: bool = False
    examples: Literal["generalised", "raw"] = "generalised"
    choice: Literal["resident", "random"] = "resident"
    keep_per_night: PositiveInt = 8
    choice_steps: PositiveInt = 24
    dataset_max: PositiveInt = 200
    lora: LoraConfig = LoraConfig()
    trainer: TrainerConfig | None = None

    @model_validator(mode="after")
    def _trainer(self) -> LearningConfig:
        if self.enabled and self.trainer is None:
            raise ValueError("learning.trainer is required when learning is enabled")
        return self
