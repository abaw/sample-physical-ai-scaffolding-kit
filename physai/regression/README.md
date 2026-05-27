# physai-regression

Regression checks for the Physical AI Pipeline Platform. Each check is a
pytest function that runs against a live cluster and asserts the platform
machinery (lifecycle scripts, Slurm features, DCV state, CLI surface) is
intact.

The suite imports `physai.ssh.Session` from the CLI package; install the
CLI first if you haven't:

```bash
pip install -e "physai/cli[dev]"
```

## Run unit tests (no AWS required)

The unit tests under `regression/tests/` exercise the fixture wiring with
mocks — they don't talk to a cluster:

```bash
cd physai/regression
python -m pytest tests/
```

## Run the checks against a live cluster

The checks SSH into the cluster's login node and submit a Slurm
allocation across the GPU partition, briefly preempting the queue. If
others share the cluster, coordinate before running.

The runner takes a lifecycle mode positional. `python -m physai_regression
--help` lists the modes that exist; arguments after the mode are forwarded
to pytest. The `upgrade-existing` mode runs the check suite against a
running, user-managed cluster.

```bash
cd physai/regression
python -m physai_regression upgrade-existing \
  --profile <aws-profile> --region <aws-region>

# Or just one check:
python -m physai_regression upgrade-existing -k dcvagent \
  --profile <aws-profile> --region <aws-region>

# Or against an explicit cluster (skip CFN lookup):
python -m physai_regression upgrade-existing \
  --cluster physai-cluster-abc12345 \
  --profile <aws-profile> --region <aws-region>
```

The runner:

1. Resolves the cluster name from the `PhysaiClusterStack` CloudFormation
   output (or uses `--cluster`).
2. Calls `infra/scripts/setup-ssh.sh --output <tempfile>` to materialize
   an SSH config for `physai-login` — your `~/.ssh/config` is **not**
   touched.
3. Opens a multiplexed SSH session through that config and runs the checks.
4. Cleans the tempfile up at session end.
