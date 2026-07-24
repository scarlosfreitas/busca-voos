"""Tests for the eligibility rule (docs/domain/regras_negocio.md).

MVP: every successfully captured flight is eligible (identity), including the
edge case of zero captured flights.
"""

from __future__ import annotations

from decimal import Decimal

from domain.eligibility import is_eligible, select_eligible

from .conftest import make_flight


class TestIsEligible:
    def test_any_captured_flight_is_eligible(self) -> None:
        assert is_eligible(make_flight()) is True

    def test_high_priced_flight_is_still_eligible(self) -> None:
        # No price ceiling in the MVP: even an expensive fare is eligible.
        assert is_eligible(make_flight(price=Decimal("99999.99"))) is True


class TestSelectEligible:
    def test_returns_all_captured_flights(self) -> None:
        flights = [
            make_flight(flight_number="G3-1000"),
            make_flight(flight_number="G3-2000"),
        ]
        assert select_eligible(flights) == flights

    def test_preserves_input_order(self) -> None:
        a = make_flight(flight_number="G3-1000")
        b = make_flight(flight_number="G3-2000")
        c = make_flight(flight_number="G3-3000")
        assert select_eligible([b, a, c]) == [b, a, c]

    def test_empty_capture_yields_no_eligible_flights(self) -> None:
        # Edge case: route with no availability -> nothing eligible.
        assert select_eligible([]) == []
