# Active Recall and Context Budget Implementation Plan

Goal: add bounded, private active recall before external action and a shared input budget.
Architecture: preserve the existing automatic retriever. Extend the decision reply with an
internal recollection request, search only the current agent's persisted memory, and rebuild
context before asking again. A priority packer allocates space to current situation and
observed evidence before old memories. Guard every enabled agent call, including retries.
Tech stack: Python, Pydantic, existing OpenAI-compatible client; optional local HF tokenizer.

1. Add validated opt-in cognition settings (old experiments retain their original behavior).
2. Implement bounded lexical search of own experiences, diaries, insights and skill notes;
   return timestamped/source-labelled chunks, reject symlink escapes and future records.
3. Implement token accounting (local tokenizer, or explicitly labelled conservative UTF-8
   byte estimate), output/safety reserves, priority packing and retry guard.
4. Integrate recall/action choice without dispatching recall to the environment; cap queries,
   deduplicate results, record audit metadata, and force normal action at the cap.
5. Test privacy, long documents, repeated/empty queries, action validation, output reservation,
   retry overflow, priority retention, and disabled-mode compatibility.
6. Add an opt-in SWE-bench configuration and document use and limitations. Run targeted
   regressions locally. Do not alter the currently running remote experiment.

Design choices: no extra mandatory planning call; recall is an alternative to acting. No
model-generated summaries of evidence (avoid invented facts); snippets retain provenance.
Mandatory context too large fails explicitly rather than silently dropping task instructions.
Local tokenizer loading never downloads files or executes remote code. Byte accounting is
conservative for byte-level tokenizers but is not claimed to be exact model tokenization.
