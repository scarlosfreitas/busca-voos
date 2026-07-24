"""Playwright browser setup with stealth, organic UA, delays and long timeouts.

This module owns the *I/O* of driving a headless Chromium (launch + stealth +
navigation config) plus the *pure* configuration parsing that decides how the
browser is set up. The split is deliberate and mirrors the persistence layer:

* Pure, unit-testable (no browser): :meth:`BrowserConfig.from_env` and
  :func:`pick_delay_seconds`. These have their contract pinned by the unit tests
  in ``test/extraction/test_browser_config.py`` and fail with
  ``NotImplementedError`` until dev-runner implements them.
* I/O, integration-only (skipped when no browser / opt-out): the async
  :func:`stealth_page_session` and :func:`human_delay`.

References: PRD §3/§4 (Playwright headless + ``playwright-stealth``, user-agents
orgânicos, delays aleatórios, proxy residencial opcional via ``.env``), PRD §6 /
``architecture.md`` §6 (timeouts de 5+ minutos), ``architecture.md`` §5 (segredos
e proxy via env, nunca hardcoded).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from random import Random
from typing import TYPE_CHECKING, Any

from .errors import ExtractionError

# Import Playwright only for typing — never at runtime in the pure/config paths.
if TYPE_CHECKING:  # pragma: no cover
    from playwright.async_api import Page

# A realistic desktop Chrome user-agent. Must never advertise "Headless"
# (PRD §4: mascarar variáveis de automação). dev-runner may rotate/refresh this,
# but the contract (organic, non-Headless, non-empty) is fixed by the tests.
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Long timeout budget per PRD §6 / architecture.md §6 (5+ minutes = 300_000 ms).
DEFAULT_NAVIGATION_TIMEOUT_MS: int = 300_000

# Bounds (seconds) for the simulated human delay between interactions (PRD §4).
DEFAULT_MIN_DELAY_SECONDS: float = 1.5
DEFAULT_MAX_DELAY_SECONDS: float = 6.0

# Environment variable names (architecture.md §5 — no hardcoded secrets/config).
ENV_PROXY_SERVER = "PROXY_SERVER"
ENV_PROXY_USERNAME = "PROXY_USERNAME"
ENV_PROXY_PASSWORD = "PROXY_PASSWORD"
ENV_USER_AGENT = "EXTRACTION_USER_AGENT"
ENV_NAV_TIMEOUT_MS = "EXTRACTION_NAV_TIMEOUT_MS"
ENV_HEADLESS = "EXTRACTION_HEADLESS"
ENV_LOCALE = "EXTRACTION_LOCALE"


@dataclass(frozen=True)
class ProxyConfig:
    """Residential-proxy credentials, as consumed by Playwright's ``proxy=`` arg.

    Optional in the MVP: no provider is contracted yet, so the pipeline runs
    without a proxy until one is configured (PRD §4/§7). ``username``/``password``
    are ``None`` for an unauthenticated proxy.
    """

    server: str
    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class BrowserConfig:
    """Everything needed to launch a stealthed Chromium for one extraction run.

    Defaults encode the MVP contract: headless, organic UA, pt-BR locale, no
    proxy, and a 5-minute navigation timeout. All values are overridable via
    environment (see :meth:`from_env`) so nothing sensitive is hardcoded.
    """

    headless: bool = True
    user_agent: str = DEFAULT_USER_AGENT
    locale: str = "pt-BR"
    proxy: ProxyConfig | None = None
    navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS
    min_delay_seconds: float = DEFAULT_MIN_DELAY_SECONDS
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BrowserConfig:
        """Build a :class:`BrowserConfig` from environment variables.

        Contract (pinned by ``test/extraction/test_browser_config.py``):

        * ``env`` defaults to :data:`os.environ` when ``None``.
        * Proxy is **optional**: if ``PROXY_SERVER`` is unset/empty → ``proxy`` is
          ``None`` (runs without proxy, PRD §4/§7). If set → a :class:`ProxyConfig`
          with the (optional) ``PROXY_USERNAME``/``PROXY_PASSWORD``.
        * ``EXTRACTION_USER_AGENT`` overrides :data:`DEFAULT_USER_AGENT`; unset →
          the default organic UA.
        * ``EXTRACTION_NAV_TIMEOUT_MS`` overrides the timeout; unset → the 5-minute
          default. Never below the PRD floor is a dev-runner responsibility to
          honour, but the *default* must satisfy it.
        * ``EXTRACTION_HEADLESS`` ("0"/"false"/"no" → ``False``) and
          ``EXTRACTION_LOCALE`` override the remaining fields.

        Implementation left to dev-runner.
        """
        source = env if env is not None else _default_env()

        proxy_server = source.get(ENV_PROXY_SERVER, "").strip()
        proxy: ProxyConfig | None = None
        if proxy_server:
            proxy = ProxyConfig(
                server=proxy_server,
                username=source.get(ENV_PROXY_USERNAME) or None,
                password=source.get(ENV_PROXY_PASSWORD) or None,
            )

        user_agent = source.get(ENV_USER_AGENT) or DEFAULT_USER_AGENT

        timeout_raw = source.get(ENV_NAV_TIMEOUT_MS)
        navigation_timeout_ms = (
            int(timeout_raw) if timeout_raw else DEFAULT_NAVIGATION_TIMEOUT_MS
        )

        headless_raw = source.get(ENV_HEADLESS)
        headless = True
        if headless_raw is not None and headless_raw.strip().lower() in {
            "0",
            "false",
            "no",
        }:
            headless = False

        locale = source.get(ENV_LOCALE) or "pt-BR"

        return cls(
            headless=headless,
            user_agent=user_agent,
            locale=locale,
            proxy=proxy,
            navigation_timeout_ms=navigation_timeout_ms,
        )


def pick_delay_seconds(config: BrowserConfig, rng: Random | None = None) -> float:
    """Pick a random human-like delay, in seconds, within the config bounds.

    Pure and unit-testable: returns a value in the closed interval
    ``[config.min_delay_seconds, config.max_delay_seconds]`` using ``rng``
    (defaults to a module-level :class:`random.Random`). Used by
    :func:`human_delay`; separated out so the randomness can be tested
    deterministically with a seeded ``rng``. Implementation left to dev-runner.
    """
    generator = rng if rng is not None else Random()
    return generator.uniform(config.min_delay_seconds, config.max_delay_seconds)


async def human_delay(config: BrowserConfig, rng: Random | None = None) -> None:
    """Sleep for a random human-like delay (PRD §4 — atrasos aleatórios).

    I/O (uses ``asyncio.sleep``); integration-only. Delegates the *duration* to
    :func:`pick_delay_seconds`. Implementation left to dev-runner.
    """
    await asyncio.sleep(pick_delay_seconds(config, rng))


@asynccontextmanager
async def stealth_page_session(config: BrowserConfig) -> AsyncIterator[Page]:
    """Async context manager yielding a stealthed, configured Playwright ``Page``.

    Intended use::

        async with stealth_page_session(config) as page:
            ...  # navigate + intercept

    Contract (I/O; covered only by the skippable integration test):

    * Launch headless Chromium (``config.headless``), applying ``playwright-stealth``
      (mask ``navigator.webdriver`` etc., PRD §4).
    * Apply ``config.user_agent``, ``config.locale`` and ``config.proxy`` (when set).
    * Set default navigation/timeout to ``config.navigation_timeout_ms`` (PRD §6).
    * Guarantee browser/context teardown on exit, even on exception.

    Any Playwright-level failure must be re-raised as an :class:`ExtractionError`
    subclass by the caller layer, never leak raw. Implementation left to dev-runner.

    The unreachable ``yield`` below only marks this as an async generator so the
    ``@asynccontextmanager`` decorator dev-runner will add is well-formed.
    """
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise ExtractionError(f"Playwright/stealth is not available: {exc}") from exc

    launch_kwargs: dict[str, Any] = {"headless": config.headless}
    if config.proxy is not None:
        proxy_kwargs: dict[str, Any] = {"server": config.proxy.server}
        if config.proxy.username is not None:
            proxy_kwargs["username"] = config.proxy.username
        if config.proxy.password is not None:
            proxy_kwargs["password"] = config.proxy.password
        launch_kwargs["proxy"] = proxy_kwargs

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**launch_kwargs)
            try:
                context = await browser.new_context(
                    user_agent=config.user_agent,
                    locale=config.locale,
                )
                context.set_default_navigation_timeout(config.navigation_timeout_ms)
                context.set_default_timeout(config.navigation_timeout_ms)
                try:
                    page = await context.new_page()
                    await Stealth().apply_stealth_async(page)
                    yield page
                finally:
                    await context.close()
            finally:
                await browser.close()
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(
            f"Failed to start stealthed browser session: {exc}"
        ) from exc


def _default_env() -> Mapping[str, str]:
    """Return the process environment (indirection to ease testing)."""
    return os.environ
