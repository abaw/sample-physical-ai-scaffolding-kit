"""Entry point: ``python -m physai_regression <mode> [pytest-args...]``.

Modes:
    fresh               Destroy → deploy → run checks → destroy on pass.
    upgrade-existing    Apply the documented in-place upgrade (cdk deploy +
                        run-lifecycle.sh --all) to a user-managed cluster,
                        then run the check suite. Cluster is left running.
    upgrade-from-ref    Worktree at <ref> → deploy@ref → upgrade to HEAD →
                        checks → destroy + worktree cleanup. Fully ephemeral
                        on success; both artifacts kept on failure.

Examples::

    python -m physai_regression fresh \\
        --profile myprofile --region us-west-2

    python -m physai_regression upgrade-existing \\
        --profile myprofile --region us-west-2

    python -m physai_regression upgrade-existing -k dcvagent \\
        --profile myprofile --region us-west-2

    python -m physai_regression upgrade-from-ref --from-ref v0.2.0 \\
        --profile myprofile --region us-west-2

``--profile`` and ``--region`` are consumed by both the orchestration
primitives (``cdk deploy``/``destroy``) and the conftest fixtures, so they
are parsed at the top level and forwarded to pytest as well. All other
arguments after the mode are forwarded to pytest unchanged.
"""

import argparse
import sys
from pathlib import Path

import pytest

from .orchestration import deploy, flows

CHECKS_DIR = Path(__file__).resolve().parent / "checks"

MODES = ["fresh", "upgrade-existing", "upgrade-from-ref"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m physai_regression",
        description=(
            "Run platform regression checks against a live cluster. "
            "Arguments after the mode are forwarded to pytest."
        ),
    )
    parser.add_argument("mode", choices=MODES, help="Lifecycle mode.")
    parser.add_argument("--profile", default=None, help="AWS profile")
    parser.add_argument("--region", default=None, help="AWS region")
    parser.add_argument(
        "--from-ref",
        default=None,
        help="Starting commit/tag to deploy before upgrading to HEAD "
        "(required for upgrade-from-ref).",
    )
    return parser


def _pytest_args(
    profile: str | None, region: str | None, extra: list[str]
) -> list[str]:
    """Forward AWS args + caller-supplied args to pytest under ``CHECKS_DIR``."""
    args: list[str] = [str(CHECKS_DIR)]
    if profile:
        args += ["--profile", profile]
    if region:
        args += ["--region", region]
    args += extra
    return args


def _run_checks(profile: str | None, region: str | None, extra: list[str]) -> int:
    return int(pytest.main(_pytest_args(profile, region, extra)))


def _run_fresh(profile: str | None, region: str | None, extra: list[str]) -> int:
    """fresh: destroy → deploy → checks → destroy on pass."""
    flows.redeploy_from_clean(profile=profile, region=region)
    rc = _run_checks(profile, region, extra)
    if rc == 0:
        deploy.cdk_destroy(profile=profile, region=region, skip_if_absent=True)
    else:
        print(
            f"Checks exited with code {rc}. Cluster left up so you can debug. "
            "Tear it down with: npx cdk destroy PhysaiClusterStack",
            file=sys.stderr,
        )
    return rc


def _run_upgrade_existing(
    profile: str | None, region: str | None, extra: list[str]
) -> int:
    """upgrade-existing: apply the in-place upgrade, then run the check suite.

    On check failure the cluster is left in the upgraded state for the
    user to debug; rolling back would require a separate downgrade flow.
    """
    flows.upgrade_in_place(profile=profile, region=region)
    rc = _run_checks(profile, region, extra)
    if rc != 0:
        print(
            f"Checks exited with code {rc}. Cluster is in the upgraded state; "
            "debug there or roll back manually.",
            file=sys.stderr,
        )
    return rc


def _run_upgrade_from_ref(
    ref: str, profile: str | None, region: str | None, extra: list[str]
) -> int:
    """upgrade-from-ref: deploy@ref → upgrade to HEAD → checks → destroy.

    The deploy@ref step validates that ``ref`` was deployable to begin
    with; the checks validate that the in-place upgrade from ``ref`` to
    HEAD landed in a healthy state.

    On failure the cluster + worktree are left on disk for inspection;
    the worktree path is printed so cleanup is one command. Full cleanup
    happens only on success.
    """
    physai_in_worktree = flows.deploy_from_ref(ref, profile=profile, region=region)
    print(f"physai/ at {ref}: {physai_in_worktree}", file=sys.stderr)
    flows.upgrade_in_place(profile=profile, region=region)
    rc = _run_checks(profile, region, extra)
    if rc != 0:
        print(
            f"Checks exited with code {rc}. "
            f"Cluster left in upgraded state; worktree physai/ at {physai_in_worktree}.",
            file=sys.stderr,
        )
        return rc
    flows.destroy_and_remove_worktree(
        physai_in_worktree, profile=profile, region=region
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args, pytest_args = parser.parse_known_args(argv)

    if args.mode != "upgrade-from-ref" and args.from_ref is not None:
        parser.error("--from-ref is only valid for the upgrade-from-ref mode")
    if args.mode == "upgrade-from-ref" and args.from_ref is None:
        parser.error("upgrade-from-ref requires --from-ref <commit-or-tag>")

    if args.mode == "fresh":
        return _run_fresh(args.profile, args.region, pytest_args)
    if args.mode == "upgrade-existing":
        return _run_upgrade_existing(args.profile, args.region, pytest_args)
    if args.mode == "upgrade-from-ref":
        return _run_upgrade_from_ref(
            args.from_ref, args.profile, args.region, pytest_args
        )

    raise AssertionError(f"unreachable: argparse rejected unknown mode {args.mode!r}")


if __name__ == "__main__":
    sys.exit(main())
