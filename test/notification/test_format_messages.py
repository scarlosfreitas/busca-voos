"""Unit tests for the pure message-composition contract (no network).

These fail today by ``NotImplementedError`` — the reason we want at this stage:
the contract (signatures, content, ordering, Brazilian formatting) is pinned and
dev-runner fills the bodies without touching the assertions.

Assertions check *content* (substrings, ordering, price format) rather than the
exact full wording, leaving dev-runner free on layout while fixing the pieces the
business rule mandates: Cia, Data, Trecho, horário, preço, data da pesquisa.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from notification.telegram import (
    format_failure_message,
    format_flight_alert_message,
    format_price,
)

SEARCH_DATE = date(2026, 7, 24)


# --- format_price -----------------------------------------------------------


def test_format_price_brl_with_thousands_separator() -> None:
    assert format_price(Decimal("1234.56"), "BRL") == "R$ 1.234,56"


def test_format_price_brl_keeps_two_decimals() -> None:
    assert format_price(Decimal("890.00"), "BRL") == "R$ 890,00"


def test_format_price_non_brl_is_generic() -> None:
    # Non-BRL currency renders generically with the currency code and two decimals.
    rendered = format_price(Decimal("1234.56"), "USD")
    assert "USD" in rendered
    assert "R$" not in rendered


# --- format_flight_alert_message: single flight -----------------------------


def test_alert_message_single_flight_has_all_mandatory_fields(flight_factory) -> None:
    flight = flight_factory()
    message = format_flight_alert_message([flight], SEARCH_DATE)

    assert isinstance(message, str)
    # Cia (carrier)
    assert "GOL" in message
    # Trecho (route origin -> destination)
    assert "MCP" in message
    assert "BSB" in message
    # Data do voo (route departure_date, 2026-09-01) in Brazilian format
    assert "01/09/2026" in message
    # Horário de partida (08:30)
    assert "08:30" in message
    # Preço (BRL formatted)
    assert "R$ 1.234,56" in message
    # Data da pesquisa (search date) in Brazilian format
    assert "24/07/2026" in message


def test_alert_message_states_search_date_once(flight_factory) -> None:
    message = format_flight_alert_message([flight_factory()], SEARCH_DATE)
    assert message.count("24/07/2026") == 1


# --- format_flight_alert_message: multiple flights, order preserved ---------


def test_alert_message_multiple_flights_preserve_order(flight_factory) -> None:
    first = flight_factory(
        flight_number="G3-1111", departure_time=time(6, 0), price=Decimal("500.00")
    )
    second = flight_factory(
        flight_number="G3-2222", departure_time=time(9, 15), price=Decimal("750.10")
    )
    third = flight_factory(
        flight_number="G3-3333", departure_time=time(20, 45), price=Decimal("990.99")
    )

    message = format_flight_alert_message([first, second, third], SEARCH_DATE)

    # All three flights are rendered.
    assert "06:00" in message
    assert "09:15" in message
    assert "20:45" in message
    assert "R$ 500,00" in message
    assert "R$ 750,10" in message
    assert "R$ 990,99" in message

    # Order is preserved (rendered top-to-bottom in input order).
    assert message.index("06:00") < message.index("09:15") < message.index("20:45")


def test_alert_message_is_single_message_for_all_flights(flight_factory) -> None:
    # One message per run: all flights compiled into a single string.
    flights = [flight_factory(flight_number=f"G3-{n}") for n in (1, 2, 3, 4)]
    message = format_flight_alert_message(flights, SEARCH_DATE)
    assert isinstance(message, str)
    assert message.count("24/07/2026") == 1  # search date stated once, one message


# --- format_flight_alert_message: empty input is a programming error ---------


def test_alert_message_empty_list_raises() -> None:
    # Deciding NOT to notify on an empty list belongs to orchestration (it must
    # not call this function). Composing an "empty alert" is therefore an error.
    with pytest.raises(ValueError):
        format_flight_alert_message([], SEARCH_DATE)


# --- format_failure_message -------------------------------------------------


def test_failure_message_includes_error_detail_and_search_date(route) -> None:
    error = RuntimeError("captcha wall detected")
    message = format_failure_message(error, search_date=SEARCH_DATE, route=route)

    assert isinstance(message, str)
    assert message  # non-empty
    # Underlying error text surfaced for diagnosis.
    assert "captcha wall detected" in message
    # Search date present.
    assert "24/07/2026" in message
    # Affected trecho present when a route is given.
    assert "MCP" in message
    assert "BSB" in message


def test_failure_message_without_route(route) -> None:
    # Route is optional (an early failure may not know it yet).
    message = format_failure_message(
        ValueError("boom"), search_date=SEARCH_DATE, route=None
    )
    assert isinstance(message, str)
    assert "boom" in message
    assert "24/07/2026" in message


def test_failure_message_distinguishes_extraction_error_types(route) -> None:
    # Distinct extraction failure types must not render identically: a human label
    # is derived from the exception *type*. We hold the error message text
    # constant so the difference can only come from the type-derived label, not
    # from the echoed ``str(error)``. The test may import extraction; the
    # notification module must not (dependency direction) — dev-runner keys off
    # the exception class/name, not an isinstance import of extraction.
    from extraction.errors import BlockedError, ExtractionTimeoutError

    same_text = "extraction stopped"
    blocked = format_failure_message(
        BlockedError(same_text), search_date=SEARCH_DATE, route=route
    )
    timeout = format_failure_message(
        ExtractionTimeoutError(same_text), search_date=SEARCH_DATE, route=route
    )
    assert blocked != timeout
