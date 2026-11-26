"""The configuration of the nights: what is learnt from, who chooses it, and how it is fitted.

The arms of the design are settings of `examples` and `choice`: the Social arm learns from the
moments the resident keeps, generalised; the Raw arm from the same choice, as the moments
happened; the Random arm from as many moments as the resident kept, drawn at random from its
life, generalised. With `enabled` false a run learns nothing, and the rest is unused.

The LoRA settings are the first guesses, to be tuned in a pilot on the GPUs: a small rank on every
projection the server can apply an adapter to (the full-attention, Gated DeltaNet and MLP
projections, as `learning.train` names them), a learning rate usual for LoRA, two epochs over a
dataset of at most `dataset_max` examples. An example may run to `max_length` tokens (less the
margin `learning.generalise.LENGTH_MARGIN` keeps): the waking turns of the run of 29 October, as
they happened, ran to a median of 299 tokens, 2,723 for nine in ten and 6,713 at the longest, so
a shorter limit would drop the long ones from the Raw arm alone and the arms would differ in which
moments they learn from. One example a step (`batch_size` 1) then keeps a step within what one
GPU holds (`TrainerConfig.step_tokens`), and every arm takes as many steps as it has examples.
The arms share all of these.
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
    batch_size: PositiveInt = 1
    seed: NonNegativeInt = 0


class TrainerConfig(StrictModel):
    """The trainer: the interpreter of its environment (an absolute path, `~` allowed), the base
    model's weights as it loads them, and the GPUs a night's fit may use, as nvidia-smi numbers
    them, one trainer process on each that has room (`learning.fit`). The most tokens one step of
    a fit may hold, `batch_size` times `max_length` at the longest, is `step_tokens`: about 8,000
    on one L20 (ops/train/README.md, Memory and time).

    A GPU has room when `free_gib` of it is free. That must cover a fit's peak at its longest
    step, `max_length` tokens, with the CUDA context and what else PyTorch's count leaves out:
    40.4 GiB at 8,000 tokens and about a GiB beside it, for the default `max_length` of 8,192.
    Of the 45 GiB nvidia-smi gives an L20, other jobs may then hold less than 3 GiB. While no
    GPU has room, a night waits for one, up to `patience_minutes`, and then fails, to be resumed:
    six hours, so that a night waits out another job that takes the GPUs for an evening, and a
    run whose GPUs stay taken stops within the day, saying why."""

    python: Path
    base: str = Field(min_length=1)
    gpus: str = Field(pattern=r"^\d+(,\d+)*$")
    step_tokens: PositiveInt = 8192
    free_gib: PositiveFloat = 42.0
    patience_minutes: NonNegativeInt = 360

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
    dataset_max: PositiveInt = 256
    lora: LoraConfig = LoraConfig()
    trainer: TrainerConfig | None = None

    @model_validator(mode="after")
    def _trainer(self) -> LearningConfig:
        if self.enabled and self.trainer is None:
            raise ValueError("learning.trainer is required when learning is enabled")
        lora, trainer = self.lora, self.trainer
        if trainer is not None and lora.batch_size * lora.max_length > trainer.step_tokens:
            raise ValueError(
                f"learning.lora.batch_size {lora.batch_size} times max_length {lora.max_length} "
                f"is more than the {trainer.step_tokens} tokens a step may hold "
                "(learning.trainer.step_tokens)"
            )
        return self
