"""Shared fixtures for the domain test suite.

Provide builders for a valid monitored route and a valid captured flight so each
test only overrides the fields relevant to the rule under test.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from domain.models import Flight, Route

# MVP monitored route: MCP -> BSB, outbound 2026-09-01.
MONITORED_ROUTE = Route(origin="MCP", destination="BSB", departure_date=date(2026, 9, 1))


def make_flight(
    *,
    route: Route = MONITORED_ROUTE,
    carrier: str = "GOL",
    flight_number: str = "G3-1234",
    departure_time: time = time(8, 30),
    price: Decimal = Decimal("1234.56"),
    currency: str = "BRL",
) -> Flight:
    """Build a valid captured flight, overriding only what a test needs."""
    return Flight(
        route=route,
        carrier=carrier,
        flight_number=flight_number,
        departure_time=departure_time,
        price=price,
        currency=currency,
    )


@pytest.fixture
def route() -> Route:
    return MONITORED_ROUTE


@pytest.fixture
def flight() -> Flight:
    return make_flight()


@pytest.fixture
def flight_factory():
    return make_flight
