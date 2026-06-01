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
--help` lists the modes; arguments after the mode are forwarded to
pytest.

### Modes

- **`fresh`** — `cdk destroy PhysaiClusterStack` → `cdk deploy` → run
  checks → `cdk destroy` (only on pass; left up on failure for debugging).
  Idempotent; ~40 min wall time. Use to catch regressions that only
  surface on a true first-boot deployment.
- **`upgrade-existing`** — `cdk deploy PhysaiClusterStack` +
  `infra/scripts/run-lifecycle.sh --all` → run checks. Mirrors the
  documented "applying lifecycle script changes to a running cluster"
  upgrade flow against a user-managed cluster. ~5 min total against a
  healthy cluster (the upgrade itself is near-no-op when scripts are
  unchanged). Cluster is left running; on check failure it stays in the
  upgraded state with no automated rollback.
- **`upgrade-from-ref`** — Fully ephemeral end-to-end upgrade test:
  `git worktree add` at `<ref>` → `cdk deploy` from the worktree →
  `cdk deploy` + `run-lifecycle.sh --all` from current HEAD (the
  upgrade) → run checks → `cdk destroy` + worktree cleanup. ~50 min
  wall time including a fresh deploy. On failure the cluster + worktree
  are left on disk so you can inspect; the worktree path is printed to
  stderr.

### Examples

```bash
cd physai/regression

# Fresh deploy + checks + teardown
python -m physai_regression fresh \
  --profile <aws-profile> --region <aws-region>

# Apply current HEAD's lifecycle to a running cluster, then run the check suite
python -m physai_regression upgrade-existing \
  --profile <aws-profile> --region <aws-region>

# Just one check:
python -m physai_regression upgrade-existing -k dcvagent \
  --profile <aws-profile> --region <aws-region>

# Or against an explicit cluster (skip CFN lookup):
python -m physai_regression upgrade-existing \
  --cluster physai-cluster-abc12345 \
  --profile <aws-profile> --region <aws-region>

# Ephemeral upgrade test: fresh deploy from a baseline ref, upgrade to HEAD, tear down
python -m physai_regression upgrade-from-ref --from-ref v0.2.0 \
  --profile <aws-profile> --region <aws-region>
```

The runner:

1. (`fresh` and `upgrade-from-ref` only) Destroys + redeploys
   `PhysaiClusterStack` via `npx cdk`. `upgrade-from-ref` deploys from a
   worktree pinned at `--from-ref` first, then upgrades from HEAD.
2. Resolves the cluster name from the `PhysaiClusterStack` CloudFormation
   output (or uses `--cluster`).
3. Calls `infra/scripts/setup-ssh.sh --output <tempfile>` to materialize
   an SSH config for `physai-login` — your `~/.ssh/config` is **not**
   touched.
4. Opens a multiplexed SSH session through that config and runs the checks.
5. Cleans the tempfile up at session end. (`fresh` and `upgrade-from-ref`
   also run `cdk destroy` on pass; `upgrade-from-ref` removes the
   worktree.)
