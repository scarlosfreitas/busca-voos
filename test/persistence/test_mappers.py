"""Unit tests for the pure row-mapping helpers (no database).

Pin how a domain entity is projected onto a Medallion row: exact keys, exact
value types (Decimal price kept as Decimal, flight_id derived from the domain
key). dev-runner implements the bodies; these tests fail with NotImplementedError
until then.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

from domain.models import Alert
from persistence.repositories import alert_to_gold_row, flight_to_silver_row

from .conftest import make_flight

_EXECUTION_ID = UUID("11111111-1111-1111-1111-111111111111")
_CAPTURED_AT = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


class TestFlightToSilverRow:
    def test_maps_all_columns(self) -> None:
        flight = make_flight()
        row = flight_to_silver_row(
            flight, execution_id=_EXECUTION_ID, captured_at=_CAPTURED_AT
        )
        assert row == {
            "execution_id": _EXECUTION_ID,
            "captured_at": _CAPTURED_AT,
            "route_origin": "MCP",
            "route_destination": "BSB",
            "departure_date": date(2026, 9, 1),
            "carrier": "GOL",
            "flight_number": "G3-1234",
            "departure_time": time(8, 30),
            "price": Decimal("1234.56"),
            "currency": "BRL",
            "flight_id": "MCP-BSB-2026-09-01-G3-1234",
        }

    def test_price_stays_decimal(self) -> None:
        flight = make_flight(price=Decimal("999.90"))
        row = flight_to_silver_row(
            flight, execution_id=_EXECUTION_ID, captured_at=_CAPTURED_AT
        )
        assert isinstance(row["price"], Decimal)
        assert row["price"] == Decimal("999.90")

    def test_flight_id_matches_domain_key(self) -> None:
        flight = make_flight(flight_number="G3-9999")
        row = flight_to_silver_row(
            flight, execution_id=_EXECUTION_ID, captured_at=_CAPTURED_AT
        )
        assert row["flight_id"] == flight.flight_id


class TestAlertToGoldRow:
    def test_maps_all_columns(self) -> None:
        alerted_at = datetime(2026, 7, 24, 13, 0, tzinfo=UTC)
        alert = Alert(
            flight_id="MCP-BSB-2026-09-01-G3-1234",
            price=Decimal("1000.00"),
            currency="BRL",
            alerted_at=alerted_at,
        )
        row = alert_to_gold_row(alert, execution_id=_EXECUTION_ID)
        assert row == {
            "execution_id": _EXECUTION_ID,
            "flight_id": "MCP-BSB-2026-09-01-G3-1234",
            "price": Decimal("1000.00"),
            "currency": "BRL",
            "alerted_at": alerted_at,
        }

    def test_price_stays_decimal(self) -> None:
        alert = Alert(
            flight_id="MCP-BSB-2026-09-01-G3-1234",
            price=Decimal("500.55"),
            currency="BRL",
            alerted_at=_CAPTURED_AT,
        )
        row = alert_to_gold_row(alert, execution_id=_EXECUTION_ID)
        assert isinstance(row["price"], Decimal)
        assert row["price"] == Decimal("500.55")
