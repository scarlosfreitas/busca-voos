"""Shared fixtures + in-memory fakes for the orchestration test suite.

Two kinds of tests live here (same split as the other layers):

* **Unit tests** for the pure decision logic (:func:`orchestration.run_daily_search`
  and the mapping helpers) — no I/O, always run. Every collaborator is a fake
  defined here. They fail until dev-runner implements the bodies (today:
  ``NotImplementedError``).
* An **integration test** that executes the real Dagster job — automatically
  *skipped* unless opt-in (``RUN_ORCHESTRATION_INTEGRATION=1``) and the real
  Playwright/Postgres/Telegram stack is reachable. This is the "recurso opcional
  pulado automaticamente" convention of ``docs/standards/architecture.md`` §8 and
  ``.claude/agents/qa.md`` §8.

The fakes deliberately mirror the *structural* Protocols in
``orchestration.assets`` (``BronzeWriter``/``SilverWriter``/``GoldStore``/
``Notifier``/``PipelineLogger``) so the pure function can be driven without a
browser, a database or the network — and so a test can make any single
collaborator raise, to pin the failure edge cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from domain.models import Alert, Flight, Route
from extraction.gol import CABIN_ECONOMY, CapturedFlight, GolCaptureResult
from notification.telegram import NotificationError

# MVP monitored route, mirrors the other layers' conftests.
MONITORED_ROUTE = Route(
    origin="MCP", destination="BSB", departure_date=date(2026, 9, 1)
)

# A fixed run clock, so outcomes are deterministic in tests.
RUN_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
SEARCH_DATE = RUN_NOW.date()


# ── Builders ────────────────────────────────────────────────────────────────────


def make_captured(
    *,
    carrier: str = "G3",
    flight_number: str = "1234",
    origin: str = "MCP",
    destination: str = "BSB",
    departure_date: date = date(2026, 9, 1),
    departure_time: time = time(8, 30),
    price: Decimal = Decimal("1234.56"),
    currency: str = "BRL",
    cabin: str = CABIN_ECONOMY,
) -> CapturedFlight:
    """Build an extraction-layer CapturedFlight, overriding only what's needed."""
    return CapturedFlight(
        carrier=carrier,
        flight_number=flight_number,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        departure_time=departure_time,
        price=price,
        currency=currency,
        cabin=cabin,
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
    """Build a valid domain Flight (already mapped/validated), overriding as needed."""
    return Flight(
        route=route,
        carrier=carrier,
        flight_number=flight_number,
        departure_time=departure_time,
        price=price,
        currency=currency,
    )


def make_capture_result(*captured: CapturedFlight) -> GolCaptureResult:
    """Bundle captured flights into a well-formed GolCaptureResult (bronze payload)."""
    payload = {"trips": [{"origin": "MCP", "destination": "BSB", "flights": []}]}
    return GolCaptureResult(raw_payload=payload, flights=tuple(captured))


# ── Fakes for the injected collaborators ────────────────────────────────────────


def capture_returning(result: GolCaptureResult):
    """A CaptureFn that returns a canned result."""

    def _capture() -> GolCaptureResult:
        return result

    return _capture


def capture_raising(exc: Exception):
    """A CaptureFn that raises (simulates an extraction failure)."""

    def _capture() -> GolCaptureResult:
        raise exc

    return _capture


@dataclass
class FakeBronze:
    """Records save_raw_response calls; can be told to raise (persistence failure)."""

    raise_on_call: Exception | None = None
    calls: list[dict] = field(default_factory=list)
    _next_id: int = 1

    def save_raw_response(
        self,
        *,
        execution_id: UUID,
        route: Route,
        captured_at: datetime,
        success: bool,
        payload: object | None,
        error_message: str | None = None,
    ) -> int:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.calls.append(
            {
                "execution_id": execution_id,
                "route": route,
                "captured_at": captured_at,
                "success": success,
                "payload": payload,
                "error_message": error_message,
            }
        )
        row_id = self._next_id
        self._next_id += 1
        return row_id


@dataclass
class FakeSilver:
    """Records save_flights calls; can be told to raise (persistence failure)."""

    raise_on_call: Exception | None = None
    calls: list[list[Flight]] = field(default_factory=list)

    def save_flights(
        self,
        *,
        execution_id: UUID,
        captured_at: datetime,
        flights,
    ) -> list[int]:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        flights = list(flights)
        self.calls.append(flights)
        return list(range(1, len(flights) + 1))


@dataclass
class FakeGold:
    """Serves a canned last_alerted_prices map and records appended alerts."""

    prices: dict[str, Decimal] = field(default_factory=dict)
    raise_on_record: Exception | None = None
    recorded: list[Alert] = field(default_factory=list)

    def last_alerted_prices(self, route: Route) -> dict[str, Decimal]:
        return dict(self.prices)

    def record_alerts(self, *, execution_id: UUID, alerts) -> list[int]:
        if self.raise_on_record is not None:
            raise self.raise_on_record
        alerts = list(alerts)
        self.recorded.extend(alerts)
        return list(range(1, len(alerts) + 1))


@dataclass
class FakeNotifier:
    """Records sent texts; can raise NotificationError on the Nth send (1-based)."""

    raise_on_send_number: int | None = None
    sent: list[str] = field(default_factory=list)

    def send(self, text: str) -> None:
        self.sent.append(text)
        if (
            self.raise_on_send_number is not None
            and len(self.sent) == self.raise_on_send_number
        ):
            raise NotificationError("fake delivery failure")


@dataclass
class FakeLogger:
    """Captures log messages by level so tests can assert observability."""

    infos: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def info(self, message: str) -> None:
        self.infos.append(str(message))

    def warning(self, message: str) -> None:
        self.warnings.append(str(message))

    def error(self, message: str) -> None:
        self.errors.append(str(message))


# ── Fixtures ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def route() -> Route:
    return MONITORED_ROUTE


@pytest.fixture
def execution_id() -> UUID:
    return uuid4()


@pytest.fixture
def logger() -> FakeLogger:
    return FakeLogger()


@pytest.fixture
def collaborators():
    """Return a fresh bundle of fakes plus the builder helpers, for convenience."""
    return {
        "bronze": FakeBronze(),
        "silver": FakeSilver(),
        "gold": FakeGold(),
        "notifier": FakeNotifier(),
    }


# ── Real-Postgres fixtures (QA integration tests only) ──────────────────────────
#
# Mirrors ``test/persistence/conftest.py``'s ``pg_engine``/``pg_connection`` skip
# gate (architecture.md §8 / qa.md §8: optional resource, auto-skip, never fail).
# Duplicated locally (rather than imported cross-package) so pytest's fixture
# injection via same-named test parameters doesn't collide with a module-level
# import name (ruff F811) — same skip semantics, independent definition.


@pytest.fixture(scope="session")
def pg_engine_qa():
    """Session-scoped Engine against a real Postgres, or skip if unavailable."""
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
def pg_connection_qa(pg_engine_qa):
    """Function-scoped transactional Connection, rolled back after each test."""
    conn = pg_engine_qa.connect()
    tx = conn.begin()
    try:
        yield conn
    finally:
        tx.rollback()
        conn.close()
