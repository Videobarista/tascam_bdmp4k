"""Fixtures for the Tascam BD-MP4K tests."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tascam_bdmp4k.const import DEFAULT_PORT, DOMAIN
from custom_components.tascam_bdmp4k.protocol import TascamConnectionError, TascamNackError
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT

# Documentation address (RFC 5737) and a made-up MAC address only.
HOST = "192.0.2.20"
MAC = "00:11:22:33:44:55"

ENTRY_DATA: dict[str, Any] = {CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT}

# Answers of a player that is playing chapter 3 of title 1, 1:12:30 in, 45:00 to go.
PLAYING_ANSWERS: dict[str, str] = {
    "!7?SST": "!7SSTPL",
    "!7?MST": "!7MSTCI",
    "!7?SET": "!7SET0011230",
    "!7?SRT": "!7SRT0004500",
    "!7?STC": "!7TNM0003",
    "!7?SGN": "!7GNM0001",
}


class FakePlayer:
    """Stand-in for a BD-MP4K behind a mocked TascamClient."""

    def __init__(self) -> None:
        """Start as a reachable player that is playing a disc."""
        self.answers: dict[str, str] = dict(PLAYING_ANSWERS)
        self.reachable = True
        self.failing: set[str] = set()
        self.sent: list[str] = []
        self.notify: Callable[[str], None] | None = None
        self.client = MagicMock()
        self.client.async_connect = AsyncMock()
        self.client.async_disconnect = AsyncMock()
        self.client.async_send = AsyncMock(side_effect=self._send)
        self.client.set_notification_callback = MagicMock(side_effect=self._set_callback)

    def _set_callback(self, callback: Callable[[str], None] | None) -> None:
        self.notify = callback

    async def _send(self, command: str, *, retry: bool = True) -> str | None:
        if not self.reachable or command in self.failing:
            raise TascamConnectionError(f"No reply to {command}")
        self.sent.append(command)
        if not command.startswith("!7?"):
            return None
        if (answer := self.answers.get(command)) is None:
            raise TascamNackError("Device replied NACK")
        return answer


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
def player() -> Generator[FakePlayer]:
    """Patch the protocol client everywhere it is created; return the fake player."""
    fake = FakePlayer()
    with (
        patch("custom_components.tascam_bdmp4k.TascamClient", return_value=fake.client),
        patch(
            "custom_components.tascam_bdmp4k.config_flow.TascamClient",
            return_value=fake.client,
        ),
    ):
        yield fake


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Skip setting up the entry, for config flow tests."""
    with patch(
        "custom_components.tascam_bdmp4k.async_setup_entry", return_value=True
    ) as setup_entry:
        yield setup_entry


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for a player without a MAC address."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Tascam BD-MP4K",
        unique_id=f"{HOST}:{DEFAULT_PORT}",
        data=dict(ENTRY_DATA),
    )


@pytest.fixture
def mock_config_entry_mac() -> MockConfigEntry:
    """Return a config entry for a player with a MAC address for Wake-on-LAN."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Tascam BD-MP4K",
        unique_id=f"{HOST}:{DEFAULT_PORT}",
        data={**ENTRY_DATA, CONF_MAC: MAC},
    )
