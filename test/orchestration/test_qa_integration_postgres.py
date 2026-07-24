"""QA-authored integration test: ``run_daily_search`` against a *real* Postgres
via the real repositories (bronze/silver/gold), with a fake capture (no
Playwright) and a fake notifier (no real Telegram) — validating that what the
pure decision logic decides is what actually lands in the database, and that
the atomicity/should_commit contract described in
``.claude/plans/2026-07-24-dev-orchestration.md`` holds for a real transaction
(not just fakes tracking calls).

Skips automatically when Postgres is unreachable (same convention as
``test/persistence/conftest.py``: ``pg_engine``/``pg_connection_qa``). Requires the
persistence-layer fixtures, so this module imports them from
``test.persistence.conftest``.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from extraction.errors import BlockedError
from orchestration.assets import run_daily_search
from persistence.repositories import BronzeRepository, GoldRepository, SilverRepository

from .conftest import (
    MONITORED_ROUTE,
    RUN_NOW,
    FakeLogger,
    FakeNotifier,
    capture_raising,
    capture_returning,
    make_capture_result,
    make_captured,
)


def _row_counts(conn) -> dict[str, int]:
    return {
        "bronze": conn.execute(
            text("SELECT count(*) FROM bronze.raw_search_response")
        ).scalar_one(),
        "silver": conn.execute(text("SELECT count(*) FROM silver.flight")).scalar_one(),
        "gold": conn.execute(
            text("SELECT count(*) FROM gold.flight_alert")
        ).scalar_one(),
    }


class TestSuccessEndToEnd:
    def test_new_flight_lands_in_bronze_silver_gold(self, pg_connection_qa) -> None:
        before = _row_counts(pg_connection_qa)

        captured = make_captured(flight_number="9999", price=Decimal("777.00"))
        bronze = BronzeRepository(pg_connection_qa)
        silver = SilverRepository(pg_connection_qa)
        gold = GoldRepository(pg_connection_qa)
        notifier = FakeNotifier()

        outcome = run_daily_search(
            route=MONITORED_ROUTE,
            search_date=RUN_NOW.date(),
            capture=capture_returning(make_capture_result(captured)),
            bronze=bronze,
            silver=silver,
            gold=gold,
            notify=notifier,
            logger=FakeLogger(),
            execution_id=uuid4(),
            now=RUN_NOW,
        )

        assert outcome.status.name == "SUCCESS_ALERTED"
        assert len(notifier.sent) == 1

        after = _row_counts(pg_connection_qa)
        assert after["bronze"] == before["bronze"] + 1
        assert after["silver"] == before["silver"] + 1
        assert after["gold"] == before["gold"] + 1

        row = pg_connection_qa.execute(
            text(
                "SELECT flight_id, price FROM gold.flight_alert "
                "ORDER BY id DESC LIMIT 1"
            )
        ).one()
        assert row.flight_id == "MCP-BSB-2026-09-01-G3-9999"
        assert row.price == Decimal("777.00")


class TestAtomicityOfDownstreamFailure:
    """Confirms the spec's own decision (plan §"Atomicidade da persistência (e)"):
    a downstream (silver/gold) failure rolls back the *entire* transaction,
    including the bronze row written earlier in the same run — because the shell
    owns one transaction and commits/rolls back based on ``should_commit``.

    This directly tests the "does the bronze marker survive a downstream
    failure" question: per the documented design, it does **not** survive when
    the failure is a *persistence* failure (edge e, ``should_commit=False``); it
    only survives for an *extraction* failure (edge d, ``should_commit=True``,
    no downstream write is attempted at all).
    """

    def test_silver_failure_rolls_back_bronze_too_when_shell_honors_should_commit(
        self, pg_connection_qa
    ) -> None:
        before = _row_counts(pg_connection_qa)

        class RaisingSilver(SilverRepository):
            def save_flights(self, **kwargs):
                raise RuntimeError("simulated silver outage")

        captured = make_captured(flight_number="1111", price=Decimal("111.00"))
        bronze = BronzeRepository(pg_connection_qa)
        silver = RaisingSilver(pg_connection_qa)
        gold = GoldRepository(pg_connection_qa)

        # Use a savepoint so we can inspect post-run state without losing the
        # outer pg_connection_qa's own rollback-on-teardown behavior.
        nested = pg_connection_qa.begin_nested()
        outcome = run_daily_search(
            route=MONITORED_ROUTE,
            search_date=RUN_NOW.date(),
            capture=capture_returning(make_capture_result(captured)),
            bronze=bronze,
            silver=silver,
            gold=gold,
            notify=FakeNotifier(),
            logger=FakeLogger(),
            execution_id=uuid4(),
            now=RUN_NOW,
        )

        assert outcome.status.name == "FAILED_PERSISTENCE"
        assert outcome.should_commit is False

        # The bronze write DID happen against the connection (nothing in
        # run_daily_search rolled it back itself - it returns should_commit and
        # trusts the shell). If the shell (as documented) rolls back the whole
        # transaction, the bronze row must disappear too.
        mid = _row_counts(pg_connection_qa)
        assert mid["bronze"] == before["bronze"] + 1  # visible before shell rollback

        nested.rollback()  # simulate the thin shell's rollback of should_commit=False

        after = _row_counts(pg_connection_qa)
        assert after["bronze"] == before["bronze"]  # gone: whole-transaction rollback
        assert after["silver"] == before["silver"]
        assert after["gold"] == before["gold"]


class TestExtractionFailureMarkerSurvives:
    def test_bronze_failure_marker_is_the_only_write_and_survives_commit(
        self, pg_connection_qa
    ) -> None:
        before = _row_counts(pg_connection_qa)
        bronze = BronzeRepository(pg_connection_qa)
        silver = SilverRepository(pg_connection_qa)
        gold = GoldRepository(pg_connection_qa)

        nested = pg_connection_qa.begin_nested()
        outcome = run_daily_search(
            route=MONITORED_ROUTE,
            search_date=RUN_NOW.date(),
            capture=capture_raising(BlockedError("blocked")),
            bronze=bronze,
            silver=silver,
            gold=gold,
            notify=FakeNotifier(),
            logger=FakeLogger(),
            execution_id=uuid4(),
            now=RUN_NOW,
        )

        assert outcome.status.name == "FAILED_EXTRACTION"
        assert outcome.should_commit is True
        nested.commit()  # simulate the shell honoring should_commit=True

        after = _row_counts(pg_connection_qa)
        assert after["bronze"] == before["bronze"] + 1
        assert after["silver"] == before["silver"]
        assert after["gold"] == before["gold"]

        row = pg_connection_qa.execute(
            text(
                "SELECT success, error_message FROM bronze.raw_search_response "
                "ORDER BY id DESC LIMIT 1"
            )
        ).one()
        assert row.success is False
        assert "blocked" in row.error_message.lower()
