"""Tests for the deduplication rule (docs/domain/regras_negocio.md).

Covers: first occurrence (no prior alert), any price change (no minimum
threshold), and an identical price (no notification).
"""

from __future__ import annotations

from decimal import Decimal

from domain.deduplication import select_flights_to_notify, should_notify

from .conftest import make_flight


class TestShouldNotify:
    def test_no_previous_alert_notifies(self) -> None:
        assert should_notify(make_flight(), last_alerted_price=None) is True

    def test_changed_price_notifies(self) -> None:
        flight = make_flight(price=Decimal("1000.00"))
        assert should_notify(flight, last_alerted_price=Decimal("1200.00")) is True

    def test_one_cent_change_notifies(self) -> None:
        # No minimum threshold: a R$ 0,01 difference already counts.
        flight = make_flight(price=Decimal("1000.01"))
        assert should_notify(flight, last_alerted_price=Decimal("1000.00")) is True

    def test_price_drop_notifies(self) -> None:
        flight = make_flight(price=Decimal("800.00"))
        assert should_notify(flight, last_alerted_price=Decimal("1000.00")) is True

    def test_identical_price_does_not_notify(self) -> None:
        flight = make_flight(price=Decimal("1000.00"))
        assert should_notify(flight, last_alerted_price=Decimal("1000.00")) is False

    def test_identical_price_scale_insensitive(self) -> None:
        # 1000 and 1000.00 are numerically equal -> no notification.
        flight = make_flight(price=Decimal("1000"))
        assert should_notify(flight, last_alerted_price=Decimal("1000.00")) is False


class TestSelectFlightsToNotify:
    def test_first_occurrence_and_changed_are_selected_unchanged_kept_out(self) -> None:
        new_flight = make_flight(flight_number="G3-1000", price=Decimal("500.00"))
        changed_flight = make_flight(flight_number="G3-2000", price=Decimal("700.00"))
        unchanged_flight = make_flight(flight_number="G3-3000", price=Decimal("900.00"))

        last_alerted = {
            changed_flight.flight_id: Decimal("650.00"),
            unchanged_flight.flight_id: Decimal("900.00"),
        }

        result = select_flights_to_notify(
            [new_flight, changed_flight, unchanged_flight], last_alerted
        )
        assert result == [new_flight, changed_flight]

    def test_preserves_input_order(self) -> None:
        a = make_flight(flight_number="G3-1000")
        b = make_flight(flight_number="G3-2000")
        assert select_flights_to_notify([b, a], {}) == [b, a]

    def test_all_identical_yields_empty(self) -> None:
        flight = make_flight(flight_number="G3-1000", price=Decimal("1000.00"))
        last_alerted = {flight.flight_id: Decimal("1000.00")}
        assert select_flights_to_notify([flight], last_alerted) == []

    def test_empty_input_yields_empty(self) -> None:
        assert select_flights_to_notify([], {}) == []
