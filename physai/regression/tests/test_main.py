"""Tests for the ``python -m physai_regression`` argparse + dispatch surface.

These don't run pytest for real — they assert that the runner forwards the
right arguments to pytest, drives the orchestration stages in the correct
order for each mode, and rejects unknown modes.
"""

from unittest.mock import patch

import pytest

from physai_regression.__main__ import CHECKS_DIR, main


# ── upgrade-existing ──────────────────────────────────────────────────────


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


def test_upgrade_existing_returns_pytest_exit_code():
    with patch("physai_regression.__main__.pytest.main", return_value=2):
        assert main(["upgrade-existing"]) == 2


def test_upgrade_existing_does_not_touch_orchestration():
    """``upgrade-existing`` operates on a running cluster — never destroys."""
    with (
        patch("physai_regression.__main__.pytest.main", return_value=0),
        patch("physai_regression.__main__.stages.fresh_prepare") as prepare,
        patch("physai_regression.__main__.stages.fresh_teardown") as teardown,
    ):
        main(["upgrade-existing", "--profile", "p", "--region", "r"])
    prepare.assert_not_called()
    teardown.assert_not_called()


# ── fresh ─────────────────────────────────────────────────────────────────


def test_fresh_runs_prepare_then_pytest_then_teardown_on_pass():
    call_order: list[str] = []
    with (
        patch(
            "physai_regression.__main__.stages.fresh_prepare",
            side_effect=lambda **_: call_order.append("prepare"),
        ),
        patch(
            "physai_regression.__main__.pytest.main",
            side_effect=lambda *_a, **_k: call_order.append("pytest") or 0,
        ),
        patch(
            "physai_regression.__main__.stages.fresh_teardown",
            side_effect=lambda **_: call_order.append("teardown"),
        ),
    ):
        rc = main(["fresh", "--profile", "p", "--region", "r"])
    assert rc == 0
    assert call_order == ["prepare", "pytest", "teardown"]


def test_fresh_skips_teardown_on_pytest_failure(capsys):
    with (
        patch("physai_regression.__main__.stages.fresh_prepare"),
        patch("physai_regression.__main__.pytest.main", return_value=1),
        patch("physai_regression.__main__.stages.fresh_teardown") as teardown,
    ):
        rc = main(["fresh", "--profile", "p", "--region", "r"])
    assert rc == 1
    teardown.assert_not_called()
    err = capsys.readouterr().err
    assert "Cluster left up" in err


def test_fresh_forwards_aws_and_extra_args_to_pytest():
    with (
        patch("physai_regression.__main__.stages.fresh_prepare"),
        patch("physai_regression.__main__.stages.fresh_teardown"),
        patch("physai_regression.__main__.pytest.main", return_value=0) as pmain,
    ):
        main(
            [
                "fresh",
                "--profile",
                "p",
                "--region",
                "r",
                "-k",
                "dcvagent",
            ]
        )
    (forwarded,), _ = pmain.call_args
    assert forwarded[0] == str(CHECKS_DIR)
    assert forwarded[1:] == ["--profile", "p", "--region", "r", "-k", "dcvagent"]


def test_fresh_passes_aws_args_to_orchestration():
    with (
        patch("physai_regression.__main__.stages.fresh_prepare") as prepare,
        patch("physai_regression.__main__.stages.fresh_teardown") as teardown,
        patch("physai_regression.__main__.pytest.main", return_value=0),
    ):
        main(["fresh", "--profile", "p", "--region", "r"])
    prepare.assert_called_once_with(profile="p", region="r")
    teardown.assert_called_once_with(profile="p", region="r")


# ── argparse rejections ───────────────────────────────────────────────────


def test_unknown_mode_is_rejected_by_argparse():
    with pytest.raises(SystemExit) as excinfo:
        main(["definitely-not-a-real-mode"])
    # argparse exits 2 on usage errors.
    assert excinfo.value.code == 2


def test_missing_mode_is_rejected_by_argparse():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
