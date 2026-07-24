"""Gol-specific navigation + network interception, and the pure payload parser.

Two responsibilities, deliberately split so the parsing logic is unit-testable
without a real browser or the real Gol site:

* :func:`parse_gol_response` — **pure** function: intercepted JSON → typed
  ``CapturedFlight`` records. Fully covered by synthetic fixtures in
  ``test/extraction/fixtures/``. Fails with ``NotImplementedError`` until
  dev-runner implements it.
* :func:`capture_gol_search` — **I/O**: opens the browser, navigates the Gol
  search for the monitored route (MCP→BSB, 2026-09-01, 1 adult, economy),
  intercepts the availability XHR/Fetch response, and returns a
  :class:`GolCaptureResult` bundling the raw payload (for the bronze layer) and
  the parsed flights (for orchestration → silver/domain). Integration-only.

Decoupling (``architecture.md`` §2): this module depends on neither ``domain``
nor ``persistence``. It emits its own :class:`CapturedFlight` value object; the
``orchestration`` layer maps it to ``domain.models.Flight`` (applying
``domain.models.validate_flight``) and persists the raw payload to
``bronze.raw_search_response``. Extraction never enforces domain rules itself —
notably the "preço positivo" validation (``regras_negocio.md`` §Validações) stays
single-sourced in ``domain``; see the boundary note on price below.

Captura via interceptação de rede, NÃO parsing de HTML (PRD §8).

.. warning::
   The JSON shape assumed below is **synthetic** — no real Gol payload has been
   captured yet. The field paths, the ``GOL_*`` URL constants and the block
   heuristic are placeholders. dev-runner must confirm them against a real
   intercepted response; the *contract* (signatures, return types, error
   semantics, the pure/I-O split) is stable regardless of the exact shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from .browser import BrowserConfig, human_delay, stealth_page_session
from .errors import (
    BlockedError,
    ExtractionError,
    ExtractionTimeoutError,
    MalformedPayloadError,
)

CABIN_ECONOMY = "economy"

# Top-level key the (synthetic) Gol availability JSON is expected to carry. Its
# absence is the signal used to distinguish a block/challenge from a malformed
# record — see parse_gol_response. Placeholder; confirm against a real payload.
GOL_TRIPS_KEY = "trips"

# Placeholder identifiers for the search deep-link and the availability endpoint
# whose response we intercept. dev-runner replaces with the real values.
GOL_SEARCH_URL = "https://www.voegol.com.br/"
GOL_AVAILABILITY_URL_FRAGMENT = "/api/flight/availability"


@dataclass(frozen=True)
class GolSearchParams:
    """Parameters of one Gol search — the "Parâmetros de busca" of the domain.

    ``adults`` and ``cabin`` are fixed by ``regras_negocio.md`` (1 adult, economy)
    and default accordingly; a capture made with any other configuration is
    invalid for the MVP.
    """

    origin: str
    destination: str
    departure_date: date
    adults: int = 1
    cabin: str = CABIN_ECONOMY


# Single source of truth for the MVP monitored search (architecture.md §5):
# Macapá → Brasília, outbound 2026-09-01, 1 adult, economy.
MVP_SEARCH_PARAMS = GolSearchParams(
    origin="MCP", destination="BSB", departure_date=date(2026, 9, 1)
)


@dataclass(frozen=True)
class CapturedFlight:
    """One flight option extracted from the intercepted payload ("Voo capturado").

    Extraction-local value object (NOT ``domain.models.Flight``) so ``extraction``
    stays decoupled from ``domain``. Fields are kept faithful to the payload:
    ``carrier``/``flight_number`` are the raw designator parts (e.g. ``"G3"`` /
    ``"1234"``) — orchestration composes the domain dedup key and translates the
    carrier when building ``domain.models.Flight``. Prices are typed to
    :class:`~decimal.Decimal` (never float) to preserve exact money semantics.
    """

    carrier: str
    flight_number: str
    origin: str
    destination: str
    departure_date: date
    departure_time: time
    price: Decimal
    currency: str
    cabin: str


@dataclass(frozen=True)
class GolCaptureResult:
    """Result of one Gol capture: raw payload (bronze) + parsed flights.

    :attr:`raw_payload` is the intercepted JSON exactly as received, to be stored
    verbatim in ``bronze.raw_search_response`` (append-only, no transformation —
    ``architecture.md`` §3). :attr:`flights` is the typed projection produced by
    :func:`parse_gol_response`, consumed by orchestration. An empty
    :attr:`flights` with a well-formed :attr:`raw_payload` is a *successful* run
    with no availability (``regras_negocio.md`` — Elegibilidade, caso de borda).
    """

    raw_payload: Any
    flights: tuple[CapturedFlight, ...]


def parse_gol_response(payload: Any) -> tuple[CapturedFlight, ...]:
    """Parse an intercepted Gol availability payload into ``CapturedFlight`` records.

    Pure function — the heart of the testable extraction logic. Contract (pinned
    by ``test/extraction/test_parse_gol_response.py`` against the synthetic
    fixtures):

    Assumed synthetic shape::

        {
          "trips": [
            {
              "origin": "MCP", "destination": "BSB", "departureDate": "2026-09-01",
              "flights": [
                {
                  "airlineCode": "G3", "flightNumber": "1234",
                  "departureDateTime": "2026-09-01T08:30:00",
                  "cabin": "economy",
                  "fare": {"amount": "1234.56", "currency": "BRL"}
                }
              ]
            }
          ]
        }

    Behaviour:

    * Valid payload → a tuple of :class:`CapturedFlight`, one per flight across all
      trips, in document order. ``price`` is ``Decimal(fare.amount)``;
      ``departure_date``/``departure_time`` come from ``departureDateTime``.
    * ``trips`` present but no flights (empty list / empty ``flights``) → ``()``.
      This is "sem disponibilidade": a valid, successful, empty capture.
    * Payload is not the expected container (not a ``dict``, or missing the
      ``trips`` key) → :class:`~extraction.errors.BlockedError`. Rationale: we
      expected the API JSON and got something else (challenge/redirect/WAF).
    * Container is correct but a flight record misses a mandatory field or carries
      a value that cannot be typed (non-numeric ``fare.amount``, unparseable
      ``departureDateTime``) → :class:`~extraction.errors.MalformedPayloadError`.

    Boundary note (single-sourcing): a *present but non-positive* price
    (``0``/negative) is returned faithfully as a ``Decimal`` here — it is NOT an
    extraction error. The "preço deve ser positivo" rule
    (``regras_negocio.md`` §Validações) is enforced downstream by
    ``domain.models.validate_flight`` when orchestration builds the ``Flight``,
    keeping that rule in one place. Implementation left to dev-runner.
    """
    if not isinstance(payload, dict) or GOL_TRIPS_KEY not in payload:
        raise BlockedError(
            "Expected the Gol availability JSON container "
            f"(missing '{GOL_TRIPS_KEY}' key or not a JSON object)"
        )

    trips = payload[GOL_TRIPS_KEY]
    if not isinstance(trips, list):
        raise BlockedError(f"'{GOL_TRIPS_KEY}' is not a list")

    flights: list[CapturedFlight] = []
    for trip in trips:
        if not isinstance(trip, dict):
            raise MalformedPayloadError("Each trip must be a JSON object")

        origin = trip.get("origin")
        destination = trip.get("destination")
        trip_flights = trip.get("flights", [])
        if not isinstance(trip_flights, list):
            raise MalformedPayloadError("Trip 'flights' must be a list")

        for flight in trip_flights:
            if not isinstance(flight, dict):
                raise MalformedPayloadError("Each flight record must be a JSON object")

            carrier = flight.get("airlineCode")
            flight_number = flight.get("flightNumber")
            departure_datetime_raw = flight.get("departureDateTime")
            cabin = flight.get("cabin")
            fare = flight.get("fare")

            if not isinstance(fare, dict):
                raise MalformedPayloadError("Flight record is missing 'fare'")

            amount = fare.get("amount")
            currency = fare.get("currency")

            if (
                not carrier
                or not flight_number
                or not origin
                or not destination
                or not departure_datetime_raw
                or not cabin
                or amount is None
                or not currency
            ):
                raise MalformedPayloadError(
                    "Flight record is missing a mandatory field"
                )

            try:
                price = Decimal(str(amount))
            except (InvalidOperation, ValueError) as exc:
                raise MalformedPayloadError(
                    f"Flight fare amount is not numeric: {amount!r}"
                ) from exc

            try:
                departure_datetime = datetime.fromisoformat(str(departure_datetime_raw))
            except ValueError as exc:
                raise MalformedPayloadError(
                    f"Flight departureDateTime is not a valid datetime: "
                    f"{departure_datetime_raw!r}"
                ) from exc

            flights.append(
                CapturedFlight(
                    carrier=str(carrier),
                    flight_number=str(flight_number),
                    origin=str(origin),
                    destination=str(destination),
                    departure_date=departure_datetime.date(),
                    departure_time=departure_datetime.time(),
                    price=price,
                    currency=str(currency),
                    cabin=str(cabin),
                )
            )

    return tuple(flights)


async def capture_gol_search(
    params: GolSearchParams = MVP_SEARCH_PARAMS,
    *,
    browser_config: BrowserConfig | None = None,
) -> GolCaptureResult:
    """Drive the Gol site and intercept the availability response (I/O).

    Integration-only (real browser + real Gol network). Contract:

    * Open a stealthed page via ``browser.stealth_page_session`` (``browser_config``
      defaults to ``BrowserConfig.from_env()``).
    * Navigate the public, anonymous search for ``params`` (MCP→BSB, 2026-09-01,
      1 adult, economy) with simulated human delays.
    * Register a response interceptor for the availability endpoint
      (:data:`GOL_AVAILABILITY_URL_FRAGMENT`); await it within the long timeout.
    * On success → ``GolCaptureResult(raw_payload=<json>, flights=parse_gol_response(<json>))``.

    Failure translation (never leak a raw library exception):

    * Awaited response never arrives / navigation times out →
      :class:`~extraction.errors.ExtractionTimeoutError`.
    * CAPTCHA/challenge/non-API response detected (directly, or via
      :func:`parse_gol_response` raising) → :class:`~extraction.errors.BlockedError`.
    * Well-formed container with an unparseable record →
      :class:`~extraction.errors.MalformedPayloadError` (propagated from the parser).

    Implementation left to dev-runner.
    """
    config = browser_config if browser_config is not None else BrowserConfig.from_env()

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise ExtractionError(f"Playwright is not available: {exc}") from exc

    try:
        async with stealth_page_session(config) as page:
            await human_delay(config)

            async with page.expect_response(
                lambda response: GOL_AVAILABILITY_URL_FRAGMENT in response.url,
                timeout=config.navigation_timeout_ms,
            ) as response_info:
                await page.goto(GOL_SEARCH_URL, timeout=config.navigation_timeout_ms)
                await human_delay(config)

            response = await response_info.value

            try:
                raw_payload = await response.json()
            except Exception as exc:
                raise BlockedError(
                    f"Availability response was not valid JSON: {exc}"
                ) from exc

    except PlaywrightTimeoutError as exc:
        raise ExtractionTimeoutError(
            f"Timed out waiting for the Gol availability response: {exc}"
        ) from exc
    except (BlockedError, MalformedPayloadError, ExtractionTimeoutError):
        raise
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Gol capture failed: {exc}") from exc

    flights = parse_gol_response(raw_payload)
    return GolCaptureResult(raw_payload=raw_payload, flights=flights)
