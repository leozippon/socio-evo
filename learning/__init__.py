"""Learning at night: every resident learns into its own LoRA adapter from the moments of its own
life it chooses to keep.

One module for each step: `moments` cuts a life into moments from the resident's trace and
session; `choice` is the resident's choice of what to keep; `generalise` makes an example of each
moment kept, generalised or as it happened; `dataset` gathers each resident's examples; `fit` runs
the trainer (`learning.train`, the fit itself); `adapters` says where the adapters are and which a
resident runs on; `night` takes a night through these steps and switches the residents to their
new adapters. `config` holds the settings and `texts` every fixed text of the night.
"""
