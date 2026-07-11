#!/bin/bash
# install_topology_watcher.sh — Keep the HyperPod Slurm 25.11 topology config
# from re-breaking the controller after the cluster agent regenerates
# slurm.conf.
#
# Runs on the CONTROLLER node only.
#
# The SageMaker cluster agent owns /opt/slurm/etc/slurm.conf and regenerates it
# (observed: it reverts our edits, restoring the empty topology.yaml/topology.conf
# and the `Topology=tree` PartitionName tag). start_slurm.sh sanitizes it before
# slurmctld's first start (initial provision); this script covers every later
# regeneration by re-applying sanitize_slurm_topology whenever slurm.conf changes.
#
# Installs two systemd units (same pattern as register_slurm_features.sh):
#
#   sanitize-slurm-topology.service (oneshot)
#     - Re-runs sanitize_slurm_topology; if it changed anything, runs
#       `scontrol reconfigure`. Sanitize BEFORE reconfigure so the running
#       controller only ever reloads the cleaned config, never the raw
#       regenerated one (which we know it crashes on).
#
#   sanitize-slurm-topology.path
#     - Watches /opt/slurm/etc/slurm.conf and triggers the .service on every
#       modification — i.e. every time the cluster agent rewrites it.
#
# Usage: install_topology_watcher.sh
set -exo pipefail
# shellcheck source=_lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
require_node_type controller

SCRIPT_PATH="/usr/local/sbin/sanitize-slurm-topology"
SERVICE_PATH="/etc/systemd/system/sanitize-slurm-topology.service"
PATH_UNIT_PATH="/etc/systemd/system/sanitize-slurm-topology.path"
SLURM_CONF_WATCH="${SLURM_DIR:-/opt/slurm}/etc/slurm.conf"

# The runtime script sources _lib.sh for sanitize_slurm_topology. It must NOT
# source it from the lifecycle staging dir: SageMaker unpacks lifecycle scripts
# under an ephemeral /tmp/<...>/lifecycle/<hash>/ path that is cleared on reboot
# (and changes each lifecycle run), so a runtime script that sourced from there
# would break after a controller reboot — exactly when a fresh slurmctld start
# would re-hit the crash. Copy _lib.sh to a persistent path and source that.
PERSIST_LIB="/usr/local/lib/physai/_lib.sh"
STAGING_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"
mkdir -p "$(dirname "$PERSIST_LIB")"
cp "$STAGING_LIB" "$PERSIST_LIB"

# The runtime script sources the persistent _lib.sh (for sanitize_slurm_topology)
# and, if the fix changed anything, reconfigures. It resolves SLURM_DIR the same
# way the orchestrator does — prefer /opt/slurm — so it edits the active install.
cat > "$SCRIPT_PATH" << SCRIPT_EOF
#!/bin/bash
# Re-apply the HyperPod 25.11 topology workaround after the cluster agent
# regenerates slurm.conf. Installed by install_topology_watcher.sh.
set -eo pipefail
if [ -e /opt/slurm ]; then
    SLURM_DIR="\$(readlink -f /opt/slurm)"
fi
export SLURM_DIR="\${SLURM_DIR:-/opt/slurm}"
# shellcheck source=/dev/null
. "$PERSIST_LIB"
if sanitize_slurm_topology; then
    echo "sanitize-slurm-topology: config changed, reconfiguring slurmctld"
    slurm_reconfigure_with_retry || echo "WARNING: reconfigure failed; see journal" >&2
else
    echo "sanitize-slurm-topology: nothing to change"
fi
SCRIPT_EOF
chmod 0755 "$SCRIPT_PATH"

# .service — oneshot. RemainAfterExit is NOT set: the .path unit only
# re-triggers a service that is inactive when the next path event fires (same
# reasoning as register_slurm_features.sh).
cat > "$SERVICE_PATH" << EOF
[Unit]
Description=Re-apply HyperPod Slurm 25.11 topology workaround on slurm.conf change
After=slurmctld.service

[Service]
Type=oneshot
ExecStart=$SCRIPT_PATH

[Install]
WantedBy=multi-user.target
EOF

# .path — fire on every write+close to slurm.conf (what the cluster agent does
# when it regenerates the config).
cat > "$PATH_UNIT_PATH" << EOF
[Unit]
Description=Watch slurm.conf and re-apply the topology workaround on change

[Path]
PathModified=$SLURM_CONF_WATCH

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
# enable (idempotent) then restart to pick up any updated unit/script content
# on re-runs of this lifecycle script.
systemctl enable sanitize-slurm-topology.path sanitize-slurm-topology.service
systemctl restart sanitize-slurm-topology.path

if systemctl is-active --quiet sanitize-slurm-topology.path; then
    echo "sanitize-slurm-topology.path is active (watching $SLURM_CONF_WATCH)"
else
    echo "WARNING: sanitize-slurm-topology.path not active; check journalctl -u sanitize-slurm-topology.path" >&2
fi
