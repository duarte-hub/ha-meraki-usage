"""Config flow for Meraki Data Usage."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import MerakiApi, MerakiApiError, MerakiAuthError
from .ntopng import NtopngApi, NtopngError
from .const import (
    CONF_API_KEY, CONF_NETWORK_ID, CONF_ORG_ID, CONF_SCAN_MINUTES, CONF_TOP_DEVICES,
    CONF_NTOPNG_IFID, CONF_NTOPNG_PASSWORD, CONF_NTOPNG_TOKEN, CONF_NTOPNG_URL, CONF_NTOPNG_USER,
    DEFAULT_SCAN_MINUTES, DEFAULT_TOP_DEVICES, DOMAIN,
)


def find_existing_key(hass: HomeAssistant) -> str | None:
    """Borrow the API key from an existing Meraki integration entry."""
    for domain in ("meraki_ha", "meraki"):
        for entry in hass.config_entries.async_entries(domain):
            for src in (entry.data, entry.options):
                for k, v in src.items():
                    kl = k.lower().replace("_", "")
                    if ("apikey" in kl or kl in ("key", "token")) and isinstance(v, str) and len(v) >= 30:
                        return v
    return None


class MerakiUsageConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._networks: dict[str, tuple[str, str]] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            key = (user_input.get(CONF_API_KEY) or "").strip() or find_existing_key(self.hass)
            if not key:
                errors["base"] = "no_key"
            else:
                api = MerakiApi(async_get_clientsession(self.hass), key)
                try:
                    for org in await api.organizations():
                        try:
                            nets = await api.networks(org["id"])
                        except MerakiApiError:
                            continue
                        for n in nets:
                            if "appliance" in (n.get("productTypes") or []):
                                self._networks[n["id"]] = (
                                    org["id"], f'{org.get("name")} / {n.get("name")}'
                                )
                except MerakiAuthError:
                    errors["base"] = "invalid_auth"
                except Exception:  # noqa: BLE001
                    errors["base"] = "cannot_connect"
                if not errors:
                    if not self._networks:
                        errors["base"] = "no_appliance"
                    else:
                        self._api_key = key
                        if len(self._networks) == 1:
                            return await self._create(next(iter(self._networks)))
                        return await self.async_step_network()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Optional(CONF_API_KEY, default=""): str}),
            errors=errors,
        )

    async def async_step_network(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return await self._create(user_input[CONF_NETWORK_ID])
        return self.async_show_form(
            step_id="network",
            data_schema=vol.Schema({
                vol.Required(CONF_NETWORK_ID): vol.In(
                    {nid: label for nid, (_, label) in self._networks.items()}
                )
            }),
        )

    async def _create(self, network_id: str):
        await self.async_set_unique_id(network_id)
        self._abort_if_unique_id_configured()
        org_id, label = self._networks[network_id]
        return self.async_create_entry(
            title=f"Data usage ({label.split(' / ')[-1]})",
            data={CONF_API_KEY: self._api_key, CONF_ORG_ID: org_id, CONF_NETWORK_ID: network_id},
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return MerakiUsageOptionsFlow()


class MerakiUsageOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        o = self.config_entry.options
        if user_input is not None:
            url = (user_input.get(CONF_NTOPNG_URL) or "").strip()
            user_input[CONF_NTOPNG_URL] = url
            # Keep the stored secret when the field is left blank
            for k in (CONF_NTOPNG_PASSWORD, CONF_NTOPNG_TOKEN):
                if not user_input.get(k) and o.get(k):
                    user_input[k] = o[k]
            if url:
                api = NtopngApi(
                    async_get_clientsession(self.hass), url, user_input.get(CONF_NTOPNG_USER),
                    user_input.get(CONF_NTOPNG_PASSWORD), user_input.get(CONF_NTOPNG_TOKEN),
                    user_input.get(CONF_NTOPNG_IFID, 0),
                )
                try:
                    await api.check()
                except NtopngError as err:
                    errors["base"] = "ntopng_auth" if "credential" in str(err) else "ntopng_connect"
            if not errors:
                return self.async_create_entry(data=user_input)
        secret = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_SCAN_MINUTES, default=o.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)):
                    vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
                vol.Required(CONF_TOP_DEVICES, default=o.get(CONF_TOP_DEVICES, DEFAULT_TOP_DEVICES)):
                    vol.All(vol.Coerce(int), vol.Range(min=3, max=20)),
                vol.Optional(CONF_NTOPNG_URL, description={"suggested_value": o.get(CONF_NTOPNG_URL, "")}): str,
                vol.Optional(CONF_NTOPNG_USER, description={"suggested_value": o.get(CONF_NTOPNG_USER, "")}): str,
                vol.Optional(CONF_NTOPNG_PASSWORD): secret,
                vol.Optional(CONF_NTOPNG_TOKEN): secret,
                vol.Required(CONF_NTOPNG_IFID, default=o.get(CONF_NTOPNG_IFID, 0)):
                    vol.All(vol.Coerce(int), vol.Range(min=0, max=64)),
            }),
        )
