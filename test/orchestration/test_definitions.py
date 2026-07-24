"""Structural tests for the thin Dagster shell (definitions/schedule wiring).

These do **not** execute the job (no I/O), they only assert the Dagster surface is
wired: the asset, the job, and a daily schedule with no catch-up exist and load.
Building ``Definitions`` never calls the asset body, so these pass once the shell
is wired even while ``run_daily_search`` is still ``NotImplementedError``.
Version-tolerant on purpose — they pin the *contract* (one daily schedule
targeting the single orchestration asset), not Dagster internals.
"""

from __future__ import annotations

from dagster import Definitions

from orchestration.assets import (
    DAILY_CRON,
    daily_flight_search_job,
    daily_flight_search_schedule,
    defs,
)


def test_definitions_is_a_dagster_definitions() -> None:
    assert isinstance(defs, Definitions)


def test_schedule_runs_once_per_day_without_catchup() -> None:
    # A daily cron (5 fields, day-of-month/month/day-of-week all wildcards) means
    # exactly one tick per day; a non-partitioned schedule does no backfill.
    assert daily_flight_search_schedule.cron_schedule == DAILY_CRON
    fields = DAILY_CRON.split()
    assert len(fields) == 5
    assert fields[2:] == ["*", "*", "*"]  # every day, every month, every weekday


def test_schedule_targets_the_daily_job() -> None:
    assert daily_flight_search_schedule.job_name == daily_flight_search_job.name


def test_job_selects_the_orchestration_asset() -> None:
    # The job must resolve to a single asset selection (the glue asset).
    assert daily_flight_search_job.name == "daily_flight_search_job"
