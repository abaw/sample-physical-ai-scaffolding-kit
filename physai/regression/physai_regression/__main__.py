"""Entry point: ``python -m physai_regression <mode> [pytest-args...]``.

Modes:
    fresh               Destroy → deploy → run checks → destroy on pass.
    upgrade-existing    Run checks against a running, user-managed cluster.

Examples::

    python -m physai_regression fresh \\
        --profile myprofile --region us-west-2

    python -m physai_regression upgrade-existing \\
        --profile myprofile --region us-west-2

    python -m physai_regression upgrade-existing -k dcvagent \\
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

from .orchestration import stages

CHECKS_DIR = Path(__file__).resolve().parent / "checks"

MODES = ["fresh", "upgrade-existing"]


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


def _run_fresh(profile: str | None, region: str | None, extra: list[str]) -> int:
    """fresh: destroy → deploy → checks → destroy on pass."""
    stages.fresh_prepare(profile=profile, region=region)
    rc = pytest.main(_pytest_args(profile, region, extra))
    if rc == 0:
        stages.fresh_teardown(profile=profile, region=region)
    else:
        print(
            f"Checks exited with code {rc}. Cluster left up so you can debug. "
            "Tear it down with: npx cdk destroy PhysaiClusterStack",
            file=sys.stderr,
        )
    return int(rc)


def _run_upgrade_existing(
    profile: str | None, region: str | None, extra: list[str]
) -> int:
    return int(pytest.main(_pytest_args(profile, region, extra)))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args, pytest_args = parser.parse_known_args(argv)

    if args.mode == "fresh":
        return _run_fresh(args.profile, args.region, pytest_args)
    if args.mode == "upgrade-existing":
        return _run_upgrade_existing(args.profile, args.region, pytest_args)

    raise AssertionError(f"unreachable: argparse rejected unknown mode {args.mode!r}")


if __name__ == "__main__":
    sys.exit(main())
