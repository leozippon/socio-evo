# External references

These repositories are design references, not dependencies: nothing here is imported or vendored, and our code carries no requirement on them.
To read one locally, clone it into `external_references/<name>/`; those checkouts are git-ignored.

| Repository | What it is | What we borrow | Where it lands |
| --- | --- | --- | --- |
| [AgentScope](https://github.com/agentscope-ai/agentscope) | Multi-agent framework for building LLM agents | Agent runtime, state handling and tool-use structure | `core/agent` |
| [AgentEvolver](https://github.com/modelscope/AgentEvolver) | Self-improving agent training framework (task generation, experience-guided exploration, credit assignment) | Self-evolution loop and attributing outcomes to steps | `core/agent/evolution`, reflection credit assignment in L0 |
| [Mesa](https://github.com/mesa/mesa) | Python agent-based modelling library | Separating environment state from agents, and stepped simulation | `core/environment`, `runtime/simulation` |
| [Concordia](https://github.com/google-deepmind/concordia) | Generative social simulation library from Google DeepMind | Scenes and events as the unit of social simulation, with a game-master-style arbiter of what happens | `runtime/scenes`, `core/interaction` |
| [SOTOPIA](https://github.com/sotopia-lab/sotopia) | Open-ended social learning environment for evaluating social intelligence of language models | Goal-driven social interaction scenarios and ways to score social behaviour | `evaluation/`, `runtime/scenes` |
| [Harbor](https://github.com/harbor-framework/harbor) | Framework for running agents on sandboxed task environments | Containerised coding tasks with checkable results | `tasks/` |
| [AI Town](https://github.com/a16z-infra/ai-town) | Starter kit for virtual worlds of interacting AI characters, after generative agents | Town map and character view for replaying a run | `frontend/` |
| [LangMem](https://github.com/langchain-ai/langmem) | Long-term memory tools for agents that learn from interactions | Extracting and consolidating memories over time | `core/agent/memory` |
| [GEPA](https://github.com/gepa-ai/gepa) | Reflective prompt evolution optimizer | Evolving text instructions from reflection on outcomes | `core/agent/evolution` (L2 policy) |
| [TRL](https://github.com/huggingface/trl) | Hugging Face library for post-training models (SFT, preference optimization, RL) | Fine-tuning recipes for adapters trained on own experience | `core/agent/evolution` (L3 parameters, not yet implemented) |

TRL matters only for L3, which has no operator yet, so nothing in the current code follows it.
GEPA informs L2 as an idea, but the current L2 operator is a plain reflective rewrite of the policy and does not use GEPA's search or selection.
