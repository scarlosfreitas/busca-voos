"""Shared fixtures for the persistence test suite.

Two kinds of tests live here:

* **Unit tests** for pure logic (URL assembly, row mapping) — no database, always
  run. They fail until dev-runner implements the bodies.
* **Integration tests** against a real Postgres — automatically *skipped* when no
  database is reachable (or the connection config is not yet implemented). This
  is the "recurso opcional pulado automaticamente" convention from
  ``docs/standards/architecture.md`` §8 and ``.claude/agents/qa.md`` §8.

The ``pg_connection`` fixture below is the skip gate: if we cannot build the URL
or connect, the whole integration test is skipped rather than failed.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, time
from decimal import Decimal

import pytest

from domain.models import Flight, Route

# MVP monitored route, mirrors test/domain/conftest.py.
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
def flight_factory():
    return make_flight


@pytest.fixture(scope="session")
def pg_engine():
    """Session-scoped Engine against a real Postgres, or skip if unavailable.

    Skips (never fails) when the connection cannot be built (config not yet
    implemented) or a live connection cannot be opened. When a database *is*
    reachable, the Medallion tables are created from
    ``persistence.tables.metadata`` (``create_all``/``checkfirst``) — acceptable
    in tests; production DDL goes through Alembic (architecture.md §4).
    """
    from sqlalchemy import create_engine, text

    from persistence.db import build_database_url
    from persistence.tables import metadata

    try:
        url = build_database_url()
    except NotImplementedError:
        pytest.skip("persistence.db.build_database_url not implemented yet")
    except Exception as exc:  # noqa: BLE001 - any config error means "skip, not fail"
        pytest.skip(f"Postgres connection config unavailable: {exc}")

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - unreachable DB means "skip, not fail"
        pytest.skip(f"Postgres not reachable: {exc}")

    metadata.create_all(engine, checkfirst=True)
    return engine


@pytest.fixture
def pg_connection(pg_engine) -> Iterator:
    """Function-scoped transactional Connection, rolled back after each test.

    Every integration test runs inside a transaction that is rolled back, so the
    append-only tables stay clean between tests without a purge step.
    """
    conn = pg_engine.connect()
    tx = conn.begin()
    try:
        yield conn
    finally:
        tx.rollback()
        conn.close()
