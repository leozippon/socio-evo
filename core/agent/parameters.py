"""The agent's parameters: its self-authored policy (L2) and its model specification (L3)."""

from pathlib import Path

from pydantic import field_validator

from infrastructure.config import StrictModel, load_config
from infrastructure.llm import Sampling


class ModelSpec(StrictModel):
    """The model behind an agent. `model` overrides the client's default model when set.

    `adapter` will name a fine-tuned adapter, the target of L3. L3 is not implemented, so any
    value other than null is rejected.
    """

    model: str | None = None
    sampling: Sampling = Sampling()
    adapter: str | None = None

    @field_validator("adapter")
    @classmethod
    def _no_adapter_before_l3(cls, adapter: str | None) -> str | None:
        if adapter is not None:
            raise ValueError("adapters belong to L3 (parameter evolution), not implemented yet")
        return adapter


class Parameters:
    """`parameters/` of an agent directory: `policy.md` and `model.yaml`."""

    def __init__(self, root: Path) -> None:
        self.policy_path = root / "policy.md"
        self.model_path = root / "model.yaml"

    def read_policy(self) -> str:
        return self.policy_path.read_text(encoding="utf-8").strip()

    def write_policy(self, text: str) -> None:
        self.policy_path.write_text(text.strip() + "\n", encoding="utf-8")

    def read_model(self) -> ModelSpec:
        return load_config(self.model_path, ModelSpec)
