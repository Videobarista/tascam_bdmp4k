"""Tests for setting up, polling and unloading the Tascam BD-MP4K integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, call, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tascam_bdmp4k.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .conftest import FakePlayer

MEDIA_PLAYER = "media_player.tascam_bd_mp4k"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_and_unload(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """The entry loads, creates the device and entities, and unloads cleanly."""
    await _setup(hass, mock_config_entry)

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, mock_config_entry.entry_id), mock_config_entry.entry_id
    )
    assert device is not None
    assert device.name == "Tascam BD-MP4K"
    assert device.model == "BD-MP4K"

    state = hass.states.get(MEDIA_PLAYER)
    assert state.state == "playing"
    assert state.attributes["media_position"] == 4350
    assert state.attributes["media_duration"] == 7050
    assert state.attributes["media_position_updated_at"] is not None

    assert hass.states.get("sensor.tascam_bd_mp4k_disc_status").state == "disc_present"
    assert hass.states.get("sensor.tascam_bd_mp4k_playback_status").state == "playing"
    assert hass.states.get("sensor.tascam_bd_mp4k_time_elapsed").state == "4350"
    assert hass.states.get("sensor.tascam_bd_mp4k_time_remaining").state == "2700"
    assert hass.states.get("sensor.tascam_bd_mp4k_current_chapter").state == "3"
    assert hass.states.get("sensor.tascam_bd_mp4k_current_title").state == "1"
    assert hass.states.get("button.tascam_bd_mp4k_tray_open") is not None

    await _unload(hass, mock_config_entry)
    player.client.async_disconnect.assert_awaited()


async def test_setup_while_player_is_off(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """An unreachable player still loads, as "off" instead of a failed setup."""
    player.reachable = False
    await _setup(hass, mock_config_entry)

    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF
    assert hass.states.get("sensor.tascam_bd_mp4k_disc_status").state == STATE_UNAVAILABLE
    assert hass.states.get("button.tascam_bd_mp4k_tray_open").state == STATE_UNAVAILABLE
    # The first poll reconnects and retries once before giving up.
    assert player.client.async_disconnect.await_count == 1

    await _unload(hass, mock_config_entry)


async def test_poll_recovers_after_one_failed_request(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """A dropped connection on the first request is retried before going offline."""
    attempts = 0
    send = player.client.async_send.side_effect

    async def fail_first_status_request(command: str, **kwargs: bool) -> str | None:
        nonlocal attempts
        if command == "!7?SST" and attempts == 0:
            attempts += 1
            player.reachable = False
            try:
                return await send(command)
            finally:
                player.reachable = True
        return await send(command)

    player.client.async_send.side_effect = fail_first_status_request
    await _setup(hass, mock_config_entry)

    assert hass.states.get(MEDIA_PLAYER).state == "playing"
    await _unload(hass, mock_config_entry)


async def test_poll_while_stopped(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """When stopped, times and chapters are not requested and show as unknown."""
    player.answers["!7?SST"] = "!7SSTST"
    await _setup(hass, mock_config_entry)

    assert hass.states.get(MEDIA_PLAYER).state == "idle"
    assert hass.states.get("sensor.tascam_bd_mp4k_playback_status").state == "stopped"
    assert hass.states.get("sensor.tascam_bd_mp4k_time_elapsed").state == STATE_UNKNOWN
    assert "!7?SET" not in player.sent

    await _unload(hass, mock_config_entry)


async def test_poll_with_unsupported_requests(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """Requests the player answers with NACK or unknown codes show as unknown."""
    player.answers["!7?SST"] = "!7SSTPP"
    player.answers["!7?MST"] = "!7MSTZZ"
    player.answers["!7?STC"] = "!7TNMUNKN"
    del player.answers["!7?SRT"]
    await _setup(hass, mock_config_entry)

    state = hass.states.get(MEDIA_PLAYER)
    assert state.state == "paused"
    assert state.attributes["media_position"] == 4350
    assert "media_duration" not in state.attributes
    assert hass.states.get("sensor.tascam_bd_mp4k_disc_status").state == STATE_UNKNOWN
    assert hass.states.get("sensor.tascam_bd_mp4k_time_remaining").state == STATE_UNKNOWN
    assert hass.states.get("sensor.tascam_bd_mp4k_current_chapter").state == STATE_UNKNOWN

    await _unload(hass, mock_config_entry)


async def test_poll_with_unknown_playback_status(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """An unknown transport code does not break the enum sensor."""
    player.answers["!7?SST"] = "!7SSTZZ"
    await _setup(hass, mock_config_entry)

    assert hass.states.get(MEDIA_PLAYER).state == "idle"
    assert hass.states.get("sensor.tascam_bd_mp4k_playback_status").state == STATE_UNKNOWN

    await _unload(hass, mock_config_entry)


async def test_connection_lost_during_poll(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """Losing the connection halfway keeps what was already read."""
    player.failing.add("!7?MST")
    await _setup(hass, mock_config_entry)

    assert hass.states.get(MEDIA_PLAYER).state == "playing"
    assert hass.states.get("sensor.tascam_bd_mp4k_disc_status").state == STATE_UNKNOWN
    assert hass.states.get("sensor.tascam_bd_mp4k_time_elapsed").state == STATE_UNKNOWN

    await _unload(hass, mock_config_entry)


async def test_push_notifications(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """Status notifications pushed by the player update the entities right away."""
    await _setup(hass, mock_config_entry)
    assert player.notify is not None

    player.answers["!7?SST"] = "!7SSTPP"
    player.notify("!7SSTPP")
    assert hass.states.get(MEDIA_PLAYER).state == "paused"
    await hass.async_block_till_done()
    assert hass.states.get("sensor.tascam_bd_mp4k_playback_status").state == "paused"

    player.answers["!7?MST"] = "!7MSTTO"
    player.notify("!7MSTTO")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.tascam_bd_mp4k_disc_status").state == "tray_open"

    player.notify("!7MSTZZ")
    player.notify("!7SSTZZ")
    player.notify("!7TNM0004")
    await hass.async_block_till_done()

    await _unload(hass, mock_config_entry)


async def test_offline_player_is_polled_once(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """A player in standby gets one connection attempt per poll, without retries."""
    player.reachable = False
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    player.client.async_send.reset_mock()
    player.client.async_disconnect.reset_mock()

    await coordinator.async_refresh()
    assert player.client.async_send.await_args_list == [call("!7?SST", retry=False)]
    player.client.async_disconnect.assert_not_awaited()
    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF

    # Once the player is back, the next poll picks it up straight away.
    player.reachable = True
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(MEDIA_PLAYER).state == "playing"

    await _unload(hass, mock_config_entry)


async def test_unchanged_notifications_are_ignored(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """Notifications that repeat the current state cause no state writes."""
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    assert player.notify is not None

    with patch.object(
        coordinator, "async_set_updated_data", wraps=coordinator.async_set_updated_data
    ) as set_data:
        player.notify("!7SSTPL")
        player.notify("!7MSTCI")
        set_data.assert_not_called()

        player.answers["!7?SST"] = "!7SSTPP"
        player.notify("!7SSTPP")
        set_data.assert_called_once()
    await hass.async_block_till_done()

    await _unload(hass, mock_config_entry)


async def test_unanswered_status_keeps_last_known(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """A status request the player does not answer keeps the last known values."""
    await _setup(hass, mock_config_entry)
    del player.answers["!7?SST"]
    del player.answers["!7?MST"]

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(MEDIA_PLAYER).state == "playing"
    assert hass.states.get("sensor.tascam_bd_mp4k_disc_status").state == "disc_present"
    assert hass.states.get("sensor.tascam_bd_mp4k_time_elapsed").state == "4350"

    await _unload(hass, mock_config_entry)


async def test_firmware_chapter_and_title_format(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """Chapter and title are read in the form the player actually sends."""
    player.answers["!7?STC"] = "!7TN0004"
    player.answers["!7?SGN"] = "!7GNMX0002"
    await _setup(hass, mock_config_entry)

    assert hass.states.get("sensor.tascam_bd_mp4k_current_chapter").state == "4"
    assert hass.states.get("sensor.tascam_bd_mp4k_current_title").state == "2"

    await _unload(hass, mock_config_entry)


async def test_push_chapter_title_and_disc(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """Chapter, title and disc notifications update the sensors without a poll."""
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    assert player.notify is not None

    with patch.object(coordinator, "async_request_refresh", new=AsyncMock()) as refresh:
        player.notify("!7TN0005")
        player.notify("!7GNMXUNKN")
        player.notify("!7MSTLD")
        # Total chapter and title counts are not shown and need no refresh.
        player.notify("!7TT0002")
        player.notify("!7TGNX0012")
        await hass.async_block_till_done()
        refresh.assert_not_called()

    assert hass.states.get("sensor.tascam_bd_mp4k_current_chapter").state == "5"
    assert hass.states.get("sensor.tascam_bd_mp4k_current_title").state == STATE_UNKNOWN
    assert hass.states.get("sensor.tascam_bd_mp4k_disc_status").state == "loading"

    await _unload(hass, mock_config_entry)
