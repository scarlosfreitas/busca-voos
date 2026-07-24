"""Shared fixtures for the notification test suite.

Two kinds of tests live here (same split as ``test/persistence`` and
``test/extraction``):

* **Unit tests** for pure message composition — no network, always run. They fail
  until dev-runner implements the ``format_*`` bodies.
* An **integration test** for real delivery to Telegram — automatically *skipped*
  unless opt-in (``RUN_TELEGRAM_INTEGRATION=1``) *and* credentials are present.
  This is the "recurso opcional pulado automaticamente" convention of
  ``docs/standards/architecture.md`` §8 and ``.claude/agents/qa.md`` §8.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from domain.models import Flight, Route

# MVP monitored route, mirrors test/persistence/conftest.py.
MONITORED_ROUTE = Route(
    origin="MCP", destination="BSB", departure_date=date(2026, 9, 1)
)


def make_flight(
    *,
    route: Route = MONITORED_ROUTE,
    carrier: str = "GOL",
    flight_number: str = "G3-1234",
    departure_time: time = time(8, 30),
    price: Decimal = Decimal("1234.56"),
    currency: str = "BRL",
) -> Flight:
    """Build a valid deduplicated flight, overriding only what a test needs."""
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
def flight_factory():
    return make_flight
