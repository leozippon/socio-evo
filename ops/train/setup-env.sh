#!/usr/bin/env bash
# Create the training environment, or bring an existing one to exactly the pinned packages.
# Usage (from anywhere): [TRAIN_ENV=/Data2/lzp/envs/socio-evo-train] ops/train/setup-env.sh
# Running it again is harmless: `uv pip sync` installs what is missing and removes what is not pinned.
set -euo pipefail

env_dir=${TRAIN_ENV:-/Data2/lzp/envs/socio-evo-train}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# The package cache shared with the other projects on /Data2; the home disk is nearly full.
export UV_CACHE_DIR=${UV_CACHE_DIR:-/Data2/lzp/uv-cache}

if [[ ! -x $env_dir/bin/python ]]; then
  uv venv --python "$HOME/miniconda3/bin/python3.12" "$env_dir"
fi
uv pip sync --python "$env_dir/bin/python" "$here/requirements.txt"
PYTHONNOUSERSITE=1 "$env_dir/bin/python" - <<'EOF'
import fla, peft, torch, transformers
from transformers.models.qwen3_5 import modeling_qwen3_5  # noqa: F401  the served architecture
print(f"torch {torch.__version__} (CUDA {torch.version.cuda}), transformers {transformers.__version__}, "
      f"peft {peft.__version__}, fla {fla.__version__}")
EOF
echo "training environment ready: $env_dir/bin/python"
