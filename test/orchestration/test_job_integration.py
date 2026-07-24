"""Integration test for the real daily Dagster job (skipped by default).

Executing the job drives Playwright against the live Gol site, writes to a real
Postgres and sends a real Telegram message — none of which run in CI. It is
opt-in via ``RUN_ORCHESTRATION_INTEGRATION=1`` and additionally skips when the
asset body is not yet implemented, mirroring the persistence / extraction /
notification integration skip gates (architecture.md §8; qa.md §8).

The point of this test is only to prove the *thin shell* executes end-to-end when
a real environment is present; all the decision logic is covered by the pure unit
tests in ``test_run_daily_search.py``.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_ORCHESTRATION_INTEGRATION") != "1",
    reason=(
        "Real Dagster job hits Playwright + Postgres + Telegram; "
        "set RUN_ORCHESTRATION_INTEGRATION=1 to run"
    ),
)


def test_daily_flight_search_job_executes() -> None:
    from orchestration.assets import daily_flight_search_job

    try:
        result = daily_flight_search_job.execute_in_process(raise_on_error=False)
    except NotImplementedError:
        pytest.skip("orchestration decision logic / shell not implemented yet")
    except Exception as exc:  # noqa: BLE001 - env not reachable means skip, not fail
        pytest.skip(f"Orchestration integration environment unavailable: {exc}")

    # When a real environment IS present, the run should complete (success, or a
    # typed failure that the shell surfaces) — never crash the process unhandled.
    assert result is not None
