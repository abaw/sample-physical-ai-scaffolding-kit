"""Entry point: ``python -m physai_regression <mode> [pytest-args...]``.

Modes:
    upgrade-existing    Run checks against a running, user-managed cluster.

Examples::

    python -m physai_regression upgrade-existing \\
        --profile myprofile --region us-west-2

    python -m physai_regression upgrade-existing -k dcvagent \\
        --profile myprofile --region us-west-2

Arguments after the mode are forwarded to pytest, including the
conftest-defined ``--profile``, ``--region``, and ``--cluster`` options.
"""

import argparse
import sys
from pathlib import Path

import pytest

CHECKS_DIR = Path(__file__).resolve().parent / "checks"

MODES = ["upgrade-existing"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m physai_regression",
        description=(
            "Run platform regression checks against a live cluster. "
            "Arguments after the mode are forwarded to pytest."
        ),
    )
    parser.add_argument("mode", choices=MODES, help="Lifecycle mode.")
    args, pytest_args = parser.parse_known_args(argv)

    if args.mode == "upgrade-existing":
        return pytest.main([str(CHECKS_DIR), *pytest_args])

    raise AssertionError(f"unreachable: argparse rejected unknown mode {args.mode!r}")


if __name__ == "__main__":
    sys.exit(main())
