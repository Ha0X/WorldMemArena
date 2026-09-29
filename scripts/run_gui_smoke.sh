#!/usr/bin/env bash
# One real GUI sample using the configured icodeeasy BaseModel target.
# Activate the worldmemarena conda environment before running this script.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DATASET_DIR="${DATASET_DIR:-$REPO_ROOT/.cache/worldmemarena_gui}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/exp_log/gui_icodeeasy}"
mkdir -p "$OUTPUT_DIR"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_CMD=("$PYTHON_BIN")
elif [[ "${CONDA_DEFAULT_ENV:-}" == "worldmemarena" ]]; then
  PYTHON_CMD=(python)
else
  PYTHON_CMD=(conda run -n worldmemarena python)
fi

# Check credentials without displaying them. No model calls here.
"${PYTHON_CMD[@]}" - <<'PY'
import eval_framework
from eval_framework.baselines._clients.base_model_api import target_for_baseline
from eval_framework.config import resolve_judge_api_key
target = target_for_baseline('BaseModel-icodeeasy')
if not target.api_key or not resolve_judge_api_key():
    raise SystemExit('Missing API key. Set OPENAI_API_KEY in the project .env.')
print(f'Baseline: {target.baseline_name}; model: {target.model}', flush=True)
PY

export EVAL_API_CALL_LOG="$OUTPUT_DIR/api_calls.jsonl"
export EVAL_API_LOG_BASELINE=BaseModel-icodeeasy
export EVAL_API_LOG_DOMAIN=agent/gui/excel
export EVAL_API_LOG_OUTPUT_DIR="$OUTPUT_DIR"
args=(
  --dataset "$DATASET_DIR" --dataset-type worldmemarena
  --baseline BaseModel-icodeeasy --sample-index 1
  --max-eval-workers 1 --output-dir "$OUTPUT_DIR"
)
# Optional limit for a shorter test; five sessions include the first checkpoint.
if [[ -n "${MAX_SESSIONS:-}" ]]; then
  args+=(--max-sessions "$MAX_SESSIONS")
fi
"${PYTHON_CMD[@]}" -u -m eval_framework.cli "${args[@]}" "$@" 2>&1 | tee "$OUTPUT_DIR/run.log"
