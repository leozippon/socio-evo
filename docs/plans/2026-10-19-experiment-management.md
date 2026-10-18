# Viewer experiment management

The local live viewer exposes Rename and Delete beside every experiment on the homepage, including study arms. Rename stores a display label in the experiment's `.display.json`; immutable experiment IDs, existing links, configs and manifests remain unchanged. The published index carries the label and every viewer breadcrumb and title resolves it through the shared display-name helper. Metadata changes invalidate incremental publication caches.

Deletion requires a native modal confirmation showing the experiment ID and number of seeds. Every seed must be completed, interrupted or failed. Deletion atomically moves the entire experiment to the runs root's hidden `.trash` directory, preserving recoverability without retaining published pages. It does not free disk capacity. The UI refreshes after mutations; modal errors remain visible. Static exports expose no management controls.

The live server serializes mutation and refresh publication, rejects path traversal and experiment symlinks, and only accepts JSON mutations from the localhost viewer origin with a custom header. The model experiment runs against its own immutable code directory; deploying viewer management must not restart the model experiment.
