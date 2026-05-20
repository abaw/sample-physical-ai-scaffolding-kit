#!/bin/bash
# dcv_session_setup.sh — Authorize the per-job DCV connection.
# Sourced from the sbatch body (host context, before srun) when --visual is set.
#
# The DCV "console" session is permanent — auto-created at boot by dcvserver
# (see install_dcv.sh) and tied to ubuntu's GDM auto-login session. Each
# physai job just sets a fresh OTP on the ubuntu PAM password so only this
# job's URL works; teardown rotates the password back to a random unguessable
# value.
#
# Inputs:
#   $1 — SLURM_JOB_ID
#
# Outputs:
#   stdout — full connect block (banner + tunnel command + URL)
#   Side effects — ubuntu PAM password set to OTP
set -euo pipefail

JOBID="${1:?Usage: dcv_session_setup.sh <SLURM_JOB_ID>}"

# ── Resolve SSM target components ──

# IMDSv2 token
TOKEN=$(curl -sfX PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60")

# Instance ID
INSTANCE_ID=$(curl -sf -H "X-aws-ec2-metadata-token: $TOKEN" \
    "http://169.254.169.254/latest/meta-data/instance-id")

# Region
REGION=$(curl -sf -H "X-aws-ec2-metadata-token: $TOKEN" \
    "http://169.254.169.254/latest/meta-data/placement/region")

# Cluster ID and group name from resource_config.json
read -r CLUSTER_ID GROUP < <(python3 -c "
import json, sys
rc = json.load(open('/opt/ml/config/resource_config.json'))
cluster_id = rc['ClusterConfig']['ClusterArn'].rsplit('/', 1)[-1]
for g in rc['InstanceGroups']:
    for inst in g.get('Instances', []):
        if inst.get('InstanceId') == '$INSTANCE_ID':
            print(cluster_id, g['Name'])
            sys.exit(0)
print('', '', file=sys.stderr)
sys.exit(1)
")

if [[ -z "$CLUSTER_ID" || -z "$GROUP" ]]; then
    echo "[visual] DCV setup failed: could not resolve cluster/group from resource_config.json" >&2
    exit 1
fi

SSM_TARGET="sagemaker-cluster:${CLUSTER_ID}_${GROUP}-${INSTANCE_ID}"

# ── Generate OTP and set ubuntu password ──

OTP=$(openssl rand -base64 24 | tr -d '=+/' | head -c 16)
echo "ubuntu:${OTP}" | sudo chpasswd

# ── Print connect block ──

cat << BLOCK

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Visual evaluation is ready on node $(hostname -s).

 1) In a second terminal, open the SSM tunnel and KEEP IT RUNNING:

    aws ssm start-session \\
      --target ${SSM_TARGET} \\
      --document-name AWS-StartPortForwardingSession \\
      --parameters '{"portNumber":["8443"],"localPortNumber":["8443"]}' \\
      --region ${REGION}

 2) Open in your browser:

    https://localhost:8443/#console

 3) Accept the self-signed cert on first connect.

 4) Sign in with:

    Username: ubuntu
    Password: ${OTP}

 Session closes automatically when the job ends (\`physai cancel ${JOBID}\`).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BLOCK
