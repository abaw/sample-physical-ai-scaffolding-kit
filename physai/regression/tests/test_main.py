"""Tests for the ``python -m physai_regression`` argparse surface.

These don't run pytest for real — they assert that the runner forwards
the right arguments and rejects unknown modes.
"""

from unittest.mock import patch

import pytest

from physai_regression.__main__ import CHECKS_DIR, main


def test_upgrade_existing_forwards_args_to_pytest():
    with patch("physai_regression.__main__.pytest.main", return_value=0) as pmain:
        rc = main(
            [
                "upgrade-existing",
                "--profile",
                "p",
                "--region",
                "r",
                "-k",
                "dcvagent",
            ]
        )
    assert rc == 0
    (forwarded,), _ = pmain.call_args
    assert forwarded[0] == str(CHECKS_DIR)
    assert forwarded[1:] == ["--profile", "p", "--region", "r", "-k", "dcvagent"]


def test_runner_returns_pytest_exit_code():
    with patch("physai_regression.__main__.pytest.main", return_value=2):
        assert main(["upgrade-existing"]) == 2


def test_unknown_mode_is_rejected_by_argparse():
    with pytest.raises(SystemExit) as excinfo:
        main(["definitely-not-a-real-mode"])
    # argparse exits 2 on usage errors.
    assert excinfo.value.code == 2


def test_missing_mode_is_rejected_by_argparse():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
