#!/bin/bash
# /app/train.sh — fake-trainer entrypoint.
# Contract (PIPELINE_DEVELOP.md §3.4): write checkpoint files directly to
# <output_dir>. The fake stage writes a stub blob so eval can read it back.
set -euo pipefail

DATASET_DIR="$1"
MODEL_CONFIG_DIR="$2"
OUTPUT_DIR="$3"
MAX_STEPS="$4"

if [[ -z "${RUN_CONFIG:-}" ]]; then
    echo "ERROR: RUN_CONFIG env var not set"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
# Unconditional 20s sleep so test_cancel_cascades has a deterministic
# window in which to observe train running and cancel it before it
# completes. Cost on the cancel-unaware tests: +20s on test_train_eval_chain.
sleep 20
dd if=/dev/zero of="$OUTPUT_DIR/checkpoint.bin" bs=1024 count=1 status=none
cat > "$OUTPUT_DIR/info.json" <<EOF
{
  "dataset": "$DATASET_DIR",
  "model_config": "$MODEL_CONFIG_DIR",
  "max_steps": $MAX_STEPS
}
EOF
echo "fake-trainer: wrote $OUTPUT_DIR/checkpoint.bin"
