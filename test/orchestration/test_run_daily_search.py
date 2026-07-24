"""Unit tests for the pure orchestration decision logic (``run_daily_search``).

Drives :func:`orchestration.run_daily_search` with the in-memory fakes from
``conftest.py`` and asserts, for every business edge case, *what got persisted*,
*what got notified*, the returned :class:`RunOutcome`, and — critically — that the
function is **total** (never raises for a handled failure mode; the process is
never crashed unobservably, ``architecture.md`` §6).

Every case is traceable 1:1 with ``docs/domain/regras_negocio.md``. Today they
fail with ``NotImplementedError`` (correct reason: missing implementation).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from extraction.errors import (
    BlockedError,
    ExtractionTimeoutError,
    MalformedPayloadError,
)
from orchestration.assets import RunStatus, run_daily_search

from .conftest import (
    MONITORED_ROUTE,
    RUN_NOW,
    SEARCH_DATE,
    FakeBronze,
    FakeGold,
    FakeLogger,
    FakeNotifier,
    FakeSilver,
    capture_raising,
    capture_returning,
    make_capture_result,
    make_captured,
)


def _run(
    *,
    capture,
    bronze=None,
    silver=None,
    gold=None,
    notifier=None,
    logger=None,
    execution_id,
):
    bronze = bronze if bronze is not None else FakeBronze()
    silver = silver if silver is not None else FakeSilver()
    gold = gold if gold is not None else FakeGold()
    notifier = notifier if notifier is not None else FakeNotifier()
    logger = logger if logger is not None else FakeLogger()
    outcome = run_daily_search(
        route=MONITORED_ROUTE,
        search_date=SEARCH_DATE,
        capture=capture,
        bronze=bronze,
        silver=silver,
        gold=gold,
        notify=notifier,
        logger=logger,
        execution_id=execution_id,
        now=RUN_NOW,
    )
    return outcome, bronze, silver, gold, notifier, logger


# ── Edge (a): success, zero eligible flights → no notification ──────────────────


def test_a_empty_capture_persists_bronze_and_sends_nothing(execution_id) -> None:
    outcome, bronze, _silver, gold, notifier, _ = _run(
        capture=capture_returning(make_capture_result()),  # no flights
        execution_id=execution_id,
    )

    assert outcome.status is RunStatus.SUCCESS_NO_ALERT
    assert outcome.should_commit is True
    assert not outcome.is_failure
    # Bronze persisted as a successful run; nothing notified; gold untouched.
    assert len(bronze.calls) == 1 and bronze.calls[0]["success"] is True
    assert notifier.sent == []
    assert gold.recorded == []


# ── Edge (b): eligible flights, all deduplicated (price unchanged) → no alert ────


def test_b_all_deduplicated_sends_nothing(execution_id) -> None:
    captured = make_captured(flight_number="1234", price=Decimal("1234.56"))
    gold = FakeGold(prices={"MCP-BSB-2026-09-01-G3-1234": Decimal("1234.56")})

    outcome, _, silver, gold, notifier, _ = _run(
        capture=capture_returning(make_capture_result(captured)),
        gold=gold,
        execution_id=execution_id,
    )

    assert outcome.status is RunStatus.SUCCESS_NO_ALERT
    assert outcome.notified_count == 0
    assert notifier.sent == []
    assert gold.recorded == []  # unchanged price → no new alert appended
    # The flight was still captured/normalized into silver (retention).
    assert silver.calls and len(silver.calls[0]) == 1


# ── Edge (c): new/changed flight → one alert + gold updated ─────────────────────


def test_c_new_flight_sends_alert_and_records_gold(execution_id) -> None:
    captured = make_captured(flight_number="1234", price=Decimal("999.00"))

    outcome, _, _, gold, notifier, _ = _run(
        capture=capture_returning(make_capture_result(captured)),
        gold=FakeGold(prices={}),  # never alerted before → first occurrence
        execution_id=execution_id,
    )

    assert outcome.status is RunStatus.SUCCESS_ALERTED
    assert outcome.notified_count == 1
    assert len(notifier.sent) == 1  # exactly one flight-alert message
    # Gold records the effectively-sent alert (the new "último preço alertado").
    assert len(gold.recorded) == 1
    assert gold.recorded[0].flight_id == "MCP-BSB-2026-09-01-G3-1234"
    assert gold.recorded[0].price == Decimal("999.00")


def test_c_changed_price_sends_alert(execution_id) -> None:
    captured = make_captured(flight_number="1234", price=Decimal("800.00"))
    gold = FakeGold(prices={"MCP-BSB-2026-09-01-G3-1234": Decimal("1234.56")})

    outcome, _, _, gold, notifier, _ = _run(
        capture=capture_returning(make_capture_result(captured)),
        gold=gold,
        execution_id=execution_id,
    )

    assert outcome.status is RunStatus.SUCCESS_ALERTED
    assert len(notifier.sent) == 1
    assert gold.recorded[0].price == Decimal("800.00")


# ── Edge (d): extraction failure → failure notification, no flight data ─────────


@pytest.mark.parametrize(
    "error",
    [
        BlockedError("blocked"),
        ExtractionTimeoutError("timed out"),
        MalformedPayloadError("bad record"),
    ],
)
def test_d_extraction_failure_notifies_and_writes_no_flight_data(
    error, execution_id
) -> None:
    outcome, bronze, silver, gold, notifier, logger = _run(
        capture=capture_raising(error),
        execution_id=execution_id,
    )

    assert outcome.status is RunStatus.FAILED_EXTRACTION
    assert outcome.is_failure
    assert outcome.error is error
    # A failure notification was sent...
    assert len(notifier.sent) == 1
    # ...no silver/gold flight data was written for this failed run...
    assert silver.calls == []
    assert gold.recorded == []
    # ...but the failure is recorded in bronze as a failure marker (success=False).
    assert len(bronze.calls) == 1 and bronze.calls[0]["success"] is False
    assert logger.errors  # the failure was logged


# ── Edge (e): persistence failure → failure notification, roll back ─────────────


def test_e_silver_write_failure_notifies_and_rolls_back(execution_id) -> None:
    captured = make_captured(flight_number="1234", price=Decimal("500.00"))
    silver = FakeSilver(raise_on_call=RuntimeError("db down"))

    outcome, _, silver, gold, notifier, logger = _run(
        capture=capture_returning(make_capture_result(captured)),
        silver=silver,
        execution_id=execution_id,
    )

    assert outcome.status is RunStatus.FAILED_PERSISTENCE
    assert outcome.is_failure
    assert outcome.should_commit is False  # shell rolls back → no partial data
    assert len(notifier.sent) == 1  # error notification sent
    assert gold.recorded == []
    assert logger.errors


def test_e_bronze_write_failure_notifies_and_rolls_back(execution_id) -> None:
    captured = make_captured(flight_number="1234", price=Decimal("500.00"))
    bronze = FakeBronze(raise_on_call=RuntimeError("db down"))

    outcome, bronze, _, _, notifier, _ = _run(
        capture=capture_returning(make_capture_result(captured)),
        bronze=bronze,
        execution_id=execution_id,
    )

    assert outcome.status is RunStatus.FAILED_PERSISTENCE
    assert outcome.should_commit is False
    assert len(notifier.sent) == 1


# ── Edge (f): error-notification failure → logged, never re-raised ──────────────


def test_f_failure_notification_failure_is_logged_not_raised(execution_id) -> None:
    # Extraction fails AND the Telegram send of the error message also fails.
    notifier = FakeNotifier(raise_on_send_number=1)

    outcome, _, _, _, notifier, logger = _run(
        capture=capture_raising(BlockedError("blocked")),
        notifier=notifier,
        execution_id=execution_id,
    )

    # The point: run_daily_search returned normally (no exception escaped) ...
    assert outcome.status is RunStatus.FAILED_EXTRACTION
    # ... the send was attempted ...
    assert len(notifier.sent) == 1
    # ... and the delivery failure is observable in the logs, not swallowed.
    assert logger.errors


# ── Bonus: flight-alert delivery failure → gold not updated, not fatal crash ────


def test_alert_delivery_failure_withholds_gold(execution_id) -> None:
    captured = make_captured(flight_number="1234", price=Decimal("999.00"))
    notifier = FakeNotifier(raise_on_send_number=1)  # the alert send fails

    outcome, _, _, gold, notifier, logger = _run(
        capture=capture_returning(make_capture_result(captured)),
        gold=FakeGold(prices={}),
        notifier=notifier,
        execution_id=execution_id,
    )

    assert outcome.status is RunStatus.FAILED_NOTIFICATION
    # Gold must NOT be updated when the alert wasn't effectively sent, so the next
    # run retries (regras_negocio.md — "último preço alertado" = efetivamente enviado).
    assert gold.recorded == []
    assert logger.errors


# ── Totality guard: an already-notified run never touches gold twice ────────────


def test_success_no_alert_never_records_gold(execution_id) -> None:
    """Both edge (a) and (b) leave gold untouched — a single assertion of intent."""
    captured = make_captured(flight_number="1234", price=Decimal("1234.56"))
    gold = FakeGold(prices={"MCP-BSB-2026-09-01-G3-1234": Decimal("1234.56")})

    outcome, _, _, gold, _, _ = _run(
        capture=capture_returning(make_capture_result(captured)),
        gold=gold,
        execution_id=execution_id,
    )
    assert outcome.status is RunStatus.SUCCESS_NO_ALERT
    assert gold.recorded == []
