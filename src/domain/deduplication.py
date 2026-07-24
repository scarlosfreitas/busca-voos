"""Deduplication rule (``docs/domain/regras_negocio.md`` — Regra de Deduplicação).

Compares the current price of an eligible flight against the last price alerted
for the same flight (identified by :attr:`domain.models.Flight.flight_id`):

* no previous alert -> notify (first occurrence);
* previous alert and price changed by any amount -> notify;
* previous alert and price exactly equal -> do not notify.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from domain.models import Flight


def should_notify(flight: Flight, last_alerted_price: Decimal | None) -> bool:
    """Return whether an eligible flight should generate an alert now.

    ``last_alerted_price`` is the last price alerted for this flight, or ``None``
    when no alert was ever sent for it.

    Contract: ``None`` -> ``True``; a different price -> ``True``; an identical
    price -> ``False`` (no minimum threshold — a R$ 0,01 change already counts).

    Implementation is left to dev-runner.
    """
    raise NotImplementedError


def select_flights_to_notify(
    flights: Sequence[Flight],
    last_alerted_prices: Mapping[str, Decimal],
) -> list[Flight]:
    """Return the subset of eligible flights that should generate an alert.

    ``last_alerted_prices`` maps ``flight_id`` to the last alerted price; a flight
    whose id is absent from the mapping has never been alerted.

    Contract: applies :func:`should_notify` per flight, preserving input order;
    an empty input yields an empty list.

    Implementation is left to dev-runner.
    """
    raise NotImplementedError
