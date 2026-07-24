"""Eligibility rule (``docs/domain/regras_negocio.md`` — Regra de Elegibilidade).

In the MVP every successfully captured flight is eligible: there is no price
ceiling. The rule is kept as an explicit, extensible function (a future
iteration may add a fixed ceiling or a percentage-drop rule) instead of being
inlined at the call site.
"""

from __future__ import annotations

from collections.abc import Sequence

from domain.models import Flight


def is_eligible(flight: Flight) -> bool:
    """Return whether a captured flight is eligible for alerting.

    MVP contract: identity — a successfully captured flight is always eligible.

    Implementation is left to dev-runner.
    """
    raise NotImplementedError


def select_eligible(flights: Sequence[Flight]) -> list[Flight]:
    """Return the subset of captured flights that are eligible.

    MVP contract: returns all input flights, preserving order; an empty input
    yields an empty list (no captured flights -> no eligible flights).

    Implementation is left to dev-runner.
    """
    raise NotImplementedError
