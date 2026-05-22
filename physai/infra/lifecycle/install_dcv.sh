#!/bin/bash
# install_dcv.sh — Install and configure NICE DCV server on GPU worker nodes.
# DCV auto-creates a single persistent "console" session owned by ubuntu at
# boot. dcvagentlauncher is started inside ubuntu's GNOME session via XDG
# autostart (/etc/xdg/autostart/dcvagentlauncher.desktop, shipped by
# nice-dcv-server) — that spawns dcvagent, which captures frames from the
# Xorg display and streams them to port 8443.
#
# Idempotent: skips if the pinned version is already installed.
# Does NOT install nice-dcv-gl (console sessions don't need it, and its
# GL-interception layer conflicts with IsaacSim's native CUDA/Vulkan).
#
# Usage: install_dcv.sh
set -euo pipefail
# shellcheck source=_lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
require_node_type compute

# Gate: only install on nodes where GDM is set up (i.e. GPU workers).
if ! systemctl is-enabled --quiet gdm3 2>/dev/null; then
    echo "gdm3 not enabled — this node has no GPU/X graphical session, skipping DCV"
    exit 0
fi

# ---------- Version pin ----------
# Source: https://www.amazondcv.com/ (Linux Server, Ubuntu 22.04). Tarballs and
# the GPG key live at the AWS-operated CloudFront origin documented in
# https://docs.aws.amazon.com/dcv/latest/adminguide/setting-up-installing-linux.html.
# To bump: pick the next "<major>.<minor>-<build>" from the download page,
# update the URL, then refresh DCV_SHA256 with the published checksum (or
# `curl -sfL "$DCV_URL" | sha256sum`).
DCV_VERSION="2025.0-20103"
DCV_URL="https://d1uj6qtbmh3dt5.cloudfront.net/2025.0/Servers/nice-dcv-2025.0-20103-ubuntu2204-x86_64.tgz"
DCV_SHA256="acfc339c9e57be9800f25734cb18dec87da2b0457b3cfd2582fc57f05de7c792"
DCV_GPG_KEY_URL="https://d1uj6qtbmh3dt5.cloudfront.net/NICE-GPG-KEY"

needs_install=true
if dpkg -l nice-dcv-server 2>/dev/null | grep -q "$DCV_VERSION"; then
    echo "DCV $DCV_VERSION already installed"
    needs_install=false
fi

if $needs_install; then
    echo "Installing DCV $DCV_VERSION..."

    # ---------- GPG key ----------
    curl -sf "$DCV_GPG_KEY_URL" | gpg --import 2>/dev/null || true

    # ---------- Download and extract ----------
    WORK_DIR=$(mktemp -d)
    trap 'rm -rf "$WORK_DIR"' EXIT

    curl -sfL "$DCV_URL" -o "$WORK_DIR/dcv.tgz"
    echo "$DCV_SHA256  $WORK_DIR/dcv.tgz" | sha256sum -c -
    tar xzf "$WORK_DIR/dcv.tgz" -C "$WORK_DIR" --strip-components=1

    # ---------- Install debs ----------
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y -qq \
        "$WORK_DIR"/nice-dcv-server_*.deb \
        "$WORK_DIR"/nice-dcv-web-viewer_*.deb \
        "$WORK_DIR"/nice-xdcv_*.deb

    # ---------- Add ubuntu to video group ----------
    usermod -aG video ubuntu
fi

# ---------- Write /etc/dcv/dcv.conf ----------
# create-session=true makes dcvserver auto-create a single persistent "console"
# session owned by ubuntu at start-up. The per-job CLI scripts only rotate
# ubuntu's OTP password — they don't create or close the session.
mkdir -p /etc/dcv
cat > /etc/dcv/dcv.conf << 'EOF'
[session-management]
create-session = true

[session-management/defaults]
permissions-file = "/etc/dcv/default.perm"

[session-management/automatic-console-session]
owner = "ubuntu"

[display]
target-fps = 30

[connectivity]
web-port = 8443
enable-quic-frontend = false

[security]
authentication = "system"
no-tls-strict = true
EOF

# ---------- systemd ordering ----------
# dcvserver should start after gdm3 so the X session it captures already exists.
mkdir -p /etc/systemd/system/dcvserver.service.d
cat > /etc/systemd/system/dcvserver.service.d/ordering.conf << 'EOF'
[Unit]
After=gdm3.service
Wants=gdm3.service
EOF

# ---------- Enable and (re)start ----------
systemctl daemon-reload
systemctl enable dcvserver
systemctl restart dcvserver

# Restart GDM so ubuntu's GNOME session picks up DCV's
# /etc/xdg/autostart/dcvagentlauncher.desktop file. dcvagentlauncher is what
# spawns dcvagent inside ubuntu's user session, and dcvagent is what actually
# captures frames. Without this restart, on first-boot ubuntu logged in
# BEFORE install_dcv.sh dropped the .desktop file, so the autostart entry
# was never picked up — the session would exist with 0 frames captured.
# Lifecycle scripts are a planned maintenance operation, so disrupting any
# in-progress visual eval session is acceptable.
systemctl restart gdm3 2>/dev/null || true

# ---------- Smoke test ----------
sleep 3
if dcv list-sessions >/dev/null 2>&1; then
    echo "DCV $DCV_VERSION running, sessions: $(dcv list-sessions)"
else
    echo "WARNING: dcv list-sessions failed; check journalctl -u dcvserver"
fi
