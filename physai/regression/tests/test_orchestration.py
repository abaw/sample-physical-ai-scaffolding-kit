"""Tests for ``physai_regression.orchestration``.

The orchestration primitives wrap ``subprocess.run`` calls to the AWS CLI
and ``npx cdk``. These tests mock that boundary so the wiring is checked
without invoking AWS or CDK.
"""

from unittest.mock import MagicMock, patch

import pytest

from physai_regression.orchestration import deploy, stages


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _flag_value(cmd: list[str], flag: str) -> str:
    """Return the argv element immediately following ``flag``.

    Asserts adjacency so a regression that emits ``--profile r --region p``
    (values swapped) is caught — plain ``"p" in cmd`` membership would not.
    """
    assert flag in cmd, f"{flag} not in {cmd}"
    return cmd[cmd.index(flag) + 1]


# ── aws_cli_args ──────────────────────────────────────────────────────────


def test_aws_cli_args_includes_only_set_values():
    assert deploy.aws_cli_args(None, None) == []
    assert deploy.aws_cli_args("p", None) == ["--profile", "p"]
    assert deploy.aws_cli_args(None, "r") == ["--region", "r"]
    assert deploy.aws_cli_args("p", "r") == ["--profile", "p", "--region", "r"]


# ── describe_stack ────────────────────────────────────────────────────────


def test_describe_stack_returns_stripped_output():
    with patch(
        "physai_regression.orchestration.deploy.subprocess.run",
        return_value=_completed(stdout="CREATE_COMPLETE\n"),
    ) as run:
        out = deploy.describe_stack("PhysaiClusterStack", "Stacks[0].StackStatus")
    assert out == "CREATE_COMPLETE"
    cmd = run.call_args.args[0]
    assert cmd[0] == "aws"
    assert "describe-stacks" in cmd
    assert "PhysaiClusterStack" in cmd


def test_describe_stack_normalizes_None_to_empty():
    with patch(
        "physai_regression.orchestration.deploy.subprocess.run",
        return_value=_completed(stdout="None\n"),
    ):
        assert deploy.describe_stack("X", "Stacks[0].Outputs[?Foo]") == ""


def test_describe_stack_raises_StackNotFound_when_stack_absent():
    """CloudFormation's "does not exist" ValidationError → StackNotFound."""
    with patch(
        "physai_regression.orchestration.deploy.subprocess.run",
        return_value=_completed(
            returncode=255,
            stderr=(
                "An error occurred (ValidationError) when calling the "
                "DescribeStacks operation: Stack with id X does not exist"
            ),
        ),
    ):
        with pytest.raises(deploy.StackNotFound, match="does not exist"):
            deploy.describe_stack("X", "Stacks[0].StackStatus")


def test_describe_stack_raises_StackQueryError_on_non_absence_failure():
    """Auth/network/throttle failures must NOT be mistaken for absence."""
    with patch(
        "physai_regression.orchestration.deploy.subprocess.run",
        return_value=_completed(
            returncode=255,
            stderr=(
                "An error occurred (ExpiredToken) when calling the "
                "DescribeStacks operation: The security token has expired"
            ),
        ),
    ):
        with pytest.raises(deploy.StackQueryError, match="ExpiredToken"):
            deploy.describe_stack("X", "Stacks[0].StackStatus")


# ── stack_exists ──────────────────────────────────────────────────────────


def test_stack_exists_returns_true_for_running_stack():
    with patch(
        "physai_regression.orchestration.deploy.describe_stack",
        return_value="CREATE_COMPLETE",
    ) as ds:
        assert (
            deploy.stack_exists("PhysaiClusterStack", profile="p", region="r") is True
        )
    # Pin the status query, not just the kwargs — a JMESPath regression
    # (e.g. querying the wrong field) would otherwise pass.
    assert ds.call_args.args == ("PhysaiClusterStack", "Stacks[0].StackStatus")
    assert ds.call_args.kwargs == {"profile": "p", "region": "r"}


def test_stack_exists_returns_false_when_stack_absent():
    """Genuine absence → describe_stack raises StackNotFound → False."""
    with patch(
        "physai_regression.orchestration.deploy.describe_stack",
        side_effect=deploy.StackNotFound("does not exist"),
    ):
        assert deploy.stack_exists("PhysaiClusterStack") is False


def test_stack_exists_propagates_query_error_rather_than_reporting_absent():
    """A StackQueryError must propagate so cdk_destroy doesn't silently skip
    and leak a live stack when CloudFormation is merely unreachable."""
    with patch(
        "physai_regression.orchestration.deploy.describe_stack",
        side_effect=deploy.StackQueryError("ExpiredToken"),
    ):
        with pytest.raises(deploy.StackQueryError):
            deploy.stack_exists("PhysaiClusterStack")


def test_stack_exists_returns_false_for_delete_complete():
    with patch(
        "physai_regression.orchestration.deploy.describe_stack",
        return_value="DELETE_COMPLETE",
    ):
        assert deploy.stack_exists("PhysaiClusterStack") is False


# ── cdk_deploy ────────────────────────────────────────────────────────────


def test_cdk_deploy_passes_profile_as_flag_and_region_via_env():
    """``cdk deploy`` silently ignores ``--region`` (aws/aws-cdk#28725).

    The region must reach the synth subprocess via ``AWS_REGION`` /
    ``AWS_DEFAULT_REGION`` so env-agnostic stacks resolve to the right
    region. ``--profile`` is documented and stays as a flag.
    """
    with patch(
        "physai_regression.orchestration.deploy.subprocess.run",
        return_value=_completed(),
    ) as run:
        deploy.cdk_deploy(profile="p", region="r")
    cmd = run.call_args.args[0]
    assert cmd[:3] == ["npx", "cdk", "deploy"]
    assert "PhysaiClusterStack" in cmd
    assert _flag_value(cmd, "--require-approval") == "never"
    assert _flag_value(cmd, "--profile") == "p"
    assert "--region" not in cmd, "--region must NOT be on the cdk argv"
    env = run.call_args.kwargs["env"]
    assert env["AWS_REGION"] == "r"
    assert env["AWS_DEFAULT_REGION"] == "r"
    assert run.call_args.kwargs["cwd"] == str(deploy.DEFAULT_INFRA_DIR)


def test_cdk_deploy_without_region_inherits_parent_env():
    """When ``region`` is not passed, the subprocess sees the parent env unchanged."""
    with (
        patch.dict(
            "os.environ",
            {"AWS_REGION": "parent-region", "AWS_DEFAULT_REGION": "parent-region"},
            clear=False,
        ),
        patch(
            "physai_regression.orchestration.deploy.subprocess.run",
            return_value=_completed(),
        ) as run,
    ):
        deploy.cdk_deploy(profile="p")
    env = run.call_args.kwargs["env"]
    assert env["AWS_REGION"] == "parent-region"
    assert env["AWS_DEFAULT_REGION"] == "parent-region"


def test_cdk_deploy_uses_provided_infra_dir(tmp_path):
    with patch(
        "physai_regression.orchestration.deploy.subprocess.run",
        return_value=_completed(),
    ) as run:
        deploy.cdk_deploy(infra_dir=tmp_path)
    assert run.call_args.kwargs["cwd"] == str(tmp_path)


def test_cdk_deploy_raises_on_nonzero_exit():
    with patch(
        "physai_regression.orchestration.deploy.subprocess.run",
        return_value=_completed(returncode=1),
    ):
        with pytest.raises(RuntimeError, match="cdk deploy"):
            deploy.cdk_deploy()


# ── cdk_destroy ───────────────────────────────────────────────────────────


def test_cdk_destroy_skips_when_stack_absent():
    with (
        patch(
            "physai_regression.orchestration.deploy.stack_exists", return_value=False
        ) as exists,
        patch("physai_regression.orchestration.deploy.subprocess.run") as run,
    ):
        deploy.cdk_destroy(profile="p", region="r")
    exists.assert_called_once()
    run.assert_not_called()


def test_cdk_destroy_runs_when_stack_present():
    with (
        patch("physai_regression.orchestration.deploy.stack_exists", return_value=True),
        patch(
            "physai_regression.orchestration.deploy.subprocess.run",
            return_value=_completed(),
        ) as run,
    ):
        deploy.cdk_destroy(profile="p", region="r")
    cmd = run.call_args.args[0]
    assert cmd[:3] == ["npx", "cdk", "destroy"]
    assert "PhysaiClusterStack" in cmd
    assert "--force" in cmd
    assert _flag_value(cmd, "--profile") == "p"
    assert "--region" not in cmd, "--region must NOT be on the cdk argv"
    env = run.call_args.kwargs["env"]
    assert env["AWS_REGION"] == "r"
    assert env["AWS_DEFAULT_REGION"] == "r"


def test_cdk_destroy_skip_if_absent_false_runs_unconditionally():
    with (
        patch("physai_regression.orchestration.deploy.stack_exists") as exists,
        patch(
            "physai_regression.orchestration.deploy.subprocess.run",
            return_value=_completed(),
        ) as run,
    ):
        deploy.cdk_destroy(skip_if_absent=False)
    exists.assert_not_called()
    run.assert_called_once()


def test_cdk_destroy_raises_on_nonzero_exit():
    with (
        patch("physai_regression.orchestration.deploy.stack_exists", return_value=True),
        patch(
            "physai_regression.orchestration.deploy.subprocess.run",
            return_value=_completed(returncode=1),
        ),
    ):
        with pytest.raises(RuntimeError, match="cdk destroy"):
            deploy.cdk_destroy()


# ── stages ────────────────────────────────────────────────────────────────


def test_fresh_prepare_destroys_then_deploys():
    with (
        patch("physai_regression.orchestration.stages.deploy.cdk_destroy") as destroy,
        patch("physai_regression.orchestration.stages.deploy.cdk_deploy") as do_deploy,
    ):
        stages.fresh_prepare(profile="p", region="r")
    destroy.assert_called_once_with(profile="p", region="r", skip_if_absent=True)
    do_deploy.assert_called_once_with(profile="p", region="r")
    # Ordering: destroy must happen before deploy.
    assert destroy.call_count == 1 and do_deploy.call_count == 1


def test_fresh_teardown_destroys_idempotently():
    with patch("physai_regression.orchestration.stages.deploy.cdk_destroy") as destroy:
        stages.fresh_teardown(profile="p", region="r")
    destroy.assert_called_once_with(profile="p", region="r", skip_if_absent=True)
