"""QA-authored unit tests for ``send_telegram_message`` failure handling.

These mock ``httpx.post`` so they run without network/credentials (unlike
``test_send_integration.py``, which is a live opt-in test). They target gaps not
covered by the dev-planner's contract test suite:

* transport error -> ``NotificationError`` (never a raw ``httpx`` exception);
* non-2xx HTTP status -> ``NotificationError``;
* HTTP 200 with a Telegram API envelope ``{"ok": false}`` -> ``NotificationError``
  too, not just non-2xx status (Telegram's API reports some failures via the
  JSON body even on a 200 response);
* success (2xx + ``{"ok": true}``) -> returns ``None`` and never raises.
"""

from __future__ import annotations

import httpx
import pytest

from notification.telegram import (
    NotificationError,
    TelegramConfig,
    send_telegram_message,
)

CONFIG = TelegramConfig(bot_token="123:abc", chat_id="42")


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text or str(json_body)

    def json(self):
        if self._json_body is None:
            raise ValueError("no JSON body")
        return self._json_body


def test_send_wraps_transport_error(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(NotificationError):
        send_telegram_message("hello", CONFIG)


def test_send_wraps_timeout(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(NotificationError):
        send_telegram_message("hello", CONFIG)


def test_send_raises_on_non_2xx_status(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return _FakeResponse(500, {"ok": False, "description": "server error"})

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(NotificationError):
        send_telegram_message("hello", CONFIG)


def test_send_raises_on_http_200_with_ok_false(monkeypatch) -> None:
    # This is the case that a naive "status code only" check would miss: the
    # Telegram API can answer 200 OK with a JSON envelope reporting failure
    # (e.g. bad chat_id, bot blocked by the user).
    def fake_post(*args, **kwargs):
        return _FakeResponse(
            200, {"ok": False, "description": "Forbidden: bot was blocked by the user"}
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(NotificationError):
        send_telegram_message("hello", CONFIG)


def test_send_succeeds_on_http_200_with_ok_true(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return _FakeResponse(200, {"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(httpx, "post", fake_post)

    assert send_telegram_message("hello", CONFIG) is None


def test_send_uses_configured_token_and_chat_id(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse(200, {"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)

    send_telegram_message("hi there", CONFIG, parse_mode="HTML")

    assert CONFIG.bot_token in captured["url"]
    assert captured["json"]["chat_id"] == CONFIG.chat_id
    assert captured["json"]["text"] == "hi there"
    assert captured["json"]["parse_mode"] == "HTML"
