"""Extraction-domain error hierarchy.

Every failure of the scraping layer (WAF/CAPTCHA block, network/page timeout,
or an unparseable response payload) must surface as one of these typed
exceptions — never as a bare ``Exception`` and never by silently crashing the
process. This is the contract that lets the ``orchestration`` layer catch a
failure and dispatch the Telegram "notificação de falha"
(``docs/standards/architecture.md`` §6; ``docs/domain/regras_negocio.md`` —
Regra de Notificação).

This module lives alongside ``browser.py`` and ``gol.py``. ``architecture.md`` §2
lists only those two files for ``extraction/``; ``errors.py`` is added to keep the
error contract in one importable place (same rationale as ``persistence/tables.py``
in the persistence plan). Documented here so dev-runner does not treat it as drift.
"""

from __future__ import annotations


class ExtractionError(Exception):
    """Base class for every recoverable failure of the extraction layer.

    ``orchestration`` catches this base type to decide that a run failed and a
    failure notification must be sent. Callers should never let a lower-level
    library exception (Playwright ``TimeoutError``, ``json`` decode error, etc.)
    escape ``extraction`` un-wrapped: translate it into one of the subclasses
    below.
    """


class BlockedError(ExtractionError):
    """Raised when the site refused/challenged us instead of returning the API JSON.

    Covers CAPTCHA screens, WAF/anti-bot blocks (Cloudflare/Akamai) and any case
    where the intercepted response is *not* the expected search-availability JSON
    (e.g. an HTML challenge page or an "access denied" JSON envelope). See PRD §8
    (evasão sem CAPTCHA) and ``docs/domain/regras_negocio.md`` — Notificação de
    falha.
    """


class ExtractionTimeoutError(ExtractionError):
    """Raised when navigation or the awaited network response times out.

    Timeouts use the long budget mandated by PRD §6 / ``architecture.md`` §6
    (5+ minutes) to tolerate slow pages without a false-positive failure. This is
    an *infrastructure* failure (distinct tag/level from ``MalformedPayloadError``,
    per ``architecture.md`` §6).
    """


class MalformedPayloadError(ExtractionError):
    """Raised when the response has the expected shape but a record is unparseable.

    Distinct from :class:`BlockedError`: here we *did* receive the API container,
    but an individual flight record is missing a mandatory field or carries a
    value that cannot be typed (non-numeric price, unparseable datetime). This is
    a *business/data* failure (distinct tag/level from timeouts, per
    ``architecture.md`` §6).
    """
