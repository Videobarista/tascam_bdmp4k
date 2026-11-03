"""Config flow for the Tascam BD-MP4K integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT

from .const import DEFAULT_NAME, DEFAULT_PORT, DOMAIN
from .protocol import TascamClient, TascamError
from .wol import normalize_mac

_LOGGER = logging.getLogger(__name__)

MAX_HOST_LENGTH = 253  # longest valid DNS name

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_MAC): str,
    }
)


def valid_host(host: str) -> bool:
    """Return True for something that can be an IP address or host name.

    Spaces, slashes and the like point at a URL or a typo, not at the player.
    IPv6 addresses (with colons) are allowed.
    """
    if not host or len(host) > MAX_HOST_LENGTH:
        return False
    return all(char.isascii() and (char.isalnum() or char in ".-_:") for char in host)


def valid_port(port: int) -> bool:
    """Return True for a usable TCP port."""
    return 1 <= port <= 65535


class TascamConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tascam BD-MP4K."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle a manual setup: address, port and optional MAC address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            data: dict[str, Any] = {CONF_HOST: host, CONF_PORT: port}

            if not valid_host(host):
                errors[CONF_HOST] = "invalid_host"
            if not valid_port(port):
                errors[CONF_PORT] = "invalid_port"
            if raw_mac := user_input.get(CONF_MAC, "").strip():
                if (mac := normalize_mac(raw_mac)) is None:
                    errors[CONF_MAC] = "invalid_mac"
                else:
                    data[CONF_MAC] = mac

            if not errors:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()

                client = TascamClient(host, port)
                try:
                    await client.async_connect()
                except TascamError as err:
                    _LOGGER.debug("Cannot connect to %s:%s: %s", host, port, err)
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error while connecting to %s:%s", host, port)
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(title=DEFAULT_NAME, data=data)
                finally:
                    await client.async_disconnect()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, user_input),
            errors=errors,
        )
