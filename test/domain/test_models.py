"""Tests for domain models and validations.

Covers the "Identificador do voo" glossary entry and the "Validações" section of
``docs/domain/regras_negocio.md``.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from domain.models import (
    Alert,
    Flight,
    InvalidFlightError,
    Route,
    validate_flight,
)

from .conftest import make_flight


class TestSchema:
    """The entities exist with the fields required by the domain."""

    def test_route_holds_origin_destination_and_outbound_date(self) -> None:
        route = Route(origin="MCP", destination="BSB", departure_date=date(2026, 9, 1))
        assert route.origin == "MCP"
        assert route.destination == "BSB"
        assert route.departure_date == date(2026, 9, 1)

    def test_flight_holds_all_mandatory_fields(self) -> None:
        flight = make_flight()
        assert flight.carrier == "GOL"
        assert flight.flight_number == "G3-1234"
        assert flight.route.origin == "MCP"
        assert flight.route.destination == "BSB"
        assert flight.route.departure_date == date(2026, 9, 1)
        assert flight.departure_time == time(8, 30)
        assert flight.price == Decimal("1234.56")
        assert flight.currency == "BRL"

    def test_alert_records_last_alerted_price_per_flight(self) -> None:
        alerted_at = datetime(2026, 7, 24, 12, 0, 0)
        alert = Alert(
            flight_id="MCP-BSB-2026-09-01-G3-1234",
            price=Decimal("999.00"),
            currency="BRL",
            alerted_at=alerted_at,
        )
        assert alert.flight_id == "MCP-BSB-2026-09-01-G3-1234"
        assert alert.price == Decimal("999.00")
        assert alert.currency == "BRL"
        assert alert.alerted_at == alerted_at

    def test_models_are_immutable(self) -> None:
        flight = make_flight()
        with pytest.raises(Exception):
            flight.price = Decimal("1.00")  # type: ignore[misc]


class TestFlightId:
    """flight_id is the deduplication key: route + outbound date + flight number."""

    def test_flight_id_composes_route_date_and_flight_number(self) -> None:
        flight = make_flight()
        assert flight.flight_id == "MCP-BSB-2026-09-01-G3-1234"

    def test_same_physical_flight_shares_id_across_captures(self) -> None:
        first = make_flight(price=Decimal("1000.00"))
        second = make_flight(price=Decimal("1500.00"))
        assert first.flight_id == second.flight_id

    def test_different_flight_number_yields_different_id(self) -> None:
        assert make_flight(flight_number="G3-1234").flight_id != make_flight(
            flight_number="G3-9999"
        ).flight_id

    def test_different_date_yields_different_id(self) -> None:
        other_route = Route(origin="MCP", destination="BSB", departure_date=date(2026, 9, 2))
        assert make_flight().flight_id != make_flight(route=other_route).flight_id


class TestValidateFlight:
    """validate_flight enforces the Validações section 1:1."""

    def test_valid_flight_passes(self) -> None:
        assert validate_flight(make_flight()) is None

    @pytest.mark.parametrize("price", [Decimal("0"), Decimal("-0.01"), Decimal("-100.00")])
    def test_non_positive_price_is_invalid(self, price: Decimal) -> None:
        with pytest.raises(InvalidFlightError):
            validate_flight(make_flight(price=price))

    def test_missing_flight_number_is_invalid(self) -> None:
        with pytest.raises(InvalidFlightError):
            validate_flight(make_flight(flight_number=""))

    def test_missing_carrier_is_invalid(self) -> None:
        with pytest.raises(InvalidFlightError):
            validate_flight(make_flight(carrier=""))

    def test_missing_currency_is_invalid(self) -> None:
        with pytest.raises(InvalidFlightError):
            validate_flight(make_flight(currency=""))

    def test_missing_origin_is_invalid(self) -> None:
        bad_route = Route(origin="", destination="BSB", departure_date=date(2026, 9, 1))
        with pytest.raises(InvalidFlightError):
            validate_flight(make_flight(route=bad_route))

    def test_missing_destination_is_invalid(self) -> None:
        bad_route = Route(origin="MCP", destination="", departure_date=date(2026, 9, 1))
        with pytest.raises(InvalidFlightError):
            validate_flight(make_flight(route=bad_route))

    def test_smallest_positive_price_is_valid(self) -> None:
        assert validate_flight(make_flight(price=Decimal("0.01"))) is None
