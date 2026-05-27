"""Tests for ``test_dcvagent_process_running``.

These tests parse-check the output the check expects from ``srun``. They
do NOT touch AWS or SSH — `physai_session` is replaced with a fake whose
``run`` method returns canned strings for each command the check issues.
"""

from unittest.mock import MagicMock

import pytest

from physai_regression.checks.test_dcv_state import (
    test_dcvagent_process_running as dcvagent_check,
)


def _fake_session(hosts: list[str], srun_output: str):
    """Return a MagicMock whose `.run` first returns the sinfo nodelist, then srun output."""
    s = MagicMock()
    s.run.side_effect = [",".join(hosts), srun_output]
    return s


def test_passes_when_every_node_reports_ok():
    s = _fake_session(
        ["ip-10-0-1-1", "ip-10-0-1-2"],
        "0: ip-10-0-1-1:OK\n1: ip-10-0-1-2:OK\n",
    )
    dcvagent_check(s)


def test_fails_when_a_node_is_missing_dcvagent():
    s = _fake_session(
        ["ip-10-0-1-1", "ip-10-0-1-2"],
        "0: ip-10-0-1-1:OK\n1: ip-10-0-1-2:MISSING\n",
    )
    with pytest.raises(AssertionError) as excinfo:
        dcvagent_check(s)
    msg = str(excinfo.value)
    assert "ip-10-0-1-2" in msg
    assert "ip-10-0-1-1" not in msg


def test_fails_when_no_schedulable_nodes():
    s = _fake_session([], "")
    with pytest.raises(AssertionError) as excinfo:
        dcvagent_check(s)
    assert "No schedulable GPU nodes" in str(excinfo.value)


def test_fails_when_a_node_drops_off_silently():
    """3 nodes expected, but only 2 lines come back — the third never reported."""
    s = _fake_session(
        ["ip-10-0-1-1", "ip-10-0-1-2", "ip-10-0-1-3"],
        "0: ip-10-0-1-1:OK\n1: ip-10-0-1-2:OK\n",
    )
    with pytest.raises(AssertionError) as excinfo:
        dcvagent_check(s)
    assert "Expected 3" in str(excinfo.value)


def test_propagates_srun_allocation_failure():
    """If srun fails (e.g. --immediate timed out because a node went unavailable),
    Session.run raises RuntimeError; the check must not swallow it."""
    s = MagicMock()
    s.run.side_effect = [
        "ip-10-0-1-1,ip-10-0-1-2",
        RuntimeError(
            "srun: error: Unable to allocate resources: "
            "Requested node configuration is not available"
        ),
    ]
    with pytest.raises(RuntimeError, match="Unable to allocate resources"):
        dcvagent_check(s)


def test_handles_srun_output_without_label_prefix():
    """Defensive: if --label gets stripped or reordered, plain `host:OK` lines still parse."""
    s = _fake_session(
        ["ip-10-0-1-1", "ip-10-0-1-2"],
        "ip-10-0-1-1:OK\nip-10-0-1-2:OK\n",
    )
    dcvagent_check(s)
