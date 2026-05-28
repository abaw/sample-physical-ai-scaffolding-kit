"""Tests for fixtures in ``physai_regression.conftest``.

Cluster discovery and ssh-config generation invoke ``aws`` and the
``setup-ssh.sh`` script via ``subprocess.run``. We mock that boundary so
the tests exercise the fixture wiring without touching AWS or the
filesystem outside ``tmp_path``.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from physai_regression import conftest as conftest_module


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


# ── cluster_name ────────────────────────────────────────────────────────────


def _request_with(cluster: str | None = None) -> MagicMock:
    req = MagicMock()
    req.config.getoption.side_effect = lambda name: {"--cluster": cluster}.get(name)
    return req


def test_cluster_name_uses_cli_override_without_calling_aws():
    with patch("physai_regression.conftest.describe_stack") as ds:
        out = conftest_module.cluster_name.__wrapped__(
            _request_with(cluster="explicit-cluster"),
            aws_profile=None,
            aws_region=None,
        )
    assert out == "explicit-cluster"
    ds.assert_not_called()


def test_cluster_name_resolves_from_cfn_output():
    with patch(
        "physai_regression.conftest.describe_stack",
        return_value="physai-cluster-abc12345",
    ) as ds:
        out = conftest_module.cluster_name.__wrapped__(
            _request_with(),
            aws_profile="myprofile",
            aws_region="us-west-2",
        )
    assert out == "physai-cluster-abc12345"
    kwargs = ds.call_args.kwargs
    assert kwargs == {"profile": "myprofile", "region": "us-west-2"}
    args = ds.call_args.args
    assert args[0] == "PhysaiClusterStack"
    assert "ClusterName" in args[1]


def test_cluster_name_fails_loudly_when_output_empty():
    with patch(
        "physai_regression.conftest.describe_stack",
        return_value="",
    ):
        with pytest.raises(pytest.fail.Exception) as excinfo:
            conftest_module.cluster_name.__wrapped__(
                _request_with(),
                aws_profile=None,
                aws_region=None,
            )
    assert "ClusterName" in str(excinfo.value)


def test_cluster_name_fails_loudly_when_stack_not_found():
    with patch(
        "physai_regression.conftest.describe_stack",
        side_effect=conftest_module.StackNotFound("no such stack"),
    ):
        with pytest.raises(pytest.fail.Exception) as excinfo:
            conftest_module.cluster_name.__wrapped__(
                _request_with(),
                aws_profile=None,
                aws_region=None,
            )
    assert "no such stack" in str(excinfo.value)


# ── ssh_config_path ─────────────────────────────────────────────────────────


def test_ssh_config_path_invokes_setup_ssh_with_output_flag(tmp_path: Path):
    fake_setup = tmp_path / "setup-ssh.sh"
    fake_setup.write_text("#!/bin/sh\n")
    fake_setup.chmod(0o755)

    with (
        patch("physai_regression.conftest.SETUP_SSH", fake_setup),
        patch(
            "physai_regression.conftest.subprocess.run",
            return_value=_completed(stdout="ok"),
        ) as run,
    ):
        gen = conftest_module.ssh_config_path.__wrapped__(
            cluster_name="my-cluster",
            aws_profile="p",
            aws_region="r",
        )
        path = next(gen)
        try:
            cmd = run.call_args.args[0]
            assert cmd[0] == str(fake_setup)
            assert "--cluster" in cmd and "my-cluster" in cmd
            assert "--output" in cmd
            output_path = Path(cmd[cmd.index("--output") + 1])
            assert output_path == path
            assert "--profile" in cmd and "p" in cmd
            assert "--region" in cmd and "r" in cmd
        finally:
            # Run the cleanup half of the fixture.
            for _ in gen:
                pass


def test_ssh_config_path_cleans_up_tempfile_after_session(tmp_path: Path):
    fake_setup = tmp_path / "setup-ssh.sh"
    fake_setup.write_text("#!/bin/sh\n")
    fake_setup.chmod(0o755)

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        # Touch the output file so the cleanup branch has something to remove.
        out_idx = cmd.index("--output")
        Path(cmd[out_idx + 1]).write_text("Host physai-login\n")
        captured["path"] = cmd[out_idx + 1]
        return _completed()

    with (
        patch("physai_regression.conftest.SETUP_SSH", fake_setup),
        patch("physai_regression.conftest.subprocess.run", side_effect=fake_run),
    ):
        gen = conftest_module.ssh_config_path.__wrapped__(
            cluster_name="c",
            aws_profile=None,
            aws_region=None,
        )
        path = next(gen)
        assert path.exists()
        for _ in gen:
            pass
        assert not path.exists()
        assert captured["path"] == str(path)


def test_ssh_config_path_fails_loudly_when_setup_ssh_returns_nonzero(tmp_path: Path):
    fake_setup = tmp_path / "setup-ssh.sh"
    fake_setup.write_text("#!/bin/sh\nexit 1\n")
    fake_setup.chmod(0o755)

    with (
        patch("physai_regression.conftest.SETUP_SSH", fake_setup),
        patch(
            "physai_regression.conftest.subprocess.run",
            return_value=_completed(returncode=1, stderr="boom"),
        ),
    ):
        gen = conftest_module.ssh_config_path.__wrapped__(
            cluster_name="c",
            aws_profile=None,
            aws_region=None,
        )
        with pytest.raises(pytest.fail.Exception) as excinfo:
            next(gen)
        assert "setup-ssh.sh" in str(excinfo.value)
