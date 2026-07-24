"""Unit tests for the pure browser-config helpers (no browser).

Pin the env-parsing contract of ``BrowserConfig.from_env`` and the bounded
randomness of ``pick_delay_seconds``. The ``from_env``/``pick_delay_seconds``
tests fail with ``NotImplementedError`` until dev-runner implements the bodies;
the constant-sanity tests document the fixed contract and pass now.
"""

from __future__ import annotations

from random import Random

from extraction.browser import (
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    DEFAULT_USER_AGENT,
    BrowserConfig,
    ProxyConfig,
    pick_delay_seconds,
)

# PRD §6 / architecture.md §6 floor: 5 minutes.
FIVE_MINUTES_MS = 5 * 60 * 1000


class TestContractConstants:
    def test_default_timeout_is_at_least_five_minutes(self) -> None:
        assert DEFAULT_NAVIGATION_TIMEOUT_MS >= FIVE_MINUTES_MS

    def test_default_user_agent_is_organic(self) -> None:
        assert DEFAULT_USER_AGENT
        assert "Headless" not in DEFAULT_USER_AGENT


class TestFromEnv:
    def test_no_proxy_env_means_no_proxy(self) -> None:
        config = BrowserConfig.from_env({})
        assert config.proxy is None

    def test_proxy_env_populates_proxy_config(self) -> None:
        config = BrowserConfig.from_env(
            {
                "PROXY_SERVER": "http://proxy.example:8080",
                "PROXY_USERNAME": "user",
                "PROXY_PASSWORD": "secret",
            }
        )
        assert config.proxy == ProxyConfig(
            server="http://proxy.example:8080",
            username="user",
            password="secret",
        )

    def test_default_timeout_when_unset(self) -> None:
        config = BrowserConfig.from_env({})
        assert config.navigation_timeout_ms == DEFAULT_NAVIGATION_TIMEOUT_MS

    def test_timeout_overridable_via_env(self) -> None:
        config = BrowserConfig.from_env({"EXTRACTION_NAV_TIMEOUT_MS": "600000"})
        assert config.navigation_timeout_ms == 600000

    def test_default_user_agent_when_unset(self) -> None:
        config = BrowserConfig.from_env({})
        assert config.user_agent == DEFAULT_USER_AGENT

    def test_user_agent_overridable_via_env(self) -> None:
        config = BrowserConfig.from_env({"EXTRACTION_USER_AGENT": "Custom UA/1.0"})
        assert config.user_agent == "Custom UA/1.0"


class TestPickDelaySeconds:
    def test_within_configured_bounds(self) -> None:
        config = BrowserConfig()
        rng = Random(42)
        for _ in range(50):
            delay = pick_delay_seconds(config, rng)
            assert config.min_delay_seconds <= delay <= config.max_delay_seconds
