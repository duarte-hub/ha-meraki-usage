"""Minimal async Meraki Dashboard API client."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import aiohttp

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)
_NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel=next')


class MerakiApiError(Exception):
    """Raised when the Meraki API returns an error."""


class MerakiAuthError(MerakiApiError):
    """Raised on 401/403."""


class MerakiApi:
    """Tiny wrapper around the endpoints this integration needs."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._headers = {
            "X-Cisco-Meraki-API-Key": api_key,
            "Accept": "application/json",
            "User-Agent": "HomeAssistant-MerakiUsage/0.1",
        }

    async def _get(self, url: str, params: dict | None = None) -> tuple[Any, str | None]:
        if not url.startswith("http"):
            url = f"{API_BASE}{url}"
        for attempt in range(4):
            async with self._session.get(
                url, headers=self._headers, params=params,
                timeout=aiohttp.ClientTimeout(total=45),
            ) as resp:
                if resp.status == 429:
                    wait = float(resp.headers.get("Retry-After", 2))
                    _LOGGER.debug("Meraki rate limited, waiting %ss", wait)
                    await asyncio.sleep(min(wait, 10))
                    continue
                if resp.status in (401, 403):
                    raise MerakiAuthError(f"{resp.status} on {url}")
                if resp.status >= 400:
                    text = await resp.text()
                    raise MerakiApiError(f"{resp.status} on {url}: {text[:300]}")
                data = await resp.json(content_type=None)
                match = _NEXT_LINK.search(resp.headers.get("Link", ""))
                return data, (match.group(1) if match else None)
        raise MerakiApiError(f"Rate limited too many times on {url}")

    async def get(self, path: str, params: dict | None = None) -> Any:
        data, _ = await self._get(path, params)
        return data

    async def get_all(self, path: str, params: dict | None = None) -> list:
        """Follow Link: rel=next pagination."""
        items: list = []
        data, nxt = await self._get(path, params)
        items.extend(data or [])
        pages = 1
        while nxt and pages < 20:
            data, nxt = await self._get(nxt)
            items.extend(data or [])
            pages += 1
        return items

    async def organizations(self) -> list[dict]:
        return await self.get("/organizations")

    async def networks(self, org_id: str) -> list[dict]:
        return await self.get_all(f"/organizations/{org_id}/networks", {"perPage": 1000})

    async def clients(self, network_id: str, timespan: int) -> list[dict]:
        return await self.get_all(
            f"/networks/{network_id}/clients",
            {"timespan": timespan, "perPage": 5000},
        )

    async def client_app_usage(self, network_id: str, client_ids: list[str], timespan: int) -> list[dict]:
        if not client_ids:
            return []
        return await self.get_all(
            f"/networks/{network_id}/clients/applicationUsage",
            {"clients": ",".join(client_ids), "timespan": timespan, "perPage": 1000},
        )

    async def top_apps(self, org_id: str, timespan: int) -> list[dict]:
        """Org-wide application usage (MB) as seen by the MX."""
        return await self.get(
            f"/organizations/{org_id}/summary/top/applications/byUsage",
            {"timespan": timespan, "quantity": 50},
        )

    async def network_traffic(self, network_id: str, timespan: int) -> list[dict]:
        """Network traffic by application/destination (KB). Timespan >= 2h."""
        return await self.get(
            f"/networks/{network_id}/traffic",
            {"timespan": max(timespan, 7200), "deviceType": "combined"},
        )

    async def uplink_usage(self, org_id: str, timespan: int) -> list[dict]:
        return await self.get(
            f"/organizations/{org_id}/appliance/uplinks/usage/byNetwork",
            {"timespan": timespan},
        )
