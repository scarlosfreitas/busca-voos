"""Dagster orchestration: the daily job that glues every layer together.

This is the **last code module of the MVP**. It wires the already-built and
already-tested layers into one daily run (``docs/standards/architecture.md`` §1):

    extraction  →  bronze  →  silver  →  domain (eligibility + dedup)  →  gold
                                                                      ↘ notification

Design axis — pure decision logic vs. thin Dagster shell
--------------------------------------------------------
The real run touches Playwright, Postgres and Telegram — none of which run in a
unit test. So the **orchestration decision logic** is extracted into pure,
dependency-injected functions (below), and the Dagster ``@asset``/job/schedule is
a *thin shell* that only:

1. builds the real collaborators (async capture, connection-scoped repositories,
   a Telegram-backed notifier, ``context.log``), and
2. delegates the whole decision to :func:`run_daily_search`, then commits/rolls
   back the transaction and surfaces failure to the Dagster UI based on the
   returned :class:`RunOutcome`.

Every collaborator is injected as a Protocol / callable, so the six business
edge cases (``docs/domain/regras_negocio.md`` — Execução / Elegibilidade /
Deduplicação / Notificação / Persistência / Validações) are exercised with
fakes, no I/O. The real job is covered only by a skippable integration test
(same convention as ``test/persistence`` / ``test/extraction`` /
``test/notification``).

Error handling (``architecture.md`` §6): :func:`run_daily_search` is **total** —
it never lets a failure crash the process. Extraction, persistence and delivery
failures are caught, logged via the injected logger, routed to a Telegram failure
notification, and reported through the :class:`RunOutcome`. Even a failure of the
*error* notification itself (Telegram down) is logged, never re-raised. The thin
shell then decides whether to mark the Dagster run failed.

All bodies that carry real logic raise :class:`NotImplementedError` for the
dev-runner to implement — this module ships the *contract* only, plus the wired
(but not-yet-executable) Dagster definitions.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Protocol
from uuid import UUID, uuid4

from dagster import Definitions, Failure, ScheduleDefinition, asset, define_asset_job

from domain.deduplication import select_flights_to_notify
from domain.eligibility import select_eligible
from domain.models import Alert, Flight, InvalidFlightError, Route, validate_flight
from extraction.errors import ExtractionError
from extraction.gol import (
    MVP_SEARCH_PARAMS,
    CapturedFlight,
    GolCaptureResult,
    capture_gol_search,
)
from notification.telegram import (
    NotificationError,
    TelegramConfig,
    format_failure_message,
    format_flight_alert_message,
    send_telegram_message,
)
from persistence.db import get_engine
from persistence.repositories import BronzeRepository, GoldRepository, SilverRepository

# ── Single sources of truth ────────────────────────────────────────────────────

#: The monitored route in domain terms, derived from the extraction layer's single
#: source of truth for the MVP search (``extraction.gol.MVP_SEARCH_PARAMS``;
#: architecture.md §5 — one config source, never re-hardcoded). MCP → BSB, 2026-09-01.
MONITORED_ROUTE = Route(
    origin=MVP_SEARCH_PARAMS.origin,
    destination=MVP_SEARCH_PARAMS.destination,
    departure_date=MVP_SEARCH_PARAMS.departure_date,
)

#: Carrier-code → display-name translation used when building a domain
#: :class:`~domain.models.Flight` from a :class:`~extraction.gol.CapturedFlight`.
#: The extraction layer keeps the raw designator parts (``"G3"`` / ``"1234"``); the
#: domain/notification layers want a human carrier name. MVP is Gol only; any
#: unknown code falls back to the code itself. Cosmetic mapping — not a business
#: rule, so it lives here rather than in ``domain``.
CARRIER_NAMES: dict[str, str] = {"G3": "GOL"}

#: Cron for the daily schedule. The exact hour is arbitrary per
#: ``docs/domain/regras_negocio.md`` — Regra de Execução (1x/dia, sem horário
#: fixo). A non-partitioned Dagster schedule performs **no catch-up/backfill**,
#: matching the rule's "sem mecanismo de compensação" edge case.
DAILY_CRON = "0 9 * * *"


# ── Injected-collaborator protocols (structural; real objects already satisfy) ──


class CaptureFn(Protocol):
    """Synchronous capture step: returns a :class:`GolCaptureResult` or raises.

    The pure orchestration logic stays synchronous and unit-testable; the shell
    adapts the async :func:`extraction.gol.capture_gol_search` to this signature
    (via ``asyncio.run``). Any failure must surface as an
    :class:`~extraction.errors.ExtractionError` subclass (the extraction layer's
    contract), which :func:`run_daily_search` catches.
    """

    def __call__(self) -> GolCaptureResult: ...


class BronzeWriter(Protocol):
    """Structural view of :class:`persistence.repositories.BronzeRepository`."""

    def save_raw_response(
        self,
        *,
        execution_id: UUID,
        route: Route,
        captured_at: datetime,
        success: bool,
        payload: object | None,
        error_message: str | None = ...,
    ) -> int: ...


class SilverWriter(Protocol):
    """Structural view of :class:`persistence.repositories.SilverRepository`."""

    def save_flights(
        self,
        *,
        execution_id: UUID,
        captured_at: datetime,
        flights: Sequence[Flight],
    ) -> list[int]: ...


class GoldStore(Protocol):
    """Structural view of :class:`persistence.repositories.GoldRepository`."""

    def last_alerted_prices(self, route: Route) -> dict[str, Decimal]: ...

    def record_alerts(
        self, *, execution_id: UUID, alerts: Sequence[Alert]
    ) -> list[int]: ...


class Notifier(Protocol):
    """Delivers an already-composed message to Telegram, or raises on failure.

    Decouples the decision logic from the transport: :func:`run_daily_search`
    composes the message with the pure ``notification.format_*`` functions and
    hands the finished text to :meth:`send`. The production implementation
    (:class:`TelegramNotifier`) wraps ``notification.send_telegram_message``; a
    delivery failure must raise ``notification.NotificationError`` (never be
    swallowed at this layer — the decision layer decides what to do with it).
    """

    def send(self, text: str) -> None: ...


class PipelineLogger(Protocol):
    """Minimal subset of Dagster's ``context.log`` used by the decision logic.

    Dagster's logger satisfies this structurally; tests pass a fake. Using the
    native Dagster logger keeps run logs in the Dagster UI (architecture.md §6 —
    no extra logging library).
    """

    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...


# ── Run outcome ────────────────────────────────────────────────────────────────


class RunStatus(Enum):
    """Terminal classification of one daily run.

    Mutually exclusive per ``docs/domain/regras_negocio.md`` — Regra de
    Notificação (0/1 flight alert + 0/1 failure message per run).
    """

    #: Ran, at least one new/changed flight → flight alert sent, gold updated.
    SUCCESS_ALERTED = auto()
    #: Ran successfully but nothing to notify (0 eligible, or all deduplicated).
    SUCCESS_NO_ALERT = auto()
    #: Extraction raised an ``ExtractionError`` → failure notification attempted.
    FAILED_EXTRACTION = auto()
    #: A bronze/silver/gold write raised → failure notification attempted, roll back.
    FAILED_PERSISTENCE = auto()
    #: Delivering the *flight alert* raised ``NotificationError`` → gold not updated.
    FAILED_NOTIFICATION = auto()
    #: ``gold.record_alerts`` raised *after* the flight alert was already
    #: successfully delivered → the user was notified, but the dedup record for
    #: this run's alerts was not persisted (next run may re-notify the same
    #: flight/price). Bronze/silver capture is still valid and kept.
    FAILED_GOLD_RECORD = auto()

    @property
    def is_failure(self) -> bool:
        """Whether the shell should surface this run as failed in the Dagster UI."""
        return self in {
            RunStatus.FAILED_EXTRACTION,
            RunStatus.FAILED_PERSISTENCE,
            RunStatus.FAILED_NOTIFICATION,
            RunStatus.FAILED_GOLD_RECORD,
        }


@dataclass(frozen=True)
class RunOutcome:
    """What one run did — the contract between :func:`run_daily_search` and the shell.

    :attr:`should_commit` tells the thin shell whether to commit or roll back the
    persistence transaction it owns: a successful run (data captured, bronze +
    silver written, and — when alerted — gold written) commits; a persistence
    failure rolls everything back so the run leaves no partial/invalid data
    (``regras_negocio.md`` — Validações: bronze written ⇔ run succeeded).
    """

    status: RunStatus
    execution_id: UUID
    eligible_count: int
    notified_count: int
    should_commit: bool
    error: Exception | None
    message: str

    @property
    def is_failure(self) -> bool:
        return self.status.is_failure


# ── Pure mapping helpers (no I/O; unit-tested) ─────────────────────────────────


def captured_to_flight(captured: CapturedFlight, route: Route) -> Flight:
    """Map an extraction :class:`CapturedFlight` onto a domain :class:`Flight`.

    Contract (pinned by ``test/orchestration/test_mapping.py``):

    * ``route`` is the domain route this flight belongs to (its origin,
      destination and outbound date).
    * ``flight_number`` becomes the **full designator** ``"{carrier}-{number}"``
      (e.g. ``"G3"`` + ``"1234"`` → ``"G3-1234"``), which is the "Identificador do
      voo" the dedup key is built from (``regras_negocio.md`` — glossário).
    * ``carrier`` is translated via :data:`CARRIER_NAMES` (``"G3"`` → ``"GOL"``;
      unknown code → the code itself).
    * ``departure_time``, ``price`` (kept a :class:`Decimal`) and ``currency`` are
      carried over verbatim.
    * The built ``Flight`` is validated with
      :func:`domain.models.validate_flight`; a non-positive price or missing
      mandatory field therefore raises
      :class:`~domain.models.InvalidFlightError` (single-sourced in ``domain``).

    Implementation left to dev-runner.
    """
    flight = Flight(
        route=route,
        carrier=CARRIER_NAMES.get(captured.carrier, captured.carrier),
        flight_number=f"{captured.carrier}-{captured.flight_number}",
        departure_time=captured.departure_time,
        price=captured.price,
        currency=captured.currency,
    )
    validate_flight(flight)
    return flight


def to_valid_flights(
    captured: Sequence[CapturedFlight],
    monitored_route: Route,
    logger: PipelineLogger,
) -> list[Flight]:
    """Map + validate captured flights, dropping (never raising on) invalid ones.

    Applies the "Validações" section of ``docs/domain/regras_negocio.md`` at the
    orchestration boundary. Contract (pinned by
    ``test/orchestration/test_mapping.py``):

    * For each captured flight, reconstruct its route from its own
      ``origin``/``destination``/``departure_date``. If it does **not** equal
      ``monitored_route`` → the flight is for another route/date and is **dropped**
      (log a warning), never persisted as a valid result of this run.
    * Otherwise build the domain flight via :func:`captured_to_flight`. If
      validation fails (:class:`~domain.models.InvalidFlightError` — e.g. a
      zero/negative price, per the rule "preço nulo/zero/negativo é tratado como
      falha de extração daquele voo") → the flight is **dropped** (log a warning).
      A single bad flight is *not* a run failure.
    * Valid flights are returned in input order.

    This function must be resilient per-flight: it returns a (possibly empty) list
    and never propagates an exception for a single bad record.

    Implementation left to dev-runner.
    """
    valid: list[Flight] = []
    for captured_flight in captured:
        captured_route = Route(
            origin=captured_flight.origin,
            destination=captured_flight.destination,
            departure_date=captured_flight.departure_date,
        )
        if captured_route != monitored_route:
            logger.warning(
                f"Dropping flight {captured_flight.carrier}-"
                f"{captured_flight.flight_number}: route "
                f"{captured_route.origin}-{captured_route.destination}-"
                f"{captured_route.departure_date.isoformat()} does not match "
                f"monitored route {monitored_route.origin}-"
                f"{monitored_route.destination}-"
                f"{monitored_route.departure_date.isoformat()}"
            )
            continue
        try:
            valid.append(captured_to_flight(captured_flight, monitored_route))
        except InvalidFlightError as exc:
            logger.warning(
                f"Dropping invalid flight {captured_flight.carrier}-"
                f"{captured_flight.flight_number}: {exc}"
            )
    return valid


def build_alert(flight: Flight, alerted_at: datetime) -> Alert:
    """Build the :class:`~domain.models.Alert` to append to gold for a notified flight.

    Contract: ``flight_id`` from :attr:`Flight.flight_id`, ``price``/``currency``
    from the flight (the price effectively alerted), ``alerted_at`` = the run
    timestamp. This is the "último preço alertado" that the next run's dedup reads.

    Implementation left to dev-runner.
    """
    return Alert(
        flight_id=flight.flight_id,
        price=flight.price,
        currency=flight.currency,
        alerted_at=alerted_at,
    )


# ── Pure orchestration decision logic (no I/O; the heart of the module) ─────────


def run_daily_search(
    *,
    route: Route,
    search_date: date,
    capture: CaptureFn,
    bronze: BronzeWriter,
    silver: SilverWriter,
    gold: GoldStore,
    notify: Notifier,
    logger: PipelineLogger,
    execution_id: UUID,
    now: datetime,
) -> RunOutcome:
    """Execute one daily run's decision logic against injected collaborators.

    Pure orchestration: **all** I/O is behind the injected ``capture`` / ``bronze``
    / ``silver`` / ``gold`` / ``notify`` / ``logger`` parameters, so every branch
    below is unit-testable with fakes. This function is **total** — it never raises
    for a handled failure mode; it always returns a :class:`RunOutcome`
    (``architecture.md`` §6: no silent crash).

    Flow and edge cases (traceable 1:1 with ``docs/domain/regras_negocio.md``):

    1. **Extraction.** Call ``capture()``.

       * Raises :class:`~extraction.errors.ExtractionError` (any subclass — block,
         timeout, malformed) → **edge (d)**: write a bronze *failure marker*
         (``save_raw_response(success=False, payload=None, error_message=str(exc))``
         — no silver/gold, no invalid flight data persisted), compose a failure
         message with ``notification.format_failure_message(exc, search_date, route)``
         and ``notify.send`` it; log the failure. Return
         ``RunStatus.FAILED_EXTRACTION`` (``should_commit=True`` — the marker row
         is valid run metadata).
       * If ``notify.send`` itself raises ``NotificationError`` while sending the
         failure message → **edge (f)**: ``logger.error`` it and **do not**
         re-raise. The run is still ``FAILED_EXTRACTION``.

    2. **Bronze (success path).** ``save_raw_response(success=True,
       payload=result.raw_payload, ...)``. If this — or any later write — raises →
       **edge (e)**: log it, attempt a failure notification (swallowing a nested
       ``NotificationError`` with a log), return ``RunStatus.FAILED_PERSISTENCE``
       with ``should_commit=False`` (the shell rolls back → no partial data).

    3. **Silver + domain.** Map with :func:`to_valid_flights` (invalid/other-route
       flights dropped, not fatal), ``silver.save_flights`` the valid ones, then
       ``select_eligible`` (MVP: identity).

    4. **Deduplication.** ``gold.last_alerted_prices(route)`` (still inside the
       same try/except as step 2-3 — a gold read failure is a persistence
       failure like bronze/silver, not a distinct edge case) →
       ``select_flights_to_notify``.

       * Empty result → **edge (a)** (0 eligible / empty capture) or **edge (b)**
         (all deduplicated, price unchanged): send **nothing**, do not touch gold.
         Return ``RunStatus.SUCCESS_NO_ALERT``.

    5. **Alert.** Non-empty → **edge (c)**: compose one message with
       ``notification.format_flight_alert_message(to_notify, search_date)`` and
       ``notify.send`` it **first**; only on success append the alerts to gold via
       ``gold.record_alerts`` (so gold holds only *effectively sent* prices — the
       "efetivamente enviado" definition of último preço alertado). Return
       ``RunStatus.SUCCESS_ALERTED``.

       * If the flight-alert ``notify.send`` raises ``NotificationError`` → do
         **not** record gold (so the next run retries), log the error, and return
         ``RunStatus.FAILED_NOTIFICATION`` (``should_commit=True`` — bronze/silver
         are valid captured data worth keeping; only gold was withheld).
       * If ``gold.record_alerts`` itself raises *after* the flight alert was
         already sent successfully → do **not** send a second (failure)
         notification (0/1 alert + 0/1 failure message per run is mutually
         exclusive), log the error, and return ``RunStatus.FAILED_GOLD_RECORD``
         (``should_commit=True`` — bronze/silver/the already-delivered alert
         stand; only this run's dedup record is missing).

    Implementation left to dev-runner.
    """

    def _notify_failure(exc: Exception) -> None:
        message = format_failure_message(exc, search_date=search_date, route=route)
        try:
            notify.send(message)
        except NotificationError as notify_exc:
            logger.error(f"Failed to send failure notification: {notify_exc}")

    # 1. Extraction.
    try:
        result = capture()
    except ExtractionError as exc:
        logger.error(f"Extraction failed: {exc}")
        try:
            bronze.save_raw_response(
                execution_id=execution_id,
                route=route,
                captured_at=now,
                success=False,
                payload=None,
                error_message=str(exc),
            )
        except Exception as bronze_exc:  # noqa: BLE001 - persistence failure path
            logger.error(f"Failed to persist bronze failure marker: {bronze_exc}")
        _notify_failure(exc)
        return RunOutcome(
            status=RunStatus.FAILED_EXTRACTION,
            execution_id=execution_id,
            eligible_count=0,
            notified_count=0,
            should_commit=True,
            error=exc,
            message=str(exc),
        )

    # 2. Bronze (success path) + downstream persistence.
    try:
        bronze.save_raw_response(
            execution_id=execution_id,
            route=route,
            captured_at=now,
            success=True,
            payload=result.raw_payload,
            error_message=None,
        )

        valid_flights = to_valid_flights(result.flights, route, logger)
        silver.save_flights(
            execution_id=execution_id, captured_at=now, flights=valid_flights
        )
        eligible = select_eligible(valid_flights)

        # 4. Deduplication read. Kept inside this same try: a gold read failure
        # is a persistence failure like bronze/silver, not a distinct edge case.
        last_alerted_prices = gold.last_alerted_prices(route)
    except Exception as exc:  # noqa: BLE001 - any persistence/mapping failure
        logger.error(f"Persistence failed: {exc}")
        _notify_failure(exc)
        return RunOutcome(
            status=RunStatus.FAILED_PERSISTENCE,
            execution_id=execution_id,
            eligible_count=0,
            notified_count=0,
            should_commit=False,
            error=exc,
            message=str(exc),
        )

    to_notify = select_flights_to_notify(eligible, last_alerted_prices)

    if not to_notify:
        return RunOutcome(
            status=RunStatus.SUCCESS_NO_ALERT,
            execution_id=execution_id,
            eligible_count=len(eligible),
            notified_count=0,
            should_commit=True,
            error=None,
            message="No new/changed flights to notify.",
        )

    # 5. Alert.
    message = format_flight_alert_message(to_notify, search_date)
    try:
        notify.send(message)
    except NotificationError as exc:
        logger.error(f"Failed to send flight alert: {exc}")
        return RunOutcome(
            status=RunStatus.FAILED_NOTIFICATION,
            execution_id=execution_id,
            eligible_count=len(eligible),
            notified_count=0,
            should_commit=True,
            error=exc,
            message=str(exc),
        )

    try:
        alerts = [build_alert(flight, now) for flight in to_notify]
        gold.record_alerts(execution_id=execution_id, alerts=alerts)
    except Exception as exc:  # noqa: BLE001 - gold write failure post-notification
        # The flight alert was already delivered successfully — do not send a
        # second (failure) notification for the same run (mutually exclusive
        # per regras_negocio.md — Regra de Notificação: 0/1 alert + 0/1 failure
        # message per run). Bronze/silver are still valid and kept; only the
        # dedup record for this run's alerts is missing (next run may re-alert).
        logger.error(
            f"Failed to record gold alerts after successful notification: {exc}"
        )
        return RunOutcome(
            status=RunStatus.FAILED_GOLD_RECORD,
            execution_id=execution_id,
            eligible_count=len(eligible),
            notified_count=len(to_notify),
            should_commit=True,
            error=exc,
            message=str(exc),
        )

    return RunOutcome(
        status=RunStatus.SUCCESS_ALERTED,
        execution_id=execution_id,
        eligible_count=len(eligible),
        notified_count=len(to_notify),
        should_commit=True,
        error=None,
        message=f"Sent {len(to_notify)} flight alert(s).",
    )


# ── Thin Dagster shell (I/O; integration-tested only) ──────────────────────────


@dataclass(frozen=True)
class TelegramNotifier:
    """Production :class:`Notifier` backed by the Telegram layer.

    Wraps a ``notification.TelegramConfig`` and delegates :meth:`send` to
    ``notification.send_telegram_message``. Thin adapter — no decision logic.
    Implementation left to dev-runner.
    """

    config: TelegramConfig

    def send(self, text: str) -> None:
        """Deliver ``text`` via ``notification.send_telegram_message``; raise on failure."""
        send_telegram_message(text, self.config)

    @classmethod
    def from_env(cls) -> TelegramNotifier:
        """Build a :class:`TelegramNotifier` from ``TelegramConfig.from_env``."""
        return cls(config=TelegramConfig.from_env())


def capture_sync() -> GolCaptureResult:
    """Adapt the async :func:`extraction.gol.capture_gol_search` to :class:`CaptureFn`.

    Runs the coroutine to completion (``asyncio.run``) for the monitored search
    (:data:`extraction.gol.MVP_SEARCH_PARAMS`) and returns the
    :class:`GolCaptureResult`, letting ``ExtractionError`` subclasses propagate.
    Implementation left to dev-runner.
    """
    return asyncio.run(capture_gol_search(MVP_SEARCH_PARAMS))


@asset(
    name="daily_flight_search",
    description="Daily Gol search: extract → bronze/silver/gold → Telegram alert.",
)
def daily_flight_search(context) -> None:
    """Thin Dagster asset: build real collaborators and delegate to the pure logic.

    Contract (integration-only; covered by the skippable
    ``test/orchestration/test_job_integration.py``):

    * Generate an ``execution_id`` (``uuid4``) and ``now``/``search_date`` from the
      clock.
    * Open a transactional scope on the persistence engine
      (``persistence.db.get_engine`` / a manual ``begin``), build
      ``BronzeRepository``/``SilverRepository``/``GoldRepository`` on the
      connection, build a :class:`TelegramNotifier` from
      ``notification.TelegramConfig.from_env`` and use ``context.log`` as the
      :class:`PipelineLogger`.
    * Call :func:`run_daily_search` with :func:`capture_sync` as ``capture``.
    * Commit if ``outcome.should_commit`` else roll back.
    * If ``outcome.is_failure`` → raise ``dagster.Failure`` (surface the run as
      failed in the UI) after the notification has already been attempted by
      :func:`run_daily_search`; otherwise attach ``outcome`` metadata.

    Implementation left to dev-runner.
    """
    execution_id = uuid4()
    now = datetime.now(UTC)
    search_date = now.date()

    engine = get_engine()
    connection = engine.connect()
    transaction = connection.begin()
    try:
        bronze = BronzeRepository(connection)
        silver = SilverRepository(connection)
        gold = GoldRepository(connection)
        notifier = TelegramNotifier.from_env()

        outcome = run_daily_search(
            route=MONITORED_ROUTE,
            search_date=search_date,
            capture=capture_sync,
            bronze=bronze,
            silver=silver,
            gold=gold,
            notify=notifier,
            logger=context.log,
            execution_id=execution_id,
            now=now,
        )

        if outcome.should_commit:
            transaction.commit()
        else:
            transaction.rollback()
    finally:
        connection.close()

    if outcome.is_failure:
        raise Failure(
            description=outcome.message,
            metadata={
                "status": outcome.status.name,
                "eligible_count": outcome.eligible_count,
                "notified_count": outcome.notified_count,
            },
        )

    context.log.info(outcome.message)


#: Job that materializes the single orchestration asset. Thin wrapper so the
#: schedule has a target and the integration test has something to execute.
daily_flight_search_job = define_asset_job(
    name="daily_flight_search_job",
    selection=[daily_flight_search],
)

#: Daily schedule (no catch-up/backfill — non-partitioned; see :data:`DAILY_CRON`
#: and Regra de Execução). Default status is stopped; the operator enables it.
daily_flight_search_schedule = ScheduleDefinition(
    name="daily_flight_search_schedule",
    job=daily_flight_search_job,
    cron_schedule=DAILY_CRON,
)

#: Top-level Dagster :class:`Definitions` loaded by ``dagster dev`` / the
#: repository's code location. The single entrypoint of the pipeline (no HTTP API,
#: no frontend — architecture.md §1).
defs = Definitions(
    assets=[daily_flight_search],
    jobs=[daily_flight_search_job],
    schedules=[daily_flight_search_schedule],
)
