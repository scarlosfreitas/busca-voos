"""Unit tests for the pure Gol payload parser (no browser).

These pin the extraction contract against synthetic fixtures and fail with
``NotImplementedError`` until dev-runner implements ``parse_gol_response``.

Coverage maps to the design cases:
* valid payload with flights → typed ``CapturedFlight`` records, in order;
* empty / no-availability → ``()`` (successful empty capture);
* not-the-expected-container → ``BlockedError`` (CAPTCHA/WAF/redirect);
* correct container, unparseable record → ``MalformedPayloadError``;
* boundary: present non-positive price is NOT an extraction error (domain owns it).
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from extraction.errors import BlockedError, MalformedPayloadError
from extraction.gol import CapturedFlight, parse_gol_response


class TestValidPayload:
    def test_returns_one_record_per_flight_in_order(self, sample_payload) -> None:
        flights = parse_gol_response(sample_payload)
        assert isinstance(flights, tuple)
        assert [f.flight_number for f in flights] == ["1234", "5678"]

    def test_first_flight_fields_are_faithful_and_typed(self, sample_payload) -> None:
        first = parse_gol_response(sample_payload)[0]
        assert first == CapturedFlight(
            carrier="G3",
            flight_number="1234",
            origin="MCP",
            destination="BSB",
            departure_date=date(2026, 9, 1),
            departure_time=time(8, 30),
            price=Decimal("1234.56"),
            currency="BRL",
            cabin="economy",
        )

    def test_price_is_decimal(self, sample_payload) -> None:
        first = parse_gol_response(sample_payload)[0]
        assert isinstance(first.price, Decimal)
        assert first.price == Decimal("1234.56")

    def test_departure_time_parsed_from_datetime(self, sample_payload) -> None:
        second = parse_gol_response(sample_payload)[1]
        assert second.departure_time == time(18, 45)


class TestEmptyPayload:
    def test_no_availability_returns_empty_tuple(self, empty_payload) -> None:
        assert parse_gol_response(empty_payload) == ()

    def test_no_trips_at_all_returns_empty_tuple(self) -> None:
        # trips present but empty -> a valid, successful, empty capture.
        assert parse_gol_response({"trips": []}) == ()


class TestBlockedPayload:
    def test_access_denied_envelope_raises_blocked(self, blocked_payload) -> None:
        with pytest.raises(BlockedError):
            parse_gol_response(blocked_payload)

    def test_missing_trips_key_raises_blocked(self) -> None:
        with pytest.raises(BlockedError):
            parse_gol_response({"unexpected": "shape"})

    def test_non_dict_payload_raises_blocked(self) -> None:
        with pytest.raises(BlockedError):
            parse_gol_response("<html>captcha challenge</html>")


class TestMalformedPayload:
    def test_missing_mandatory_field_raises_malformed(self, malformed_payload) -> None:
        # Correct container, but the flight record has no `fare`.
        with pytest.raises(MalformedPayloadError):
            parse_gol_response(malformed_payload)

    def test_non_numeric_price_raises_malformed(self) -> None:
        payload = {
            "trips": [
                {
                    "origin": "MCP",
                    "destination": "BSB",
                    "departureDate": "2026-09-01",
                    "flights": [
                        {
                            "airlineCode": "G3",
                            "flightNumber": "1234",
                            "departureDateTime": "2026-09-01T08:30:00",
                            "cabin": "economy",
                            "fare": {"amount": "not-a-number", "currency": "BRL"},
                        }
                    ],
                }
            ]
        }
        with pytest.raises(MalformedPayloadError):
            parse_gol_response(payload)

    def test_unparseable_datetime_raises_malformed(self) -> None:
        payload = {
            "trips": [
                {
                    "origin": "MCP",
                    "destination": "BSB",
                    "departureDate": "2026-09-01",
                    "flights": [
                        {
                            "airlineCode": "G3",
                            "flightNumber": "1234",
                            "departureDateTime": "not-a-datetime",
                            "cabin": "economy",
                            "fare": {"amount": "1000.00", "currency": "BRL"},
                        }
                    ],
                }
            ]
        }
        with pytest.raises(MalformedPayloadError):
            parse_gol_response(payload)


class TestPricePositivityBoundary:
    def test_zero_price_is_not_an_extraction_error(self) -> None:
        # A present, numeric, non-positive price is returned faithfully as Decimal.
        # Enforcing "price must be positive" is domain.validate_flight's job — the
        # rule stays single-sourced in the domain (regras_negocio.md §Validações).
        payload = {
            "trips": [
                {
                    "origin": "MCP",
                    "destination": "BSB",
                    "departureDate": "2026-09-01",
                    "flights": [
                        {
                            "airlineCode": "G3",
                            "flightNumber": "1234",
                            "departureDateTime": "2026-09-01T08:30:00",
                            "cabin": "economy",
                            "fare": {"amount": "0.00", "currency": "BRL"},
                        }
                    ],
                }
            ]
        }
        flights = parse_gol_response(payload)
        assert len(flights) == 1
        assert flights[0].price == Decimal("0.00")
