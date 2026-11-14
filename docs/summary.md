# Current design

The current experiment is one four-person artificial intelligence laboratory: Mei teaches, and Aisha, Ravi and Kofi are students. They retain private memories, persistent conversations, personalities, bodies, sleep, housing and money. Shops, meals and healthcare come from fixed-price external services; there are no agent merchants, cooks, doctors or mayor.

The first seven complete simulated days are ordinary life. Residents know their backgrounds and daily facilities, but receive no advance commission, paper deadline, review rubric or research reward. At 07:00 on day 8, a common announcement opens the Office research facilities and asks them to discuss and choose an AI research question together. The proposal is reviewed at the end of day 8; an initial manuscript is reviewed at the end of day 28.

The resident model is a local Qwen3.8-27B-FP8 service assigned to host GPU 0. Research commands use a separate CUDA/PyTorch container on host GPU 1. Shared study files and execution evidence are versioned; installed dependencies and model caches persist separately. Tavily and curl are available at the Office after the announcement. Semantic Scholar is disabled.

An independent external `gpt-6.1-sol` judge scores significance, rigor, evidence and reproducibility. AI relevance is part of its scientific assessment. Each score determines a collective grant divided equally among the four residents; a one-off living allowance supports the initial period. Reviews, grants and the announced commission follow checkpoint restoration. Missing deliverables receive zero; judge failures stop without a payout.

The laboratory is running; scientific results remain to be assessed. The [research protocol](research.md) defines the hypothesis, funding and evidence limits; the [operations guide](../ops/research/README.md) records deployment status and launch procedures. The completed town/academy pair remains preserved as a separate historical experiment, described in the [original plan](plans/2026-11-13-autoresearch-town-academy.md) and [completion record](logbook/PROJECT_LOG_2026-11-14). Its results cannot establish the outcome of this changed model and schedule.
