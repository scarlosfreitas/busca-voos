"""QA-authored edge-case tests for the composition contract.

Complements ``test_format_messages.py`` (dev-planner's contract suite) with
cases not pinned there: zero-value price, sub-unit price, and special
characters in free-text fields (carrier name) that could break message
rendering if it ever moved to an escaped ``parse_mode``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from notification.telegram import format_flight_alert_message, format_price

SEARCH_DATE = date(2026, 7, 24)


def test_format_price_zero() -> None:
    assert format_price(Decimal("0.00"), "BRL") == "R$ 0,00"


def test_format_price_sub_unit_cents() -> None:
    assert format_price(Decimal("0.01"), "BRL") == "R$ 0,01"


def test_format_price_large_value_multiple_thousand_separators() -> None:
    assert format_price(Decimal("1000000.00"), "BRL") == "R$ 1.000.000,00"


def test_alert_message_carrier_with_special_characters_is_not_mangled(
    flight_factory,
) -> None:
    # A carrier/free-text field containing characters that would need escaping
    # under an HTML parse_mode must still render intact under the current
    # plain-text (parse_mode=None) contract.
    flight = flight_factory(carrier="GOL <Test> & Co.")
    message = format_flight_alert_message([flight], SEARCH_DATE)
    assert "GOL <Test> & Co." in message
