"""Telegram notification layer.

Public surface re-exported for the ``orchestration`` layer, which composes a
message from the deduplicated flights (or from an extraction failure) and sends
it. See ``src/notification/telegram.py`` for the full contract.
"""

from __future__ import annotations

from notification.telegram import (
    DEFAULT_TIMEOUT_SECONDS,
    TELEGRAM_API_BASE,
    NotificationError,
    TelegramConfig,
    format_failure_message,
    format_flight_alert_message,
    format_price,
    send_telegram_message,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "TELEGRAM_API_BASE",
    "NotificationError",
    "TelegramConfig",
    "format_failure_message",
    "format_flight_alert_message",
    "format_price",
    "send_telegram_message",
]
