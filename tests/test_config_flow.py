"""Tests for the Tascam BD-MP4K config flow."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tascam_bdmp4k.const import DEFAULT_PORT, DOMAIN
from custom_components.tascam_bdmp4k.protocol import TascamConnectionError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import HOST, MAC, FakePlayer

pytestmark = pytest.mark.usefixtures("mock_setup_entry")


async def test_user_flow(hass: HomeAssistant, player: FakePlayer) -> None:
    """A manual setup tests the connection and creates an entry keyed by address."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f" {HOST} ", CONF_MAC: "00-11-22-33-44-55"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Tascam BD-MP4K"
    assert result["data"] == {CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT, CONF_MAC: MAC}
    assert result["result"].unique_id == f"{HOST}:{DEFAULT_PORT}"
    player.client.async_connect.assert_awaited_once()
    player.client.async_disconnect.assert_awaited_once()


@pytest.mark.parametrize("mac", [None, "", "   "])
async def test_user_flow_without_mac(
    hass: HomeAssistant, player: FakePlayer, mac: str | None
) -> None:
    """Leaving the MAC address out stores no MAC address."""
    user_input = {CONF_HOST: HOST, CONF_PORT: 9031}
    if mac is not None:
        user_input[CONF_MAC] = mac

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: HOST, CONF_PORT: 9031}
    assert result["result"].unique_id == f"{HOST}:9031"


async def test_user_flow_invalid_mac(hass: HomeAssistant, player: FakePlayer) -> None:
    """An invalid MAC address is shown on the form, without a connection attempt."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_MAC: "not-a-mac"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_MAC: "invalid_mac"}
    player.client.async_connect.assert_not_awaited()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_MAC: MAC}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MAC] == MAC


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (TascamConnectionError("refused"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, player: FakePlayer, side_effect: Exception, error: str
) -> None:
    """Connection errors are shown on the form and the flow recovers afterwards."""
    player.client.async_connect.side_effect = side_effect

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    player.client.async_disconnect.assert_awaited_once()

    player.client.async_connect.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant, player: FakePlayer, mock_config_entry: MockConfigEntry
) -> None:
    """The same player cannot be added twice."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    player.client.async_connect.assert_not_awaited()


@pytest.mark.parametrize(
    "host", ["http://192.0.2.20", "192.0.2.20/setup", "my player", "", "   ", "a" * 254]
)
async def test_user_flow_invalid_host(hass: HomeAssistant, player: FakePlayer, host: str) -> None:
    """Anything that is not an address or host name is refused before connecting."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: host})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "invalid_host"}
    player.client.async_connect.assert_not_awaited()

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize("host", ["player.local", "tascam-bd_mp4k", "2001:db8::20"])
async def test_user_flow_host_names(hass: HomeAssistant, player: FakePlayer, host: str) -> None:
    """Host names and IPv6 addresses are accepted."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: host})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == host


@pytest.mark.parametrize("port", [0, -1, 65536, 70000])
async def test_user_flow_invalid_port(hass: HomeAssistant, player: FakePlayer, port: int) -> None:
    """A port outside 1-65535 is refused before connecting."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: port}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PORT: "invalid_port"}
    player.client.async_connect.assert_not_awaited()
