#!/bin/bash
# Start Slurm daemons based on node type.
# Usage: start_slurm.sh <controller_ips>
#   controller_ips: comma-separated controller IP addresses
set -ex
# shellcheck source=_lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
require_node_type controller compute login

CONTROLLER_IPS="${1:?Usage: start_slurm.sh <controller_ips>}"

if [[ "$NODE_TYPE" == "controller" ]]; then
  # Sanitize the HyperPod Slurm 25.11 topology config BEFORE slurmctld's first
  # start, so it starts cleanly instead of crash-looping on the generated config
  # (see sanitize_slurm_topology in _lib.sh). At initial provision no scontrol
  # reconfigure precedes this start, so a one-shot edit is sufficient here; the
  # .path watcher (install_topology_watcher.sh) covers later agent
  # regenerations. No-op when real topology is present or the config is clean.
  sanitize_slurm_topology || true

  echo "Starting slurmctld (controller)..."
  systemctl enable --now slurmctld
  # Prevent slurmd from running on controller
  mv /etc/systemd/system/slurmd{,_disabled}.service 2>/dev/null || true

else
  # Compute or login node — both run slurmd.
  echo "Starting slurmd ($NODE_TYPE)..."
  # Point slurmd at the controller for config
  SLURMD_OPTIONS="--conf-server $CONTROLLER_IPS" envsubst < /etc/systemd/system/slurmd.service > /tmp/slurmd.service
  mv /tmp/slurmd.service /etc/systemd/system/slurmd.service
  systemctl daemon-reload
  systemctl enable --now slurmd
  # Prevent slurmctld from running on non-controller
  mv /etc/systemd/system/slurmctld{,_disabled}.service 2>/dev/null || true
fi

echo "Slurm started for $NODE_TYPE"
