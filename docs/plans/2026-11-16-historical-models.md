# Historical model access and GPU inference

Goal: let the continuing IR laboratory obtain public Hugging Face model snapshots dated no later than its simulated instant, use local weights in scientific commands, and run real vLLM inference on physical GPU 1 while retaining the original run records.

Architecture: a host model gateway resolves repository history to a full commit, downloads and verifies a complete inference snapshot outside scientific Git, and records admission in checkpointed research evidence. Research commands see only admitted model snapshots as read-only mounts. A recorded model tool runs a fixed offline vLLM worker in the existing serving environment on GPU 1; GPU 0 continues serving the residents. No arbitrary resident code executes on the host.

## Implementation and evidence

1. `world/research_models.py`: public model search/info/download, server-controlled cutoff, pinned revision, file integrity and atomic cache publication. Reject future revisions, missing history and incomplete downloads. Tests use cleaned temporary directories and deterministic API fixtures. Consult the [HF history/download API](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api).
2. `world/research.py`, `world/research_workspace.py` and research configuration: expose the model tool in the Office, checkpoint admitted models, mount only those models, record operation provenance, and serialize GPU work with existing research commands. Test rollback, tool availability, errors and cancellation. Keep weights outside research Git and agent memory.
3. `ops/research/model_inference.py`: a fixed JSON-input worker using [vLLM offline inference](https://docs.vllm.ai/en/stable/getting_started/quickstart/). Load local snapshots only, return outputs and execution metadata, and release the process/GPU on timeout or cancellation. Reuse the existing compatible serving interpreter without changing the resident inference service or research image dependencies.
4. Remote acceptance: download a genuinely pretrained public small model with a pre-simulation commit; verify SHA/date and actual weight bytes, test rejected future revision, run nonempty vLLM generation on physical GPU 1, and verify the same snapshot loads in the resident Transformers container. Record GPU identity and GPU 0 service health. Store all probe files and receipts on Zenith outside the formal scientific run.
5. Preserve the running experiment and full live records before any stop/restore. Continue from a complete checkpoint with an explicit environment-change receipt, frozen source/config identities and a natural resident-visible service notice. Preserve old files rather than silently replacing history. Confirm four resident response streams and the newly exposed tools after resumption.
6. Update the resident guide, current design, operations guide and project log. Commit and push source before deployment; record real acceptance separately from intended behavior.

## Boundaries

Commit timestamps and current model discovery do not prove historical public availability; model provenance must say so. Initially support public ungated snapshots and installed architectures without remote Python code. A checkpoint saved by a resident in an arbitrary custom format is not automatically a vLLM-compatible model. No fixed 256 MiB browser limit applies to model weights; capacity failures must be explicit. This intervention expands available resources mid-trajectory and must not be described as an unchanged controlled experiment.
