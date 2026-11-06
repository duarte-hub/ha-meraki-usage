"""Minimal ntopng REST client for per-host live flows."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class NtopngError(Exception):
    """ntopng request failed."""


class NtopngNotFound(NtopngError):
    """ntopng has no record of the requested object (e.g. a host with no active flows)."""


class NtopngApi:
    def __init__(self, session: aiohttp.ClientSession, url: str, user: str | None,
                 password: str | None, token: str | None, ifid: int = 0) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._ifid = ifid
        self._headers = {"Accept": "application/json"}
        self._auth = None
        if token:
            self._headers["Authorization"] = f"Token {token}"
        elif user:
            self._auth = aiohttp.BasicAuth(user, password or "")

    async def _get(self, path: str, params: dict) -> Any:
        try:
            async with self._session.get(
                f"{self._url}{path}", params=params, headers=self._headers, auth=self._auth,
                timeout=aiohttp.ClientTimeout(total=10), allow_redirects=False,
            ) as resp:
                if resp.status in (301, 302, 401, 403):
                    raise NtopngError("ntopng rejected the credentials")
                if resp.status == 404:
                    raise NtopngNotFound("ntopng returned HTTP 404")
                if resp.status >= 400:
                    raise NtopngError(f"ntopng returned HTTP {resp.status}")
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise NtopngError(f"Cannot reach ntopng: {err}") from err
        if isinstance(data, dict) and data.get("rc", 0) != 0:
            raise NtopngError(data.get("rc_str_hr") or data.get("rc_str") or "ntopng error")
        return data.get("rsp", data) if isinstance(data, dict) else data

    async def check(self) -> None:
        await self._get("/lua/rest/v2/get/ntopng/interfaces.lua", {})

    async def host_flows(self, ip: str, limit: int = 40) -> dict:
        # ntopng answers 404 NOT_FOUND when the host isn't in its active host table,
        # i.e. it has had no flows recently (idle, asleep, or not seen via NetFlow yet).
        try:
            rsp = await self._get("/lua/rest/v2/get/flow/active.lua", {
                "ifid": self._ifid, "host": ip, "perPage": limit, "currentPage": 1,
                "sortColumn": "bytes", "sortOrder": "desc",
            })
        except NtopngNotFound:
            return {"flows": [], "total": 0}
        rows = rsp.get("data", rsp) if isinstance(rsp, dict) else rsp
        flows = [self._norm(f, ip) for f in rows or [] if isinstance(f, dict)]
        total = rsp.get("recordsTotal") if isinstance(rsp, dict) else None
        return {"flows": flows, "total": total if total is not None else len(flows)}

    @staticmethod
    def _norm(f: dict, ip: str) -> dict:
        def ep(key: str) -> dict:
            v = f.get(key) or {}
            if not isinstance(v, dict):
                v = {"ip": v}
            return {"ip": v.get("ip"), "name": v.get("name") or v.get("ip"), "port": v.get("port")}

        cli, srv = ep("client"), ep("server")
        outbound = cli["ip"] == ip or srv["ip"] != ip
        peer = srv if outbound else cli
        proto = f.get("protocol") or {}
        if not isinstance(proto, dict):
            proto = {"l7": proto}
        thpt = f.get("thpt") or {}
        if not isinstance(thpt, dict):
            thpt = {"bps": thpt}
        brk = f.get("breakdown") or {}
        total_bytes = f.get("bytes") or 0
        if isinstance(total_bytes, dict):
            total_bytes = total_bytes.get("total") or 0
        c2s = brk.get("cli2srv") if isinstance(brk, dict) else None
        if isinstance(c2s, (int, float)) and c2s <= 100:  # percentage breakdown
            up = total_bytes * c2s / 100
        else:
            up = f.get("cli2srv_bytes") or 0
        down = max(total_bytes - up, 0)
        if not outbound:
            up, down = down, up
        return {
            "peer": peer["name"], "peer_ip": peer["ip"], "port": peer["port"],
            "l4": proto.get("l4") or f.get("l4_proto"),
            "app": proto.get("l7") or proto.get("l7_proto") or f.get("application"),
            "bps": thpt.get("bps") or 0, "bytes": total_bytes,
            "down": round(down), "up": round(up),
            "duration": f.get("duration"), "last_seen": f.get("last_seen"),
        }
