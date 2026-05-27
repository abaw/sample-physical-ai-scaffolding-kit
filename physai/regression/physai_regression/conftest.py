"""Shared fixtures for regression checks.

These fixtures connect a live ``PhysaiClusterStack`` deployment to the
checks under ``physai_regression.checks``. The full chain is:

    pytest CLI flags  ──►  aws_profile / aws_region (None if unset; aws CLI then
                            uses its own profile/region resolution)
    aws cloudformation describe-stacks  ──►  cluster_name
    infra/scripts/setup-ssh.sh --output  ──►  ssh_config_path (tempfile)
    physai.ssh.Session(host, ssh_config=...)  ──►  physai_session

The user's ``~/.ssh/config`` is intentionally not touched — every SSH call
the checks make threads ``-F <ssh_config_path>`` via ``Session``.

Cluster connectivity (CFN describe, setup-ssh, SSH ControlMaster) only
happens when a check that requests one of these fixtures actually runs;
unit tests under ``regression/tests/`` that don't touch AWS are
unaffected.
"""

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from physai.ssh import Session

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SSH = REPO_ROOT / "infra" / "scripts" / "setup-ssh.sh"
SSH_HOST = "physai-login"
STACK_NAME = "PhysaiClusterStack"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--profile", action="store", default=None, help="AWS profile")
    parser.addoption("--region", action="store", default=None, help="AWS region")
    parser.addoption(
        "--cluster",
        action="store",
        default=None,
        help=f"Cluster name (default: resolved from {STACK_NAME} CFN output)",
    )


@pytest.fixture(scope="session")
def aws_profile(request: pytest.FixtureRequest) -> str | None:
    return request.config.getoption("--profile")


@pytest.fixture(scope="session")
def aws_region(request: pytest.FixtureRequest) -> str | None:
    return request.config.getoption("--region")


def _aws_args(profile: str | None, region: str | None) -> list[str]:
    args: list[str] = []
    if profile:
        args += ["--profile", profile]
    if region:
        args += ["--region", region]
    return args


@pytest.fixture(scope="session")
def cluster_name(
    request: pytest.FixtureRequest,
    aws_profile: str | None,
    aws_region: str | None,
) -> str:
    override = request.config.getoption("--cluster")
    if override:
        return override
    cmd = [
        "aws",
        *_aws_args(aws_profile, aws_region),
        "cloudformation",
        "describe-stacks",
        "--stack-name",
        STACK_NAME,
        "--query",
        "Stacks[0].Outputs[?OutputKey==`ClusterName`].OutputValue",
        "--output",
        "text",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0 or not r.stdout.strip() or r.stdout.strip() == "None":
        pytest.fail(
            f"Could not resolve cluster name from {STACK_NAME} CFN output. "
            f"Pass --cluster <name>.\n"
            f"aws stderr: {r.stderr.strip()}"
        )
    return r.stdout.strip()


@pytest.fixture(scope="session")
def ssh_config_path(
    cluster_name: str,
    aws_profile: str | None,
    aws_region: str | None,
) -> Iterator[Path]:
    """Tempfile populated by ``setup-ssh.sh --output``; cleaned up on session end."""
    if not SETUP_SSH.is_file():
        pytest.fail(f"setup-ssh.sh not found at {SETUP_SSH}")
    fd, path_str = tempfile.mkstemp(prefix="physai-regression-ssh-", suffix=".config")
    os.close(fd)
    path = Path(path_str)
    cmd = [
        str(SETUP_SSH),
        "--cluster",
        cluster_name,
        "--output",
        str(path),
        *_aws_args(aws_profile, aws_region),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        path.unlink(missing_ok=True)
        pytest.fail(
            f"setup-ssh.sh --output failed (exit {r.returncode}).\n"
            f"stdout: {r.stdout.strip()}\nstderr: {r.stderr.strip()}"
        )
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def physai_session(ssh_config_path: Path) -> Iterator[Session]:
    """A ``physai.ssh.Session`` to the login node, scoped to the test session."""
    if not shutil.which("ssh"):
        pytest.fail("`ssh` not found on PATH")
    s = Session(SSH_HOST, ssh_config=str(ssh_config_path))
    yield s
    s.close()
