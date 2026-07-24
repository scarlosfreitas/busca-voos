"""QA-authored gap-fill tests for ``parse_gol_response`` (independent of dev-runner).

Written by the `qa` agent to probe edge cases not explicitly pinned by
``test_parse_gol_response.py``: order preservation across *multiple* trips
(not just multiple flights within one trip), a negative price boundary
(symmetric to the zero-price boundary already covered), and an unexpected
time format inside ``departureDateTime``. Synthetic data only.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal

import pytest

from extraction.errors import MalformedPayloadError
from extraction.gol import parse_gol_response


def _flight(
    flight_number: str, departure_datetime: str, amount: str = "1000.00"
) -> dict:
    return {
        "airlineCode": "G3",
        "flightNumber": flight_number,
        "departureDateTime": departure_datetime,
        "cabin": "economy",
        "fare": {"amount": amount, "currency": "BRL"},
    }


class TestMultipleTripsOrderPreserved:
    def test_flights_across_multiple_trips_preserve_document_order(self) -> None:
        payload = {
            "trips": [
                {
                    "origin": "MCP",
                    "destination": "BSB",
                    "departureDate": "2026-09-01",
                    "flights": [_flight("1111", "2026-09-01T06:00:00")],
                },
                {
                    "origin": "MCP",
                    "destination": "BSB",
                    "departureDate": "2026-09-01",
                    "flights": [
                        _flight("2222", "2026-09-01T09:00:00"),
                        _flight("3333", "2026-09-01T12:00:00"),
                    ],
                },
            ]
        }
        flights = parse_gol_response(payload)
        assert [f.flight_number for f in flights] == ["1111", "2222", "3333"]


class TestNegativePriceBoundary:
    def test_negative_price_is_not_an_extraction_error(self) -> None:
        # Symmetric to the zero-price boundary pinned by dev-planner: a present,
        # numeric, negative price is returned faithfully — not extraction's job
        # to reject it (domain.validate_flight owns "price must be positive").
        payload = {
            "trips": [
                {
                    "origin": "MCP",
                    "destination": "BSB",
                    "departureDate": "2026-09-01",
                    "flights": [
                        _flight("1234", "2026-09-01T08:30:00", amount="-50.00")
                    ],
                }
            ]
        }
        flights = parse_gol_response(payload)
        assert len(flights) == 1
        assert flights[0].price == Decimal("-50.00")


class TestUnexpectedTimeFormat:
    def test_date_only_departure_datetime_is_silently_accepted_as_midnight(
        self,
    ) -> None:
        # QA finding (spec ambiguity, not a dev-runner bug): datetime.fromisoformat
        # accepts a date-only string and defaults the time to 00:00:00, so a
        # `departureDateTime` missing its time component is NOT rejected as
        # MalformedPayloadError -- it silently produces a (likely wrong)
        # midnight `departure_time`. The plan ("departureDateTime impossível de
        # tipar" -> MalformedPayloadError) is satisfied to the letter (it IS
        # typeable), but this edge case is not covered by dev-planner's fixtures
        # and the current behavior may hide a real data-quality issue. Documented
        # here as current behavior, not asserted as desired; escalate to
        # dev-planner to decide whether date-only should be MalformedPayloadError.
        payload = {
            "trips": [
                {
                    "origin": "MCP",
                    "destination": "BSB",
                    "departureDate": "2026-09-01",
                    "flights": [_flight("1234", "2026-09-01")],
                }
            ]
        }
        flights = parse_gol_response(payload)
        assert flights[0].departure_time == time(0, 0)

    def test_slash_separated_datetime_raises_malformed(self) -> None:
        # A plausible "wrong shape" a real Gol payload might carry instead of ISO.
        payload = {
            "trips": [
                {
                    "origin": "MCP",
                    "destination": "BSB",
                    "departureDate": "2026-09-01",
                    "flights": [_flight("1234", "01/09/2026 08:30")],
                }
            ]
        }
        with pytest.raises(MalformedPayloadError):
            parse_gol_response(payload)
