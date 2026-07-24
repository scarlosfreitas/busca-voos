"""Unit tests for the pure mapping helpers (CapturedFlight → domain Flight).

These pin the orchestration boundary that applies ``regras_negocio.md`` §Validações
when translating the extraction value object into a domain entity. No I/O — today
they fail with ``NotImplementedError`` (correct reason: missing implementation).
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from domain.models import InvalidFlightError
from orchestration.assets import captured_to_flight, to_valid_flights

from .conftest import MONITORED_ROUTE, FakeLogger, make_captured


def test_captured_to_flight_composes_designator_and_translates_carrier() -> None:
    captured = make_captured(carrier="G3", flight_number="1234")

    flight = captured_to_flight(captured, MONITORED_ROUTE)

    # Full designator becomes the dedup flight number; carrier code → display name.
    assert flight.flight_number == "G3-1234"
    assert flight.carrier == "GOL"
    assert flight.route == MONITORED_ROUTE
    assert flight.price == Decimal("1234.56")
    assert flight.currency == "BRL"
    # The dedup key is stable and route-scoped.
    assert flight.flight_id == "MCP-BSB-2026-09-01-G3-1234"


def test_captured_to_flight_unknown_carrier_falls_back_to_code() -> None:
    captured = make_captured(carrier="XX", flight_number="9")

    flight = captured_to_flight(captured, MONITORED_ROUTE)

    assert flight.carrier == "XX"
    assert flight.flight_number == "XX-9"


def test_captured_to_flight_rejects_non_positive_price() -> None:
    captured = make_captured(price=Decimal(0))

    # validate_flight is single-sourced in domain; a zero price must raise.
    with pytest.raises(InvalidFlightError):
        captured_to_flight(captured, MONITORED_ROUTE)


def test_to_valid_flights_keeps_valid_drops_invalid_price() -> None:
    good = make_captured(flight_number="1000", price=Decimal("500.00"))
    bad = make_captured(flight_number="2000", price=Decimal(0))
    logger = FakeLogger()

    result = to_valid_flights(
        [
            good,
            bad,
        ],
        MONITORED_ROUTE,
        logger,
    )

    assert [f.flight_number for f in result] == ["G3-1000"]
    # The dropped flight must be observable, not silent.
    assert logger.warnings


def test_to_valid_flights_drops_flight_of_another_route() -> None:
    on_route = make_captured(flight_number="1000")
    other_route = make_captured(flight_number="3000", origin="GRU", destination="BSB")
    logger = FakeLogger()

    result = to_valid_flights([on_route, other_route], MONITORED_ROUTE, logger)

    assert [f.flight_number for f in result] == ["G3-1000"]
    assert logger.warnings


def test_to_valid_flights_preserves_order() -> None:
    a = make_captured(flight_number="1", departure_time=time(6, 0))
    b = make_captured(flight_number="2", departure_time=time(9, 0))
    c = make_captured(flight_number="3", departure_time=time(20, 0))
    logger = FakeLogger()

    result = to_valid_flights([a, b, c], MONITORED_ROUTE, logger)

    assert [f.flight_number for f in result] == ["G3-1", "G3-2", "G3-3"]


def test_to_valid_flights_empty_input_yields_empty_list() -> None:
    logger = FakeLogger()
    assert to_valid_flights([], MONITORED_ROUTE, logger) == []
    # Distinct outbound date is also "another route/date" and must be dropped.
    off_date = make_captured(departure_date=date(2026, 9, 2))
    assert to_valid_flights([off_date], MONITORED_ROUTE, logger) == []
