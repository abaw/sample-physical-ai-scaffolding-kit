"""Composed orchestration sequences used by lifecycle modes.

Each function is a thin sequence of :mod:`deploy` primitives. Modes call
these so the pytest-side code stays focused on running checks.
"""

from . import deploy


def fresh_prepare(profile: str | None, region: str | None) -> None:
    """Bring up a fresh ``PhysaiClusterStack`` from a clean slate.

    Destroys an existing stack first so the deploy provisions every node
    via the lifecycle scripts in their initial-bootstrap path. This is the
    case that catches the kind of regressions a re-run on a long-lived dev
    cluster does not (missing FSx dirs, services that only autostart on
    first boot, etc.).
    """
    deploy.cdk_destroy(profile=profile, region=region, skip_if_absent=True)
    deploy.cdk_deploy(profile=profile, region=region)


def fresh_teardown(profile: str | None, region: str | None) -> None:
    """Destroy ``PhysaiClusterStack`` after a successful fresh run."""
    deploy.cdk_destroy(profile=profile, region=region, skip_if_absent=True)
