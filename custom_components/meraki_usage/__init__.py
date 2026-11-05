"""Meraki Data Usage: today's internet usage by line, device and app."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MerakiApi
from .const import (
    CONF_API_KEY, CONF_NETWORK_ID, CONF_ORG_ID, CONF_SCAN_MINUTES, CONF_TOP_DEVICES,
    DEFAULT_SCAN_MINUTES, DEFAULT_TOP_DEVICES,
)
from .coordinator import MerakiUsageCoordinator

PLATFORMS = [Platform.SENSOR]


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
