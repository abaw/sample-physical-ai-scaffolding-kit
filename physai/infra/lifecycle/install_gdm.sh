#!/bin/bash
# install_gdm.sh — Install GNOME/GDM3 with auto-login on GPU worker nodes.
# DCV console sessions need a real graphical login session to attach to.
# GDM3 boots Xorg (with the NVIDIA driver) under ubuntu's PAM session, and
# dcvsessionlauncher hooks dcvagent into that session at start-up.
#
# Pins xserver-xorg-video-nvidia to match the kernel module version (HyperPod
# AMI ships a specific NVIDIA driver; mismatched userspace fails Xorg startup).
set -e
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
require_node_type compute

# Skip non-GPU compute nodes.
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "nvidia-smi not present — not a GPU node, skipping GDM install"
    exit 0
fi

DRIVER_VERSION=$(grep "NVRM version" /proc/driver/nvidia/version | grep -oP '\d+\.\d+\.\d+' | head -1)
if [[ -z "$DRIVER_VERSION" ]]; then
  echo "WARNING: Could not detect NVIDIA driver version, skipping GDM install"
  exit 0
fi
echo "NVIDIA kernel module version: $DRIVER_VERSION"
MAJOR=$(echo "$DRIVER_VERSION" | cut -d. -f1)
V="${DRIVER_VERSION}-1ubuntu1"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# GNOME desktop + GDM3 + matching NVIDIA Xorg driver.
apt-get install -y -qq --allow-downgrades --no-install-recommends \
  ubuntu-desktop-minimal \
  gdm3 \
  "xserver-xorg-video-nvidia-${MAJOR}=${V}" \
  "nvidia-persistenced=${V}" \
  "libnvidia-cfg1-${MAJOR}=${V}" \
  "libnvidia-common-${MAJOR}=${V}" \
  "libnvidia-compute-${MAJOR}=${V}" \
  "libnvidia-decode-${MAJOR}=${V}" \
  "libnvidia-gl-${MAJOR}=${V}" \
  "libnvidia-gpucomp-${MAJOR}=${V}"

# NVIDIA Xorg modules live under /usr/lib/x86_64-linux-gnu/nvidia/xorg/ on
# Ubuntu; OutputClass in /usr/share/X11/xorg.conf.d/10-nvidia.conf normally
# picks them up, but symlink anyway as belt-and-braces for environments where
# the OutputClass file is missing.
mkdir -p /usr/lib/xorg/modules/drivers /usr/lib/xorg/modules/extensions
ln -sf /usr/lib/x86_64-linux-gnu/nvidia/xorg/nvidia_drv.so \
       /usr/lib/xorg/modules/drivers/nvidia_drv.so
ln -sf /usr/lib/x86_64-linux-gnu/nvidia/xorg/libglxserver_nvidia.so \
       /usr/lib/xorg/modules/extensions/libglxserver_nvidia.so

systemctl enable --now nvidia-persistenced

# Generate xorg.conf via nvidia-xconfig — the supported recipe for headless
# data-center GPUs (a virtual DFP display head instead of a physical monitor)
# per AWS DCV TAM runbook. --preserve-busid pins the BusID to the detected
# GPU so the driver binds correctly across reboots.
nvidia-xconfig \
  --preserve-busid \
  --enable-all-gpus \
  --connected-monitor=DFP-0

# Auto-login ubuntu so GDM brings up Xorg + a graphical session at boot,
# without a human at the (non-existent) console. dcvsessionlauncher hooks
# dcvagent into that session for frame capture.
mkdir -p /etc/gdm3
cat > /etc/gdm3/custom.conf << 'EOF'
[daemon]
WaylandEnable = false
AutomaticLoginEnable = true
AutomaticLogin = ubuntu

[security]

[xdmcp]

[chooser]

[debug]
EOF

# Disable GNOME screen lock and idle blanking system-wide. Without this the
# auto-logged-in ubuntu desktop locks itself after a few minutes of no input
# and DCV viewers get stuck on the lock screen — there is no human at the
# console to type ubuntu's PAM password (which is the per-job OTP, already
# rotated out by then anyway).
mkdir -p /etc/dconf/db/local.d /etc/dconf/profile
cat > /etc/dconf/profile/user << 'EOF'
user-db:user
system-db:local
EOF
cat > /etc/dconf/db/local.d/00-physai-no-lock << 'EOF'
[org/gnome/desktop/screensaver]
lock-enabled=false
idle-activation-enabled=false

[org/gnome/desktop/session]
idle-delay=uint32 0

[org/gnome/settings-daemon/plugins/power]
sleep-inactive-ac-type='nothing'
sleep-inactive-battery-type='nothing'
EOF
dconf update

# Tear down the obsolete raw-Xorg unit if we're upgrading from a node that
# was previously bootstrapped with install_xorg.sh.
if [[ -f /etc/systemd/system/xorg.service ]]; then
    systemctl disable --now xorg.service 2>/dev/null || true
    rm -f /etc/systemd/system/xorg.service
    systemctl daemon-reload
fi

# nvidia-xconfig leaves /etc/X11/xorg.conf.{backup,nvidia-xconfig-original}
# on its first run. Drop them so a freshly-bootstrapped node and a migrated
# node end up with identical /etc/X11/ contents.
rm -f /etc/X11/xorg.conf.backup /etc/X11/xorg.conf.nvidia-xconfig-original

# Boot to graphical.target so GDM starts on every boot.
systemctl set-default graphical.target

systemctl enable gdm3
# Restart unconditionally so dconf/custom.conf changes take effect on re-runs.
# Lifecycle scripts are a planned maintenance operation — operators accept
# that this kills any in-progress visual eval session.
systemctl restart gdm3

sleep 3
if systemctl is-active --quiet gdm3 && ls /tmp/.X11-unix/X* >/dev/null 2>&1; then
    echo "GDM3 running, X display socket present: $(ls /tmp/.X11-unix/)"
else
    echo "WARNING: GDM3 or Xorg not up yet; check 'journalctl -u gdm3'"
fi
