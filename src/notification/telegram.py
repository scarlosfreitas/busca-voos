"""Telegram notification layer: message composition + delivery.

This module is the only integration point with the Telegram Bot API. It follows
``docs/domain/regras_negocio.md`` — Regra de Notificação (Telegram):

* A non-empty list of flights (already filtered by eligibility + deduplication in
  ``domain/``) becomes **one** human-readable alert message per run, carrying
  carrier (Cia), flight date (Data), route (Trecho), departure time(s), price(s)
  and the search date (data da pesquisa).
* An empty list means **no message is sent** — but that decision belongs to the
  ``orchestration`` layer, which simply does not call the send function. The
  composition functions here refuse to build an "empty" alert (they raise) so a
  bug upstream surfaces loudly instead of sending a blank message.
* An extraction failure produces a **separate, independent** error notification
  (``format_failure_message`` + send), never merged with the flight alert.

Design boundaries (see the plan in ``.claude/plans/2026-07-24-dev-notification.md``):

* **Composition is pure and network-free** (``format_*`` functions) so it is unit
  tested without any credentials or HTTP.
* **Delivery is isolated** in :func:`send_telegram_message`, covered only by a
  skippable integration test (same convention as ``test/persistence`` /
  ``test/extraction`` — no real credentials ⇒ skip, never fail).
* Token and chat id come exclusively from environment variables
  (``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``); nothing is hardcoded
  (``docs/standards/architecture.md`` §5).
* A network/API failure while sending becomes a typed :class:`NotificationError`,
  never swallowed silently.

This module is a pure ``notification`` concern: it does not decide eligibility or
deduplication (``domain/``) and does not persist anything (``persistence/``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx

from domain.models import Flight, Route

# --- Constants (contract) ---------------------------------------------------

#: Base URL of the Telegram Bot API. The per-bot endpoint is
#: ``{TELEGRAM_API_BASE}/bot{token}/sendMessage``. Kept as a constant so tests can
#: assert the send function targets the official API and never a hardcoded host.
TELEGRAM_API_BASE = "https://api.telegram.org"

#: Default HTTP timeout (seconds) for a single ``sendMessage`` call. Telegram is a
#: fast API; unlike the scraping layer this does not need the 5-minute budget.
DEFAULT_TIMEOUT_SECONDS = 15.0

#: Human-readable Brazilian-Portuguese label for each known extraction failure
#: type, used by :func:`format_failure_message`. Mapping content (the exact
#: wording) is part of the contract dev-runner implements; the presence of a
#: sensible label per ``ExtractionError`` subclass is what the tests pin.
FAILURE_LABEL_FALLBACK = "Falha inesperada"

#: Human-readable label per known ``extraction.errors.ExtractionError`` subclass,
#: keyed by *class name* (not by import) to keep this module decoupled from
#: ``extraction`` (dependency direction, see plan). Any exception whose type name
#: is not listed here falls back to :data:`FAILURE_LABEL_FALLBACK`.
_FAILURE_LABELS_BY_TYPE_NAME: dict[str, str] = {
    "BlockedError": "Bloqueio/CAPTCHA detectado",
    "ExtractionTimeoutError": "Tempo limite excedido",
    "MalformedPayloadError": "Dados retornados inválidos",
}


# --- Exceptions -------------------------------------------------------------


class NotificationError(Exception):
    """Raised when delivering a message to Telegram fails.

    Covers transport failures (connection error, timeout) and non-success API
    responses (non-2xx HTTP status, ``ok: false`` envelope). The point of this
    typed exception is that a delivery failure is **never swallowed**: the
    ``orchestration`` layer can catch it, log it and decide what to do, but the
    error is always visible (``docs/standards/architecture.md`` §6).
    """


# --- Configuration ----------------------------------------------------------


@dataclass(frozen=True)
class TelegramConfig:
    """Credentials needed to talk to the Telegram Bot API.

    Both fields are secrets and must come from the environment, never from source
    (``docs/standards/architecture.md`` §5). The real bot/token is created
    manually by the operator via @BotFather — outside the scope of this code.
    """

    bot_token: str
    chat_id: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> TelegramConfig:
        """Build the config from environment variables.

        Reads ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` from ``env`` (default
        ``os.environ``). If either is missing or empty, raises ``RuntimeError``
        **naming the missing variable** (fail-fast) so a misconfigured deploy is
        obvious instead of silently not notifying.

        Implementation is left to dev-runner.
        """
        source = env if env is not None else os.environ

        bot_token = source.get("TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

        chat_id = source.get("TELEGRAM_CHAT_ID", "")
        if not chat_id:
            raise RuntimeError("TELEGRAM_CHAT_ID is not set")

        return cls(bot_token=bot_token, chat_id=chat_id)


# --- Pure message composition (network-free, unit tested) -------------------


def format_price(price: Decimal, currency: str) -> str:
    """Render a price as a human-readable Brazilian-Portuguese string.

    Contract:

    * ``currency == "BRL"`` → Brazilian format with the ``R$`` symbol, ``.`` as
      thousands separator and ``,`` as decimal separator, always two decimals —
      e.g. ``Decimal("1234.56")`` → ``"R$ 1.234,56"`` and ``Decimal("890.00")``
      → ``"R$ 890,00"``.
    * any other currency → a generic ``"{currency} {amount}"`` rendering with two
      decimals (kept simple; the MVP only captures BRL).

    ``Decimal`` in, ``str`` out — never goes through ``float`` (money precision).

    Implementation is left to dev-runner.
    """
    amount = f"{price.quantize(Decimal('0.01')):,.2f}"
    if currency == "BRL":
        # amount is US-style ("1,234.56"); swap separators to pt-BR ("1.234,56").
        brl_amount = amount.replace(",", "\0").replace(".", ",").replace("\0", ".")
        return f"R$ {brl_amount}"
    return f"{currency} {amount}"


def format_flight_alert_message(flights: Sequence[Flight], search_date: date) -> str:
    """Compose the single Telegram alert message for a run.

    ``flights`` are the flights that already passed eligibility + deduplication in
    ``domain/`` — this function does not re-filter them, it only renders them.

    Contract (``docs/domain/regras_negocio.md`` — Regra de Notificação; PRD §8):

    * Produces **one** message string covering **all** ``flights``, in the given
      order (order is preserved — the caller sorts/filters, we render).
    * Each flight contributes at least: carrier (Cia), route/trecho
      (origin → destination), flight date (Data — the route's ``departure_date``),
      departure time (``HH:MM``) and price (via :func:`format_price`).
    * The message states the **search date** (data da pesquisa) once, rendered in
      Brazilian ``dd/mm/aaaa`` format.
    * Dates are rendered ``dd/mm/aaaa`` and times ``HH:MM`` for a Brazilian reader.

    Empty input is a programming error here: deciding *not* to notify on an empty
    list is the ``orchestration`` layer's job (it must not call this function).
    Therefore an empty ``flights`` raises ``ValueError`` rather than returning a
    blank message.

    Implementation is left to dev-runner.
    """
    if not flights:
        raise ValueError("cannot compose an alert message for an empty flight list")

    lines = [
        f"Alerta de voos — pesquisa em {search_date.strftime('%d/%m/%Y')}",
        "",
    ]
    for flight in flights:
        route = flight.route
        lines.append(
            f"{flight.carrier} {route.origin} → {route.destination} "
            f"em {route.departure_date.strftime('%d/%m/%Y')} às "
            f"{flight.departure_time.strftime('%H:%M')} — "
            f"{format_price(flight.price, flight.currency)}"
        )

    return "\n".join(lines)


def format_failure_message(
    error: Exception,
    *,
    search_date: date,
    route: Route | None = None,
) -> str:
    """Compose the standalone failure notification for a run.

    Sent when the run could not complete extraction (block/CAPTCHA, timeout,
    malformed payload, unexpected exception) — a **separate, independent** message
    from any flight alert (``docs/domain/regras_negocio.md`` — Notificação de
    falha; ``docs/standards/architecture.md`` §6).

    Contract:

    * Returns a readable Brazilian-Portuguese message flagging that the run failed.
    * Represents the failure legibly: a human label derived from the exception
      **type** (the ``extraction.errors.ExtractionError`` subclasses — block,
      timeout, malformed — each get a distinct label; anything else falls back to
      :data:`FAILURE_LABEL_FALLBACK`) plus the underlying error message
      (``str(error)``) so the operator can diagnose it.
    * States the search date (``dd/mm/aaaa``) and, when ``route`` is given, the
      affected trecho (origin → destination) and flight date.

    This function must not import ``extraction`` (dependency direction); it keys
    off the exception's type name / class, so it degrades gracefully for any
    ``Exception``.

    Implementation is left to dev-runner.
    """
    label = _FAILURE_LABELS_BY_TYPE_NAME.get(
        type(error).__name__, FAILURE_LABEL_FALLBACK
    )

    lines = [
        f"Falha na execução — pesquisa em {search_date.strftime('%d/%m/%Y')}",
        f"{label}: {error}",
    ]
    if route is not None:
        lines.append(
            f"Trecho afetado: {route.origin} → {route.destination} "
            f"em {route.departure_date.strftime('%d/%m/%Y')}"
        )

    return "\n".join(lines)


# --- Delivery (I/O, integration tested only) --------------------------------


def send_telegram_message(
    text: str,
    config: TelegramConfig,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    parse_mode: str | None = None,
) -> None:
    """Send an already-composed message to Telegram, or raise on failure.

    Performs a single HTTP ``POST`` to
    ``{TELEGRAM_API_BASE}/bot{config.bot_token}/sendMessage`` with ``chat_id`` and
    ``text`` (and ``parse_mode`` when provided), using ``httpx`` synchronously —
    a one-shot fire-and-forget send fits the daily batch job better than the
    async ``python-telegram-bot`` application framework (decision recorded in the
    plan).

    Separation of concerns: this function takes the **already composed** ``text``
    (from the ``format_*`` functions) so composition stays unit-testable without
    network and delivery can be mocked/skipped in tests.

    Failure handling (``docs/standards/architecture.md`` §6):

    * a transport error (connection failure, timeout) → :class:`NotificationError`
      wrapping the cause;
    * a non-2xx response or an ``{"ok": false}`` envelope → :class:`NotificationError`
      carrying the status/description.

    Never swallows a failure silently and never returns partial success. Returns
    ``None`` on success.

    Implementation is left to dev-runner.
    """
    url = f"{TELEGRAM_API_BASE}/bot{config.bot_token}/sendMessage"
    payload: dict[str, str] = {"chat_id": config.chat_id, "text": text}
    if parse_mode is not None:
        payload["parse_mode"] = parse_mode

    try:
        response = httpx.post(url, json=payload, timeout=timeout_seconds)
    except httpx.HTTPError as exc:
        raise NotificationError(f"failed to reach Telegram API: {exc}") from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise NotificationError(
            f"Telegram API returned status {response.status_code}: {response.text}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise NotificationError(
            f"Telegram API returned a non-JSON response: {response.text}"
        ) from exc

    if not body.get("ok", False):
        raise NotificationError(f"Telegram API responded with ok=false: {body}")
