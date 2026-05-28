"""Wrappers for ``cdk`` and CloudFormation operations.

Each primitive shells out via ``subprocess.run`` and is mockable at the
``subprocess.run`` boundary. The CDK app lives at ``physai/infra/``; each
primitive accepts ``infra_dir`` so the modes can override (e.g. the
``upgrade-from-ref`` mode uses a worktree path).

Region handling: ``cdk deploy`` and ``cdk destroy`` silently accept
``--region`` but do not honor it (see aws/aws-cdk#28725 — the flag is
listed by the top-level ``cdk`` parser but not by ``deploy``/``destroy``,
so it gets parsed and discarded). For environment-agnostic stacks like
this app's, the deploy region is resolved from ``AWS_REGION`` /
``AWS_DEFAULT_REGION`` in the subprocess env (which CDK exports as
``CDK_DEFAULT_REGION`` to the synth subprocess). These helpers therefore
inject the region via env, not argv. ``--profile`` is documented and
honored, so it stays as a flag.
"""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INFRA_DIR = REPO_ROOT / "infra"
CLUSTER_STACK = "PhysaiClusterStack"


def aws_cli_args(profile: str | None, region: str | None) -> list[str]:
    """Build ``--profile``/``--region`` argv suffixes for an ``aws`` CLI call,
    skipping each flag when its value is None."""
    args: list[str] = []
    if profile:
        args += ["--profile", profile]
    if region:
        args += ["--region", region]
    return args


class StackNotFound(RuntimeError):
    """The named stack genuinely does not exist in this account/region.

    Raised only when ``describe-stacks`` fails with CloudFormation's
    "does not exist" ``ValidationError`` — never for auth, network, or
    other failures, which raise :class:`StackQueryError` instead so they
    can't be mistaken for absence.
    """


class StackQueryError(RuntimeError):
    """``describe-stacks`` failed for a reason other than the stack being
    absent (expired/insufficient credentials, throttling, wrong region,
    no network). Callers must NOT treat this as "stack absent"."""


# CloudFormation's signature for a genuinely-missing stack, e.g.
# "An error occurred (ValidationError) ... Stack with id X does not exist".
_STACK_ABSENT_SIGNATURE = "does not exist"


def describe_stack(
    stack: str,
    query: str,
    profile: str | None = None,
    region: str | None = None,
) -> str:
    """Run ``aws cloudformation describe-stacks --stack-name <stack> --query <query>``.

    Returns the stripped ``--output text`` result. Raises
    :class:`StackNotFound` when the stack genuinely does not exist, and
    :class:`StackQueryError` for any other failure (auth, network,
    throttling, wrong region) — the distinction matters because
    :func:`stack_exists` maps only the former to "absent". The returned
    string can be empty when the stack exists but the JMESPath query
    matched nothing (e.g. an output key that isn't declared).
    """
    cmd = [
        "aws",
        *aws_cli_args(profile, region),
        "cloudformation",
        "describe-stacks",
        "--stack-name",
        stack,
        "--query",
        query,
        "--output",
        "text",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        stderr = r.stderr.strip()
        prefix = f"aws cloudformation describe-stacks --stack-name {stack} failed: "
        if _STACK_ABSENT_SIGNATURE in stderr:
            raise StackNotFound(prefix + stderr)
        raise StackQueryError(prefix + stderr)
    out = r.stdout.strip()
    # `aws --output text` prints "None" (not empty) when a query matches a
    # null JMESPath result. Normalize to empty.
    return "" if out == "None" else out


def _cdk_env(region: str | None) -> dict[str, str]:
    """Subprocess env for ``cdk`` invocations.

    Pins ``AWS_REGION`` / ``AWS_DEFAULT_REGION`` to the requested region
    so the synth subprocess resolves env-agnostic stacks to the right
    region regardless of the parent shell's settings.
    """
    env = dict(os.environ)
    if region:
        env["AWS_REGION"] = region
        env["AWS_DEFAULT_REGION"] = region
    return env


def stack_exists(
    stack: str,
    profile: str | None = None,
    region: str | None = None,
) -> bool:
    """Return True when the stack is present in CloudFormation.

    A stack in ``DELETE_COMPLETE`` is reported as absent: ``describe-stacks``
    only surfaces it when filtered by name, and treating it as present would
    make the fresh mode attempt a destroy that does nothing useful.

    Only a genuine :class:`StackNotFound` maps to ``False``. A
    :class:`StackQueryError` (auth/network/throttle) propagates: a caller
    like ``cdk_destroy(skip_if_absent=True)`` must not silently skip the
    destroy — and leak a live cluster — just because the existence probe
    couldn't reach CloudFormation.
    """
    try:
        status = describe_stack(
            stack, "Stacks[0].StackStatus", profile=profile, region=region
        )
    except StackNotFound:
        return False
    return bool(status) and status != "DELETE_COMPLETE"


def _cdk_profile_args(profile: str | None) -> list[str]:
    return ["--profile", profile] if profile else []


def cdk_deploy(
    stack: str = CLUSTER_STACK,
    profile: str | None = None,
    region: str | None = None,
    infra_dir: Path | None = None,
) -> None:
    """Run ``npx cdk deploy <stack> --require-approval never``.

    Streams stdout/stderr to the parent process so the deploy progress is
    visible while the regression run is in flight. ``region`` is passed
    via env vars (see module docstring), not as a flag.
    """
    cwd = infra_dir or DEFAULT_INFRA_DIR
    cmd = [
        "npx",
        "cdk",
        "deploy",
        stack,
        "--require-approval",
        "never",
        *_cdk_profile_args(profile),
    ]
    r = subprocess.run(cmd, cwd=str(cwd), env=_cdk_env(region), check=False)
    if r.returncode != 0:
        raise RuntimeError(f"cdk deploy {stack} failed (exit {r.returncode})")


def cdk_destroy(
    stack: str = CLUSTER_STACK,
    profile: str | None = None,
    region: str | None = None,
    infra_dir: Path | None = None,
    skip_if_absent: bool = True,
) -> None:
    """Run ``npx cdk destroy <stack> --force``.

    With ``skip_if_absent=True`` (the default), checks CloudFormation first
    and returns without invoking ``cdk`` if the stack is not present.
    ``region`` is passed via env vars (see module docstring), not as a flag.
    """
    if skip_if_absent and not stack_exists(stack, profile=profile, region=region):
        return
    cwd = infra_dir or DEFAULT_INFRA_DIR
    cmd = [
        "npx",
        "cdk",
        "destroy",
        stack,
        "--force",
        *_cdk_profile_args(profile),
    ]
    r = subprocess.run(cmd, cwd=str(cwd), env=_cdk_env(region), check=False)
    if r.returncode != 0:
        raise RuntimeError(f"cdk destroy {stack} failed (exit {r.returncode})")
