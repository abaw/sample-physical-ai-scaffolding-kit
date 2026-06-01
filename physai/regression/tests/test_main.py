"""Tests for the ``python -m physai_regression`` argparse + dispatch surface.

These don't run pytest for real — they assert that the runner forwards the
right arguments to pytest, drives the orchestration flows in the correct
order for each mode, and rejects unknown modes.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from physai_regression.__main__ import CHECKS_DIR, main


# ── upgrade-existing ──────────────────────────────────────────────────────


def test_upgrade_existing_upgrades_then_runs_checks():
    call_order: list[str] = []
    with (
        patch(
            "physai_regression.__main__.flows.upgrade_in_place",
            side_effect=lambda **_: call_order.append("upgrade"),
        ),
        patch(
            "physai_regression.__main__.pytest.main",
            side_effect=lambda *_a, **_k: call_order.append("pytest") or 0,
        ),
    ):
        rc = main(["upgrade-existing", "--profile", "p", "--region", "r"])
    assert rc == 0
    assert call_order == ["upgrade", "pytest"]


def test_upgrade_existing_returns_pytest_rc_on_check_failure(capsys):
    """Check failure: cluster left in upgraded state; rc is the pytest rc."""
    with (
        patch("physai_regression.__main__.flows.upgrade_in_place"),
        patch("physai_regression.__main__.pytest.main", return_value=5),
    ):
        rc = main(["upgrade-existing", "--profile", "p", "--region", "r"])
    assert rc == 5
    err = capsys.readouterr().err
    assert "upgraded state" in err


def test_upgrade_existing_forwards_args_to_pytest():
    with (
        patch("physai_regression.__main__.flows.upgrade_in_place"),
        patch("physai_regression.__main__.pytest.main", return_value=0) as pmain,
    ):
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
    pmain.assert_called_once()
    (forwarded,), _ = pmain.call_args
    assert forwarded[0] == str(CHECKS_DIR)
    assert forwarded[1:] == ["--profile", "p", "--region", "r", "-k", "dcvagent"]


def test_upgrade_existing_does_not_destroy():
    """``upgrade-existing`` operates on a running cluster — never destroys."""
    with (
        patch("physai_regression.__main__.flows.upgrade_in_place"),
        patch("physai_regression.__main__.pytest.main", return_value=0),
        patch("physai_regression.__main__.deploy.cdk_destroy") as destroy,
        patch("physai_regression.__main__.flows.redeploy_from_clean") as redeploy,
    ):
        main(["upgrade-existing", "--profile", "p", "--region", "r"])
    destroy.assert_not_called()
    redeploy.assert_not_called()


# ── fresh ─────────────────────────────────────────────────────────────────


def test_fresh_redeploys_then_runs_checks_then_destroys_on_pass():
    call_order: list[str] = []
    with (
        patch(
            "physai_regression.__main__.flows.redeploy_from_clean",
            side_effect=lambda **_: call_order.append("redeploy"),
        ),
        patch(
            "physai_regression.__main__.pytest.main",
            side_effect=lambda *_a, **_k: call_order.append("pytest") or 0,
        ),
        patch(
            "physai_regression.__main__.deploy.cdk_destroy",
            side_effect=lambda **_: call_order.append("destroy"),
        ),
    ):
        rc = main(["fresh", "--profile", "p", "--region", "r"])
    assert rc == 0
    assert call_order == ["redeploy", "pytest", "destroy"]


def test_fresh_skips_destroy_on_pytest_failure(capsys):
    with (
        patch("physai_regression.__main__.flows.redeploy_from_clean"),
        patch("physai_regression.__main__.pytest.main", return_value=1),
        patch("physai_regression.__main__.deploy.cdk_destroy") as destroy,
    ):
        rc = main(["fresh", "--profile", "p", "--region", "r"])
    assert rc == 1
    destroy.assert_not_called()
    err = capsys.readouterr().err
    assert "Cluster left up" in err


def test_fresh_forwards_aws_and_extra_args_to_pytest():
    with (
        patch("physai_regression.__main__.flows.redeploy_from_clean"),
        patch("physai_regression.__main__.deploy.cdk_destroy"),
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
        patch("physai_regression.__main__.flows.redeploy_from_clean") as redeploy,
        patch("physai_regression.__main__.deploy.cdk_destroy") as destroy,
        patch("physai_regression.__main__.pytest.main", return_value=0),
    ):
        main(["fresh", "--profile", "p", "--region", "r"])
    redeploy.assert_called_once_with(profile="p", region="r")
    destroy.assert_called_once_with(profile="p", region="r", skip_if_absent=True)


# ── upgrade-from-ref ──────────────────────────────────────────────────────


def _wt_path(name: str = "wt") -> Path:
    return Path(f"/tmp/{name}")


def test_upgrade_from_ref_full_success_deploys_upgrades_checks_destroys():
    call_order: list[str] = []
    with (
        patch(
            "physai_regression.__main__.flows.deploy_from_ref",
            side_effect=lambda *_a, **_k: call_order.append("deploy_ref") or _wt_path(),
        ),
        patch(
            "physai_regression.__main__.flows.upgrade_in_place",
            side_effect=lambda **_: call_order.append("upgrade"),
        ),
        patch(
            "physai_regression.__main__.pytest.main",
            side_effect=lambda *_a, **_k: call_order.append("pytest") or 0,
        ),
        patch(
            "physai_regression.__main__.flows.destroy_and_remove_worktree",
            side_effect=lambda *_a, **_k: call_order.append("destroy"),
        ) as destroy,
    ):
        rc = main(
            [
                "upgrade-from-ref",
                "--from-ref",
                "v0.2.0",
                "--profile",
                "p",
                "--region",
                "r",
            ]
        )
    assert rc == 0
    assert call_order == ["deploy_ref", "upgrade", "pytest", "destroy"]
    # The worktree path from deploy_from_ref must be the one handed to
    # cleanup — otherwise cleanup removes the wrong (or no) worktree.
    assert destroy.call_args.args[0] == _wt_path()
    assert destroy.call_args.kwargs == {"profile": "p", "region": "r"}


def test_upgrade_from_ref_passes_ref_to_deploy_from_ref():
    with (
        patch(
            "physai_regression.__main__.flows.deploy_from_ref",
            return_value=_wt_path(),
        ) as deploy_ref,
        patch("physai_regression.__main__.flows.upgrade_in_place"),
        patch("physai_regression.__main__.pytest.main", return_value=0),
        patch("physai_regression.__main__.flows.destroy_and_remove_worktree"),
    ):
        main(
            [
                "upgrade-from-ref",
                "--from-ref",
                "v0.2.0",
                "--profile",
                "p",
                "--region",
                "r",
            ]
        )
    deploy_ref.assert_called_once_with("v0.2.0", profile="p", region="r")


def test_upgrade_from_ref_check_failure_skips_destroy(capsys):
    """Check failure: cluster + worktree left in place so the user can debug."""
    with (
        patch(
            "physai_regression.__main__.flows.deploy_from_ref",
            return_value=_wt_path("post-fail"),
        ),
        patch("physai_regression.__main__.flows.upgrade_in_place"),
        patch("physai_regression.__main__.pytest.main", return_value=7),
        patch(
            "physai_regression.__main__.flows.destroy_and_remove_worktree"
        ) as destroy,
    ):
        rc = main(["upgrade-from-ref", "--from-ref", "v0.2.0", "--profile", "p"])
    assert rc == 7
    destroy.assert_not_called()
    err = capsys.readouterr().err
    assert "upgraded state" in err
    assert "/tmp/post-fail" in err


def test_upgrade_from_ref_requires_from_ref():
    with pytest.raises(SystemExit) as excinfo:
        main(["upgrade-from-ref", "--profile", "p"])
    assert excinfo.value.code == 2


def test_from_ref_rejected_for_non_upgrade_from_ref_modes():
    with pytest.raises(SystemExit) as excinfo:
        main(["fresh", "--from-ref", "v0.2.0", "--profile", "p"])
    assert excinfo.value.code == 2


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
