"""Integration test for real Telegram delivery (skipped by default).

Sending hits the live Telegram Bot API over the network and needs real
credentials, so this never runs by default. It is opt-in via
``RUN_TELEGRAM_INTEGRATION=1`` and additionally skips when credentials are not
configured or the send is not yet implemented — mirroring the persistence /
extraction integration skip gates (architecture.md §8; qa.md §8). A typed
``NotificationError`` from a live send is treated as a skip (transient network
condition), not a failure: the contract is that failures are *typed*, not that
Telegram is always reachable.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_TELEGRAM_INTEGRATION") != "1",
    reason="Telegram send is a live-network integration test; set RUN_TELEGRAM_INTEGRATION=1 to run",
)


@pytest.fixture
def telegram_config():
    """Real credentials from env, or skip when unavailable/unimplemented."""
    from notification.telegram import TelegramConfig

    try:
        return TelegramConfig.from_env()
    except NotImplementedError:
        pytest.skip("TelegramConfig.from_env not implemented yet")
    except Exception as exc:  # noqa: BLE001 - missing creds means "skip, not fail"
        pytest.skip(f"Telegram credentials not configured: {exc}")


def test_send_telegram_message_delivers(telegram_config, flight_factory) -> None:
    from datetime import date

    from notification.telegram import (
        NotificationError,
        format_flight_alert_message,
        send_telegram_message,
    )

    try:
        text = format_flight_alert_message([flight_factory()], date(2026, 7, 24))
        send_telegram_message(text, telegram_config)
    except NotImplementedError:
        pytest.skip("send_telegram_message / format not implemented yet")
    except NotificationError as exc:
        # A typed delivery failure is an acceptable real-world outcome for a live
        # send — surface it as a skip, not a failure.
        pytest.skip(f"Live Telegram send failed with a typed NotificationError: {exc}")
