"""Polls Meraki for today's usage and shapes it for the Sankey card."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import MerakiApi, MerakiApiError, MerakiAuthError
from .const import APPS_PER_DEVICE, DOMAIN

_LOGGER = logging.getLogger(__name__)
KB = 1024

UPLINK_NAMES = {"wan1": "WAN 1", "wan2": "WAN 2", "cellular": "Cellular", "wan3": "WAN 3"}


def _client_name(c: dict) -> str:
    return (
        c.get("description")
        or c.get("dhcpHostname")
        or c.get("mdnsName")
        or c.get("ip")
        or c.get("mac")
        or "Unknown"
    )


class MerakiUsageCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch usage since local midnight."""

    def __init__(
        self, hass: HomeAssistant, api: MerakiApi, org_id: str, network_id: str,
        scan_minutes: int, top_devices: int,
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=timedelta(minutes=scan_minutes)
        )
        self.api = api
        self.org_id = org_id
        self.network_id = network_id
        self.top_devices = top_devices
        self._day = None
        self._max_total = 0

    async def _async_update_data(self) -> dict[str, Any]:
        now = dt_util.now()
        midnight = dt_util.start_of_local_day()
        timespan = max(int((now - midnight).total_seconds()), 300)

        try:
            clients = await self.api.clients(self.network_id, timespan)
            try:
                uplinks_raw = await self.api.uplink_usage(self.org_id, timespan)
            except MerakiApiError as err:
                _LOGGER.debug("Uplink usage unavailable: %s", err)
                uplinks_raw = []

            # Rank clients by total usage
            ranked = []
            for c in clients:
                u = c.get("usage") or {}
                down = float(u.get("recv") or 0) * KB
                up = float(u.get("sent") or 0) * KB
                if down + up <= 0:
                    continue
                ranked.append({
                    "id": c.get("id"),
                    "name": _client_name(c),
                    "mac": c.get("mac"),
                    "ip": c.get("ip"),
                    "down": down,
                    "up": up,
                })
            ranked.sort(key=lambda d: d["down"] + d["up"], reverse=True)
            top = ranked[: self.top_devices]
            rest = ranked[self.top_devices:]

            app_rows = await self.api.client_app_usage(
                self.network_id, [d["id"] for d in top if d["id"]], timespan
            )
        except MerakiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MerakiApiError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # network errors, timeouts
            raise UpdateFailed(f"Meraki request failed: {err}") from err

        apps_by_client: dict[str, list[dict]] = {}
        for row in app_rows or []:
            cid = row.get("clientId")
            apps = []
            for a in row.get("applicationUsage") or []:
                b = (float(a.get("received") or 0) + float(a.get("sent") or 0)) * KB
                if b > 0:
                    apps.append({"name": a.get("application") or "Unknown", "bytes": b})
            apps.sort(key=lambda a: a["bytes"], reverse=True)
            apps_by_client[cid] = apps

        devices = []
        for d in top:
            apps = apps_by_client.get(d["id"], [])
            shown = apps[:APPS_PER_DEVICE]
            other = sum(a["bytes"] for a in apps[APPS_PER_DEVICE:])
            if other > 0:
                shown.append({"name": "Other apps", "bytes": other})
            devices.append({
                "name": d["name"], "mac": d["mac"], "ip": d["ip"],
                "down": round(d["down"]), "up": round(d["up"]),
                "apps": [{"name": a["name"], "bytes": round(a["bytes"])} for a in shown],
            })

        other_devices = {
            "count": len(rest),
            "down": round(sum(d["down"] for d in rest)),
            "up": round(sum(d["up"] for d in rest)),
        }

        lines = []
        for net in uplinks_raw or []:
            if net.get("networkId") != self.network_id:
                continue
            for u in net.get("byUplink") or []:
                down = float(u.get("received") or 0)
                up = float(u.get("sent") or 0)
                iface = u.get("interface") or "wan"
                lines.append({
                    "name": UPLINK_NAMES.get(iface, iface.upper()),
                    "down": round(down), "up": round(up),
                })
        lines = [l for l in lines if l["down"] + l["up"] > 0] or lines

        clients_total = sum(d["down"] + d["up"] for d in ranked)
        lines_total = sum(l["down"] + l["up"] for l in lines)
        total = lines_total if lines_total > 0 else clients_total
        not_broken_down = max(total - clients_total, 0)

        # Keep the daily total monotonic so long-term stats don't see false resets
        today = midnight.date()
        if self._day != today:
            self._day = today
            self._max_total = 0
        self._max_total = max(self._max_total, total)

        return {
            "since": midnight.isoformat(),
            "updated": now.isoformat(),
            "total": self._max_total,
            "lines": lines,
            "devices": devices,
            "other_devices": other_devices,
            "not_broken_down": round(not_broken_down),
            "client_count": len(ranked),
        }
