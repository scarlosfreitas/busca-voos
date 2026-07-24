"""Orchestration layer: the daily Dagster job that glues every layer together.

Public surface re-exported for Dagster (``defs``) and for the unit tests that
exercise the pure decision logic. See ``src/orchestration/assets.py`` for the
full contract: the pure, dependency-injected :func:`run_daily_search` (plus its
mapping helpers) and the thin Dagster asset/job/schedule shell.
"""

from __future__ import annotations

from orchestration.assets import (
    CARRIER_NAMES,
    DAILY_CRON,
    MONITORED_ROUTE,
    BronzeWriter,
    CaptureFn,
    GoldStore,
    Notifier,
    PipelineLogger,
    RunOutcome,
    RunStatus,
    SilverWriter,
    TelegramNotifier,
    build_alert,
    capture_sync,
    captured_to_flight,
    daily_flight_search,
    daily_flight_search_job,
    daily_flight_search_schedule,
    defs,
    run_daily_search,
    to_valid_flights,
)

__all__ = [
    "CARRIER_NAMES",
    "DAILY_CRON",
    "MONITORED_ROUTE",
    "BronzeWriter",
    "CaptureFn",
    "GoldStore",
    "Notifier",
    "PipelineLogger",
    "RunOutcome",
    "RunStatus",
    "SilverWriter",
    "TelegramNotifier",
    "build_alert",
    "capture_sync",
    "captured_to_flight",
    "daily_flight_search",
    "daily_flight_search_job",
    "daily_flight_search_schedule",
    "defs",
    "run_daily_search",
    "to_valid_flights",
]
