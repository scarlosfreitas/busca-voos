"""Domain entities for the flight-monitoring pipeline.

These dataclasses are the pure schema of the domain (the "gold"-level view of a
captured flight and of an alert). They carry no I/O and no dependency on
``extraction``/``persistence``/``notification`` — see
``docs/standards/architecture.md`` §2.

The business validations enforced by :func:`validate_flight` are traceable 1:1
with the "Validações" section of ``docs/domain/regras_negocio.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal


class InvalidFlightError(ValueError):
    """Raised when a captured flight fails a domain validation rule.

    A flight that raises this error is treated as an extraction failure for that
    flight, not as an eligible flight (see ``docs/domain/regras_negocio.md`` —
    Validações).
    """


@dataclass(frozen=True)
class Route:
    """A monitored route: origin/destination pair plus the outbound date.

    In the MVP this is fixed to MCP -> BSB, outbound 2026-09-01, but the schema
    is generic so future iterations can register other routes.
    """

    origin: str
    destination: str
    departure_date: date


@dataclass(frozen=True)
class Flight:
    """A single captured flight option for a monitored route.

    Attributes mirror the mandatory fields listed in the "Validações" section of
    ``docs/domain/regras_negocio.md``: carrier, flight number, origin/destination
    (via :attr:`route`), flight date (via :attr:`route`), departure time and the
    final price (numeric, taxes included) with its currency.
    """

    route: Route
    carrier: str
    flight_number: str
    departure_time: time
    price: Decimal
    currency: str

    @property
    def flight_id(self) -> str:
        """Deduplication key for this flight.

        Composed of route (origin, destination, outbound date) plus the flight
        number, per the "Identificador do voo" glossary entry in
        ``docs/domain/regras_negocio.md``.

        Contract (to be implemented by dev-runner): a stable string of the form
        ``"{origin}-{destination}-{YYYY-MM-DD}-{flight_number}"`` so that two
        captures of the same physical flight on different runs share one key.
        """
        departure_date = self.route.departure_date.isoformat()
        return f"{self.route.origin}-{self.route.destination}-{departure_date}-{self.flight_number}"


@dataclass(frozen=True)
class Alert:
    """Record of the last price effectively alerted for a given flight.

    This is the "Último preço alertado" concept from
    ``docs/domain/regras_negocio.md`` and is the persisted basis for the
    deduplication rule. Compiling the human-readable Telegram message from a set
    of flights is the job of the ``notification`` layer, not of this entity.
    """

    flight_id: str
    price: Decimal
    currency: str
    alerted_at: datetime


def validate_flight(flight: Flight) -> None:
    """Validate a captured flight against the domain rules.

    Enforces the "Validações" section of ``docs/domain/regras_negocio.md``:
    every mandatory field must be present/non-empty, the flight number is
    required, and the price must be a positive numeric value. Raises
    :class:`InvalidFlightError` on the first rule violated; returns ``None`` for
    a valid flight.

    Implementation is left to dev-runner.
    """
    required_fields = {
        "carrier": flight.carrier,
        "flight_number": flight.flight_number,
        "origin": flight.route.origin,
        "destination": flight.route.destination,
        "currency": flight.currency,
    }
    for name, value in required_fields.items():
        if not value:
            raise InvalidFlightError(f"{name} must not be empty")

    if flight.price is None or flight.price <= 0:
        raise InvalidFlightError("price must be a strictly positive number")
