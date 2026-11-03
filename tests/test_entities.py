"""Tests for the Tascam BD-MP4K media player and button entities."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.media_player import (
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_MEDIA_NEXT_TRACK,
    SERVICE_MEDIA_PAUSE,
    SERVICE_MEDIA_PLAY,
    SERVICE_MEDIA_PREVIOUS_TRACK,
    SERVICE_MEDIA_STOP,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import HomeAssistant

from .conftest import MAC, FakePlayer

MEDIA_PLAYER = "media_player.tascam_bd_mp4k"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("service", "command"),
    [
        (SERVICE_MEDIA_PLAY, "!7PLY"),
        (SERVICE_MEDIA_PAUSE, "!7PAS"),
        (SERVICE_MEDIA_STOP, "!7STP"),
        (SERVICE_MEDIA_NEXT_TRACK, "!7SKPNX"),
        (SERVICE_MEDIA_PREVIOUS_TRACK, "!7SKPPV"),
        (SERVICE_TURN_OFF, "!7PWR00"),
    ],
)
async def test_media_player_commands(
    hass: HomeAssistant,
    player: FakePlayer,
    mock_config_entry: MockConfigEntry,
    service: str,
    command: str,
) -> None:
    """Media player actions send the matching protocol command."""
    await _setup(hass, mock_config_entry)

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN, service, {ATTR_ENTITY_ID: MEDIA_PLAYER}, blocking=True
    )
    assert command in player.sent

    await _unload(hass, mock_config_entry)


async def test_turn_on_with_wake_on_lan(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry_mac: MockConfigEntry
) -> None:
    """With a MAC address the player can be switched on with a magic packet."""
    player.reachable = False
    await _setup(hass, mock_config_entry_mac)

    state = hass.states.get(MEDIA_PLAYER)
    assert state.attributes[ATTR_SUPPORTED_FEATURES] & MediaPlayerEntityFeature.TURN_ON

    with patch(
        "custom_components.tascam_bdmp4k.media_player.async_send_magic_packet",
        new=AsyncMock(),
    ) as send_magic_packet:
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: MEDIA_PLAYER}, blocking=True
        )
    send_magic_packet.assert_awaited_once_with(hass, MAC)

    await _unload(hass, mock_config_entry_mac)


async def test_turn_on_not_offered_without_mac(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """Without a MAC address there is no way to switch the player on."""
    await _setup(hass, mock_config_entry)

    state = hass.states.get(MEDIA_PLAYER)
    assert not state.attributes[ATTR_SUPPORTED_FEATURES] & MediaPlayerEntityFeature.TURN_ON

    await _unload(hass, mock_config_entry)


@pytest.mark.parametrize(
    ("entity_id", "command"),
    [
        ("button.tascam_bd_mp4k_tray_open", "!7OPCOP"),
        ("button.tascam_bd_mp4k_tray_close", "!7OPCCL"),
        ("button.tascam_bd_mp4k_menu_home", "!7HOM"),
        ("button.tascam_bd_mp4k_mute_on", "!7MUT00"),
        ("button.tascam_bd_mp4k_power_off_standby", "!7PWR00"),
    ],
)
async def test_buttons(
    hass: HomeAssistant,
    player: FakePlayer,
    mock_config_entry: MockConfigEntry,
    entity_id: str,
    command: str,
) -> None:
    """Pressing a button sends its protocol command."""
    await _setup(hass, mock_config_entry)

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert command in player.sent

    await _unload(hass, mock_config_entry)


async def test_failed_command_is_logged(
    hass: HomeAssistant,
    player: FakePlayer,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A command that fails while the player is on is logged as a warning."""
    await _setup(hass, mock_config_entry)
    player.failing.update({"!7PAS", "!7OPCOP"})

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN, SERVICE_MEDIA_PAUSE, {ATTR_ENTITY_ID: MEDIA_PLAYER}, blocking=True
    )
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: "button.tascam_bd_mp4k_tray_open"},
        blocking=True,
    )
    assert "Command !7PAS failed" in caplog.text
    assert "Command !7OPCOP failed" in caplog.text

    await _unload(hass, mock_config_entry)


async def test_command_while_off_is_not_a_warning(
    hass: HomeAssistant,
    player: FakePlayer,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Switching off a player that is already off does not raise a warning."""
    caplog.set_level(logging.DEBUG, logger="custom_components.tascam_bdmp4k")
    player.reachable = False
    await _setup(hass, mock_config_entry)

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: MEDIA_PLAYER}, blocking=True
    )
    assert "Command !7PWR00 failed" not in caplog.text
    assert "Command !7PWR00 skipped" in caplog.text

    await _unload(hass, mock_config_entry)
