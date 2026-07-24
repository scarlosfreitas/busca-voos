"""Integration tests for the repositories against a real Postgres.

Skipped automatically when no database is reachable (see the ``pg_connection``
fixture in ``conftest.py``). When a database *is* available and dev-runner has
implemented the repositories, these assert the round-trip contract of each
Medallion layer, with special focus on
``GoldRepository.last_alerted_prices`` — the mapping the deduplication rule
consumes.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.deduplication import select_flights_to_notify
from domain.models import Alert
from persistence.repositories import (
    BronzeRepository,
    GoldRepository,
    SilverRepository,
)

from .conftest import MONITORED_ROUTE, make_flight

_NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


class TestBronzeRepository:
    def test_save_success_payload_returns_id(self, pg_connection) -> None:
        repo = BronzeRepository(pg_connection)
        row_id = repo.save_raw_response(
            execution_id=uuid4(),
            route=MONITORED_ROUTE,
            captured_at=_NOW,
            success=True,
            payload={"trips": [{"flightNumber": "G3-1234"}]},
        )
        assert isinstance(row_id, int)

    def test_save_failure_allows_null_payload(self, pg_connection) -> None:
        repo = BronzeRepository(pg_connection)
        row_id = repo.save_raw_response(
            execution_id=uuid4(),
            route=MONITORED_ROUTE,
            captured_at=_NOW,
            success=False,
            payload=None,
            error_message="timeout",
        )
        assert isinstance(row_id, int)


class TestSilverRepository:
    def test_save_flights_returns_one_id_per_flight_in_order(
        self, pg_connection
    ) -> None:
        repo = SilverRepository(pg_connection)
        flights = [
            make_flight(flight_number="G3-1000", departure_time=time(6, 0)),
            make_flight(flight_number="G3-2000", departure_time=time(9, 30)),
        ]
        ids = repo.save_flights(execution_id=uuid4(), captured_at=_NOW, flights=flights)
        assert len(ids) == 2

    def test_save_empty_flights_returns_empty(self, pg_connection) -> None:
        repo = SilverRepository(pg_connection)
        assert (
            repo.save_flights(execution_id=uuid4(), captured_at=_NOW, flights=[]) == []
        )


class TestGoldRepository:
    def test_record_alerts_returns_ids(self, pg_connection) -> None:
        repo = GoldRepository(pg_connection)
        alert = Alert(
            flight_id="MCP-BSB-2026-09-01-G3-1234",
            price=Decimal("1000.00"),
            currency="BRL",
            alerted_at=_NOW,
        )
        ids = repo.record_alerts(execution_id=uuid4(), alerts=[alert])
        assert len(ids) == 1

    def test_last_alerted_prices_empty_when_no_history(self, pg_connection) -> None:
        repo = GoldRepository(pg_connection)
        assert repo.last_alerted_prices(MONITORED_ROUTE) == {}

    def test_last_alerted_prices_returns_most_recent_price_per_flight(
        self, pg_connection
    ) -> None:
        repo = GoldRepository(pg_connection)
        flight_id = "MCP-BSB-2026-09-01-G3-1234"
        older = Alert(
            flight_id=flight_id,
            price=Decimal("1200.00"),
            currency="BRL",
            alerted_at=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
        )
        newer = Alert(
            flight_id=flight_id,
            price=Decimal("980.00"),
            currency="BRL",
            alerted_at=datetime(2026, 7, 24, 12, 0, tzinfo=UTC),
        )
        repo.record_alerts(execution_id=uuid4(), alerts=[older])
        repo.record_alerts(execution_id=uuid4(), alerts=[newer])

        prices = repo.last_alerted_prices(MONITORED_ROUTE)
        assert prices == {flight_id: Decimal("980.00")}

    def test_last_alerted_prices_feeds_deduplication(self, pg_connection) -> None:
        # End-to-end contract: the gold mapping plugs directly into the domain
        # deduplication rule. A flight at the same last-alerted price is filtered
        # out; a changed one is kept.
        repo = GoldRepository(pg_connection)
        unchanged = make_flight(flight_number="G3-1000", price=Decimal("900.00"))
        changed = make_flight(flight_number="G3-2000", price=Decimal("700.00"))

        repo.record_alerts(
            execution_id=uuid4(),
            alerts=[
                Alert(
                    flight_id=unchanged.flight_id,
                    price=Decimal("900.00"),
                    currency="BRL",
                    alerted_at=_NOW,
                ),
                Alert(
                    flight_id=changed.flight_id,
                    price=Decimal("650.00"),
                    currency="BRL",
                    alerted_at=_NOW,
                ),
            ],
        )

        last_prices = repo.last_alerted_prices(MONITORED_ROUTE)
        to_notify = select_flights_to_notify([unchanged, changed], last_prices)
        assert to_notify == [changed]


@pytest.mark.parametrize("layer", ["bronze", "silver", "gold"])
def test_schemas_exist(pg_engine, layer: str) -> None:
    # Sanity: the Medallion schemas are present (init-db.sql / migration).
    from sqlalchemy import text

    with pg_engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
            {"s": layer},
        ).scalar()
    assert result == 1
