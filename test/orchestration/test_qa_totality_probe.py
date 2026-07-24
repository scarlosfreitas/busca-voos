"""QA-authored probe (not part of dev-runner's spec): confirms whether
``run_daily_search`` is truly total when a collaborator raises a *generic*,
unexpected exception (not ExtractionError/NotificationError) at points the
spec's own test suite doesn't cover: ``gold.last_alerted_prices`` and
``gold.record_alerts``.

Temporary QA artifact used to gather evidence for the validation report; not
meant to remain as part of the permanent suite ownership boundary (dev-planner
owns test/orchestration's contract). Kept in test/ per QA's write scope.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from orchestration.assets import run_daily_search

from .conftest import (
    MONITORED_ROUTE,
    RUN_NOW,
    SEARCH_DATE,
    FakeBronze,
    FakeGold,
    FakeLogger,
    FakeNotifier,
    FakeSilver,
    capture_returning,
    make_capture_result,
    make_captured,
)


class RaisingLastAlertedGold(FakeGold):
    def last_alerted_prices(self, route):
        raise RuntimeError("gold read exploded unexpectedly (not a domain error)")


class RaisingRecordGold(FakeGold):
    def record_alerts(self, *, execution_id, alerts):
        raise RuntimeError("gold write exploded unexpectedly (not a domain error)")


def test_qa_totality_gold_read_generic_exception_must_not_escape():
    captured = make_captured(flight_number="1234", price=Decimal("999.00"))
    outcome = run_daily_search(
        route=MONITORED_ROUTE,
        search_date=SEARCH_DATE,
        capture=capture_returning(make_capture_result(captured)),
        bronze=FakeBronze(),
        silver=FakeSilver(),
        gold=RaisingLastAlertedGold(),
        notify=FakeNotifier(),
        logger=FakeLogger(),
        execution_id=uuid4(),
        now=RUN_NOW,
    )
    assert outcome.is_failure


def test_qa_totality_gold_record_alerts_generic_exception_must_not_escape():
    captured = make_captured(flight_number="1234", price=Decimal("999.00"))
    outcome = run_daily_search(
        route=MONITORED_ROUTE,
        search_date=SEARCH_DATE,
        capture=capture_returning(make_capture_result(captured)),
        bronze=FakeBronze(),
        silver=FakeSilver(),
        gold=RaisingRecordGold(prices={}),
        notify=FakeNotifier(),
        logger=FakeLogger(),
        execution_id=uuid4(),
        now=RUN_NOW,
    )
    assert outcome.is_failure
