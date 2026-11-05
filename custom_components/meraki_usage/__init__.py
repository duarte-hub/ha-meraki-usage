"""Meraki Data Usage: today's internet usage by line, device and app."""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import MerakiApi
from .const import (
    CONF_API_KEY, CONF_NETWORK_ID, CONF_ORG_ID, CONF_SCAN_MINUTES, CONF_TOP_DEVICES,
    CONF_NTOPNG_IFID, CONF_NTOPNG_PASSWORD, CONF_NTOPNG_TOKEN, CONF_NTOPNG_URL, CONF_NTOPNG_USER,
    DEFAULT_SCAN_MINUTES, DEFAULT_TOP_DEVICES, DOMAIN,
)
from .coordinator import MerakiUsageCoordinator
from .ntopng import NtopngApi, NtopngError

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
CARD_URL = "/meraki_usage/meraki-usage-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "meraki-usage-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the Lovelace card from the integration so HACS updates include it."""
    version = await hass.async_add_executor_job(
        lambda: json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]
    )
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    websocket_api.async_register_command(hass, ws_host_flows)
    return True


def _ip(value: str) -> str:
    return str(ipaddress.ip_address(value))


@websocket_api.websocket_command({
    vol.Required("type"): "meraki_usage/host_flows",
    vol.Required("ip"): _ip,
    vol.Optional("limit", default=40): vol.All(int, vol.Range(min=1, max=200)),
})
@websocket_api.async_response
async def ws_host_flows(hass: HomeAssistant, connection, msg) -> None:
    """Return ntopng's active flows for one host."""
    api = next(
        (e.runtime_data.ntopng for e in hass.config_entries.async_loaded_entries(DOMAIN)
         if getattr(e.runtime_data, "ntopng", None)),
        None,
    )
    if api is None:
        connection.send_error(msg["id"], "not_configured", "ntopng isn't configured in Meraki Data Usage options")
        return
    try:
        connection.send_result(msg["id"], await api.host_flows(msg["ip"], msg["limit"]))
    except NtopngError as err:
        connection.send_error(msg["id"], "ntopng_error", str(err))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = MerakiApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    coordinator = MerakiUsageCoordinator(
        hass, api, entry.data[CONF_ORG_ID], entry.data[CONF_NETWORK_ID],
        entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES),
        entry.options.get(CONF_TOP_DEVICES, DEFAULT_TOP_DEVICES),
    )
    o = entry.options
    coordinator.ntopng = (
        NtopngApi(async_get_clientsession(hass), o[CONF_NTOPNG_URL], o.get(CONF_NTOPNG_USER),
                  o.get(CONF_NTOPNG_PASSWORD), o.get(CONF_NTOPNG_TOKEN), o.get(CONF_NTOPNG_IFID, 0))
        if o.get(CONF_NTOPNG_URL) else None
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
