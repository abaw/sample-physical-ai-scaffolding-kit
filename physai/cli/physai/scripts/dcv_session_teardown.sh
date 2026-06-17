#!/bin/bash
# dcv_session_teardown.sh — Invalidate the per-job DCV connection.
# Called from the sbatch EXIT/TERM trap when --visual is set.
#
# The "console" session itself is permanent (created at boot by dcvserver);
# we only rotate ubuntu's PAM password to a random unguessable value so the
# previous job's URL no longer authenticates.
#
# NOT passwd -l — that would lock the account and break SSH login for
# subsequent operations.
#
# Inputs:
#   $1 — SLURM_JOB_ID (used in the completion-sentinel line so a regression
#        check can confirm the trap fired and this script ran to completion).
set -euo pipefail

JOBID="${1:-?}"

if ! echo "ubuntu:$(openssl rand -base64 32)" | sudo chpasswd; then
    echo "dcv-teardown: chpasswd failed for job ${JOBID}" >&2
    exit 1
fi
echo "dcv-teardown: completed for job ${JOBID}"
