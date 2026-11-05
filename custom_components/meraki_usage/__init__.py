"""Meraki Data Usage: today's internet usage by line, device and app."""
from __future__ import annotations

import json
from pathlib import Path

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
    DEFAULT_SCAN_MINUTES, DEFAULT_TOP_DEVICES, DOMAIN,
)
from .coordinator import MerakiUsageCoordinator

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
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = MerakiApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    coordinator = MerakiUsageCoordinator(
        hass, api, entry.data[CONF_ORG_ID], entry.data[CONF_NETWORK_ID],
        entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES),
        entry.options.get(CONF_TOP_DEVICES, DEFAULT_TOP_DEVICES),
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
