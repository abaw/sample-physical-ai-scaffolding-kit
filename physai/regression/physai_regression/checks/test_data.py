"""Data-management checks: upload/list/remove and S3 → FSx auto-import (DRA)."""

import subprocess
import time
from datetime import datetime

import pytest

from physai_regression.orchestration.deploy import aws_cli_args

DATASET_NAME = "regression-roundtrip"
RAW_NAME = "regression-dra"


@pytest.mark.platform
def test_dataset_round_trip(physai_session, physai_cli, tmp_path) -> None:
    """``physai upload datasets`` → ``physai ls datasets`` → ``physai rm datasets``."""
    src = tmp_path / DATASET_NAME
    src.mkdir()
    (src / "marker.txt").write_text("regression\n")
    target = f"/fsx/datasets/{DATASET_NAME}"

    # Pre-clean in case a previous run died mid-test. `rm -rf` on a
    # nonexistent path is a no-op.
    physai_session.run(f"rm -rf {target}")

    try:
        physai_cli.run("upload", "datasets", str(src))
        listing = physai_cli.run("ls", "datasets").stdout
        assert DATASET_NAME in listing, (
            f"`physai ls datasets` did not include {DATASET_NAME}.\nstdout:\n{listing}"
        )
        # Verify the file is actually on FSx — `physai ls` listing is
        # only a partial proof.
        assert "regression" in physai_session.run(f"cat {target}/marker.txt")

        physai_cli.run("rm", "datasets", DATASET_NAME, "--force")
        post = physai_session.run(f"test -e {target} && echo present || echo absent")
        assert post.strip() == "absent", (
            f"`physai rm datasets {DATASET_NAME}` left {target} behind."
        )
    finally:
        physai_session.run(f"rm -rf {target}")


@pytest.mark.platform
def test_s3_dra_lazy_load(
    physai_cli,
    data_bucket_name,
    aws_profile,
    aws_region,
    tmp_path,
) -> None:
    """File uploaded to ``s3://<bucket>/raw/<name>/`` appears under ``physai ls raw``.

    FSx Lustre's Data Repository Association links ``s3://<bucket>/raw/`` to
    ``/fsx/raw/``; new keys appear in the namespace via auto-import (lazy
    metadata sync, file content lazy-loaded on first read). The check
    asserts the namespace import — not content load — because hitting Lustre
    pulls bytes which is more disruptive than necessary for a smoke check.

    The marker filename is per-run-unique and the poll looks for that file
    *inside* ``/fsx/raw/<RAW_NAME>/`` (``physai ls raw <RAW_NAME>``), not for
    the directory ``RAW_NAME`` itself. A leftover ``RAW_NAME`` directory from
    a prior run whose S3 deletion hasn't yet propagated would otherwise make
    the check pass instantly without the new key ever being auto-imported —
    i.e. pass even if auto-import were broken.
    """
    marker = f"marker-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    src = tmp_path / marker
    src.write_text("regression-dra-marker\n")
    s3_uri = f"s3://{data_bucket_name}/raw/{RAW_NAME}/{marker}"

    # Pre-clean S3 only. /fsx/raw/ is a DRA-imported tree where the file
    # mode reflects the S3 object's read-only-ness — `rm -rf` against it as
    # the unprivileged ssh user fails with "Permission denied" on prior
    # files. The FSx namespace entry follows the S3 deletion via DRA sync.
    subprocess.run(
        [
            "aws",
            *aws_cli_args(aws_profile, aws_region),
            "s3",
            "rm",
            "--recursive",
            f"s3://{data_bucket_name}/raw/{RAW_NAME}/",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    try:
        # Use the same --metadata flags `physai upload raw` recommends to
        # users: imports the file as ubuntu:ubuntu (UID/GID 1000) so the
        # downstream pipeline can read+write without sudo. (The
        # DRA-synthesized parent directory `/fsx/raw/<name>/` is still
        # root:0755 — that's a DRA-side limitation; this test cleans up
        # via S3 deletion which DRA propagates back to the FSx namespace.)
        cp_cmd = [
            "aws",
            *aws_cli_args(aws_profile, aws_region),
            "s3",
            "cp",
            "--metadata",
            "file-owner=1000,file-group=1000",
            str(src),
            s3_uri,
        ]
        r = subprocess.run(cp_cmd, capture_output=True, text=True, check=False)
        assert r.returncode == 0, f"`aws s3 cp` failed: stderr={r.stderr.strip()}"

        # DRA auto-import is async — usually within seconds, occasionally
        # longer. Poll for the *new marker file* inside the prefix (not the
        # prefix directory itself) so a stale leftover dir can't false-pass.
        deadline = time.time() + 60
        seen = ""
        while time.time() < deadline:
            # check=False: the prefix dir may not exist yet on the first
            # polls; `physai ls raw <name>` simply lists empty then.
            seen = physai_cli.run("ls", "raw", RAW_NAME, check=False).stdout
            if marker in seen:
                break
            time.sleep(2)
        assert marker in seen, (
            f"`physai ls raw {RAW_NAME}` did not show {marker} within 60s "
            f"(auto-import of the new key did not propagate).\nlast stdout:\n{seen}"
        )
    finally:
        # S3 is the source of truth for /fsx/raw/ — DRA auto-syncs
        # deletions to the FSx namespace. We don't `rm -rf` the FSx path
        # because DRA-imported files are not deletable from FSx as the
        # unprivileged ssh user.
        subprocess.run(
            [
                "aws",
                *aws_cli_args(aws_profile, aws_region),
                "s3",
                "rm",
                "--recursive",
                f"s3://{data_bucket_name}/raw/{RAW_NAME}/",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
