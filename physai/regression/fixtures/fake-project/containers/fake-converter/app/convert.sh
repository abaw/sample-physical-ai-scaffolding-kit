#!/bin/bash
# /app/convert.sh — fake-converter entrypoint.
# Contract (from PIPELINE_DEVELOP.md §3.4): read source files from <input_dir>
# and write a dataset to <output_dir>. The fake stage just acknowledges its
# inputs and writes a sentinel file so downstream stages can verify it ran.
set -euo pipefail

INPUT_DIR="$1"
OUTPUT_DIR="$2"

if [[ -z "${RUN_CONFIG:-}" ]]; then
    echo "ERROR: RUN_CONFIG env var not set"
    exit 1
fi

if ! mkdir "$OUTPUT_DIR" 2>/dev/null; then
    echo "ERROR: $OUTPUT_DIR already exists"
    exit 1
fi

# Sentinel files: enough for the regression checks to verify the stage ran.
echo "fake-converter ran" > "$OUTPUT_DIR/info.json"
echo "input=$INPUT_DIR" >> "$OUTPUT_DIR/info.json"
ls "$INPUT_DIR" > "$OUTPUT_DIR/input.listing"
echo "fake-converter: wrote $OUTPUT_DIR"
