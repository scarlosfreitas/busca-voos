"""QA-authored integration tests probing gaps not covered by dev-planner's suite.

Independent validation (per .claude/agents/qa.md) of src/persistence/ against
docs/domain/regras_negocio.md (Regra de Deduplicação, Regra de Persistência) and
.claude/plans/2026-07-24-dev-persistence.md. Skips automatically without a
reachable Postgres, same gate as test_repositories_integration.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from domain.deduplication import select_flights_to_notify
from domain.models import Alert, Route
from persistence.repositories import BronzeRepository, GoldRepository, SilverRepository

from .conftest import MONITORED_ROUTE, make_flight

_NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


class TestLastAlertedPricesInsertionOrderIndependence:
    def test_reflects_most_recent_alerted_at_even_when_inserted_out_of_order(
        self, pg_connection
    ) -> None:
        """The 'most recent' price must be decided by alerted_at, never by
        insertion/row order. Insert the *newer* alert first, then the older
        one, to make sure the query isn't accidentally relying on row order
        (e.g. 'last row wins' instead of MAX(alerted_at))."""
        repo = GoldRepository(pg_connection)
        flight_id = "MCP-BSB-2026-09-01-G3-7777"

        newer = Alert(
            flight_id=flight_id,
            price=Decimal("500.00"),
            currency="BRL",
            alerted_at=datetime(2026, 7, 24, 12, 0, tzinfo=UTC),
        )
        older = Alert(
            flight_id=flight_id,
            price=Decimal("900.00"),
            currency="BRL",
            alerted_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        )

        # Insert newer first, older second -- inverse of chronological order.
        repo.record_alerts(execution_id=uuid4(), alerts=[newer])
        repo.record_alerts(execution_id=uuid4(), alerts=[older])

        prices = repo.last_alerted_prices(MONITORED_ROUTE)
        assert prices[flight_id] == Decimal("500.00")

    def test_three_alerts_same_flight_keeps_only_latest_price(
        self, pg_connection
    ) -> None:
        repo = GoldRepository(pg_connection)
        flight_id = "MCP-BSB-2026-09-01-G3-8888"
        prices_and_times = [
            (Decimal("1000.00"), datetime(2026, 7, 20, 8, 0, tzinfo=UTC)),
            (Decimal("850.00"), datetime(2026, 7, 22, 8, 0, tzinfo=UTC)),
            (Decimal("910.00"), datetime(2026, 7, 24, 8, 0, tzinfo=UTC)),
        ]
        for price, alerted_at in prices_and_times:
            repo.record_alerts(
                execution_id=uuid4(),
                alerts=[
                    Alert(
                        flight_id=flight_id,
                        price=price,
                        currency="BRL",
                        alerted_at=alerted_at,
                    )
                ],
            )

        prices = repo.last_alerted_prices(MONITORED_ROUTE)
        assert prices[flight_id] == Decimal("910.00")


class TestLastAlertedPricesRouteIsolation:
    def test_alerts_from_a_different_route_are_not_returned(
        self, pg_connection
    ) -> None:
        """Regra de Deduplicação keys on rota+data+número do voo. An alert for
        the same flight number but a different departure_date must not leak
        into another route's last_alerted_prices (prefix filter correctness).
        """
        other_route = Route(
            origin="MCP", destination="BSB", departure_date=date(2026, 10, 1)
        )
        repo = GoldRepository(pg_connection)

        # Same carrier/flight_number, different date -> different flight_id.
        other_route_alert = Alert(
            flight_id="MCP-BSB-2026-10-01-G3-1234",
            price=Decimal("111.00"),
            currency="BRL",
            alerted_at=_NOW,
        )
        monitored_route_alert = Alert(
            flight_id="MCP-BSB-2026-09-01-G3-1234",
            price=Decimal("222.00"),
            currency="BRL",
            alerted_at=_NOW,
        )
        repo.record_alerts(
            execution_id=uuid4(), alerts=[other_route_alert, monitored_route_alert]
        )

        prices = repo.last_alerted_prices(MONITORED_ROUTE)
        assert prices == {"MCP-BSB-2026-09-01-G3-1234": Decimal("222.00")}
        assert "MCP-BSB-2026-10-01-G3-1234" not in prices

        other_prices = repo.last_alerted_prices(other_route)
        assert other_prices == {"MCP-BSB-2026-10-01-G3-1234": Decimal("111.00")}


class TestGoldAppendOnly:
    def test_record_alerts_never_mutates_prior_rows_row_count_grows(
        self, pg_connection
    ) -> None:
        """Regra de Persistência: gold é histórico append-only. Sending two
        alerts for the same flight_id at different prices must result in two
        rows, not one row updated in place."""
        from sqlalchemy import func, select

        from persistence.tables import flight_alert

        repo = GoldRepository(pg_connection)
        flight_id = "MCP-BSB-2026-09-01-G3-9999"

        repo.record_alerts(
            execution_id=uuid4(),
            alerts=[
                Alert(
                    flight_id=flight_id,
                    price=Decimal("100.00"),
                    currency="BRL",
                    alerted_at=datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
                )
            ],
        )
        repo.record_alerts(
            execution_id=uuid4(),
            alerts=[
                Alert(
                    flight_id=flight_id,
                    price=Decimal("200.00"),
                    currency="BRL",
                    alerted_at=datetime(2026, 7, 21, 8, 0, tzinfo=UTC),
                )
            ],
        )

        count = pg_connection.execute(
            select(func.count())
            .select_from(flight_alert)
            .where(flight_alert.c.flight_id == flight_id)
        ).scalar_one()
        assert count == 2


class TestBronzeWithoutSilver:
    def test_bronze_success_recorded_even_when_no_flights_are_eligible(
        self, pg_connection
    ) -> None:
        """Regra de Execução/Persistência edge case: a run with a reachable
        network response but zero flights returned must still count as a
        successful bronze write, with silver staying empty -- this is what
        makes the run 'bem-sucedida' per the Validações section even with 0
        eligible flights, and it must not raise trying to save an empty
        flights sequence to silver."""
        bronze = BronzeRepository(pg_connection)
        silver = SilverRepository(pg_connection)
        execution_id = uuid4()

        bronze_id = bronze.save_raw_response(
            execution_id=execution_id,
            route=MONITORED_ROUTE,
            captured_at=_NOW,
            success=True,
            payload={"trips": []},
        )
        silver_ids = silver.save_flights(
            execution_id=execution_id, captured_at=_NOW, flights=[]
        )

        assert isinstance(bronze_id, int)
        assert silver_ids == []


class TestDeduplicationEndToEndWithFreshFlight:
    def test_flight_never_alerted_is_treated_as_first_occurrence(
        self, pg_connection
    ) -> None:
        """No gold history at all for a brand-new flight_id -> select_flights_to_notify
        must include it (absence == never alerted, not '0 price change')."""
        repo = GoldRepository(pg_connection)
        brand_new = make_flight(flight_number="G3-0001", price=Decimal("321.00"))

        last_prices = repo.last_alerted_prices(MONITORED_ROUTE)
        to_notify = select_flights_to_notify([brand_new], last_prices)
        assert to_notify == [brand_new]
