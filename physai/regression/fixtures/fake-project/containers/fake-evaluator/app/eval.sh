#!/bin/bash
# /app/eval.sh — fake-evaluator entrypoint.
# Contract (PIPELINE_DEVELOP.md §3.4): write metrics.json with at least
# eval_rounds, success_rate, checkpoint. --visual is accepted and
# recorded in metrics.json but not acted on — this fake doesn't render.
set -euo pipefail

CHECKPOINT_DIR="$1"
MODEL_CONFIG_DIR="$2"
OUTPUT_DIR="$3"
ROUNDS="$4"
VISUAL_FLAG="${5:-}"

if [[ -z "${RUN_CONFIG:-}" ]]; then
    echo "ERROR: RUN_CONFIG env var not set"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

if [[ ! -f "$CHECKPOINT_DIR/checkpoint.bin" ]]; then
    echo "ERROR: expected $CHECKPOINT_DIR/checkpoint.bin from fake-trainer"
    exit 1
fi

cat > "$OUTPUT_DIR/metrics.json" <<EOF
{
  "eval_rounds": $ROUNDS,
  "success_rate": 0.0,
  "checkpoint": "$CHECKPOINT_DIR",
  "visual": "${VISUAL_FLAG}",
  "model_config": "$MODEL_CONFIG_DIR"
}
EOF
echo "fake-evaluator: wrote $OUTPUT_DIR/metrics.json"
