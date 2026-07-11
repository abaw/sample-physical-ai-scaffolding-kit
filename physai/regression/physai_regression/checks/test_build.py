"""Container build checks against the fake-project containers.

These submit real ``physai build`` jobs to the cluster. With the
fake-project base image (``python:3.12-slim-bookworm``) and a no-op
setup hook, each build completes in well under a minute on the
``cpu`` partition.
"""

import time

import pytest

FAKE_BUILD_NAME = "fake-converter"


@pytest.mark.platform
def test_build_produces_sqsh(physai_session, physai_cli, fake_project_dir) -> None:
    """``physai build <fake-converter> --rebuild`` produces a ``.sqsh`` on FSx.

    Without ``-n``, ``physai build`` streams the build job's log and only
    returns once the Slurm job has exited — so on return, the sqsh is
    guaranteed to exist if the build succeeded. ``--rebuild`` makes the
    test idempotent regardless of whether a previous run left a sqsh.
    """
    container = fake_project_dir / "containers" / FAKE_BUILD_NAME
    physai_cli.run("build", str(container), "--rebuild")
    out = physai_session.run(
        f"test -f /fsx/enroot/{FAKE_BUILD_NAME}.sqsh && echo y || echo n"
    ).strip()
    assert out == "y", (
        f"`physai build` returned but /fsx/enroot/{FAKE_BUILD_NAME}.sqsh is missing"
    )


@pytest.mark.platform
def test_rebuild_replaces_sqsh(physai_session, physai_cli, fake_project_dir) -> None:
    """``physai build --rebuild`` advances the sqsh's mtime (it was replaced)."""
    container = fake_project_dir / "containers" / FAKE_BUILD_NAME

    physai_cli.run("build", str(container), "--rebuild")
    before = physai_session.run(
        f"stat -c %Y /fsx/enroot/{FAKE_BUILD_NAME}.sqsh"
    ).strip()

    # `stat -c %Y` is whole seconds. Sleep over the boundary so a successful
    # rebuild is observable.
    time.sleep(2)

    physai_cli.run("build", str(container), "--rebuild")
    after = physai_session.run(f"stat -c %Y /fsx/enroot/{FAKE_BUILD_NAME}.sqsh").strip()
    assert int(after) > int(before), (
        f"/fsx/enroot/{FAKE_BUILD_NAME}.sqsh mtime did not advance "
        f"({before} → {after}) after a second --rebuild."
    )
