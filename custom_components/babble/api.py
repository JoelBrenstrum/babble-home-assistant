from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import time
from typing import Any

import aiohttp

from .const import CONF_ACCESS_TOKEN, CONF_EXPIRES_AT, CONF_REFRESH_TOKEN, DEVICE_HEADER, DEVICE_NAME

TIMEOUT = aiohttp.ClientTimeout(total=20)
REFRESH_MARGIN_SECONDS = 60


class BabbleError(Exception):
    pass


class BabbleConnectionError(BabbleError):
    pass


class BabbleAuthError(BabbleError):
    pass


class BabbleLinkExpired(BabbleError):
    pass


class BabbleActionError(BabbleError):
    pass


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float
    user_id: str
    email: str | None


def token_data(tokens: Tokens) -> dict[str, Any]:
    return {
        CONF_ACCESS_TOKEN: tokens.access_token,
        CONF_REFRESH_TOKEN: tokens.refresh_token,
        CONF_EXPIRES_AT: tokens.expires_at,
    }


def normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    return url if "://" in url else f"https://{url}"


async def _json(response: aiohttp.ClientResponse) -> Any:
    try:
        return await response.json(content_type=None)
    except (aiohttp.ContentTypeError, ValueError):
        return None


def _message(body: Any, fallback: str) -> str:
    if isinstance(body, dict):
        for key in ("error", "msg", "error_description", "message"):
            if isinstance(body.get(key), str):
                return body[key]
    return fallback


async def _call(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: Any = None,
) -> tuple[int, Any]:
    try:
        async with session.request(method, url, headers=headers, json=payload, timeout=TIMEOUT) as response:
            return response.status, await _json(response)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise BabbleConnectionError(str(err)) from err


async def fetch_config(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    status, body = await _call(session, "GET", f"{url}/api/ha/v1/config")
    if status != 200 or not isinstance(body, dict) or "supabase_url" not in body:
        raise BabbleConnectionError(f"{url} doesn't look like a babble server")
    return body


async def start_link(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    status, body = await _call(session, "POST", f"{url}/api/device-link", payload={})
    if status != 200 or not isinstance(body, dict):
        raise BabbleConnectionError(_message(body, f"Couldn't start signing in ({status})"))
    return body


async def poll_link(session: aiohttp.ClientSession, url: str, link_id: str, secret: str) -> str | None:
    status, body = await _call(
        session, "POST", f"{url}/api/device-link/poll", payload={"id": link_id, "secret": secret}
    )
    if status != 200 or not isinstance(body, dict):
        raise BabbleConnectionError(_message(body, f"Couldn't check the sign-in code ({status})"))
    if body.get("status") == "approved" and body.get("tokenHash"):
        return body["tokenHash"]
    if body.get("status") == "pending":
        return None
    raise BabbleLinkExpired


def _tokens(body: Any) -> Tokens:
    if not isinstance(body, dict) or "access_token" not in body:
        raise BabbleAuthError("Sign-in failed")
    user = body.get("user") or {}
    expires_at = body.get("expires_at") or time.time() + float(body.get("expires_in", 3600))
    return Tokens(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=float(expires_at),
        user_id=user.get("id", ""),
        email=user.get("email"),
    )


def _auth_headers(anon_key: str) -> dict[str, str]:
    return {"apikey": anon_key, "authorization": f"Bearer {anon_key}"}


async def verify_link(
    session: aiohttp.ClientSession, supabase_url: str, anon_key: str, token_hash: str
) -> Tokens:
    status, body = await _call(
        session,
        "POST",
        f"{supabase_url}/auth/v1/verify",
        headers=_auth_headers(anon_key),
        payload={"type": "magiclink", "token_hash": token_hash},
    )
    if status != 200:
        raise BabbleAuthError(_message(body, "Sign-in failed"))
    return _tokens(body)


async def refresh_tokens(
    session: aiohttp.ClientSession, supabase_url: str, anon_key: str, refresh_token: str
) -> Tokens:
    status, body = await _call(
        session,
        "POST",
        f"{supabase_url}/auth/v1/token?grant_type=refresh_token",
        headers=_auth_headers(anon_key),
        payload={"refresh_token": refresh_token},
    )
    if status in (400, 401, 403):
        raise BabbleAuthError(_message(body, "Signed out"))
    if status != 200:
        raise BabbleConnectionError(_message(body, f"Couldn't refresh the sign-in ({status})"))
    return _tokens(body)


class BabbleClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        supabase_url: str,
        anon_key: str,
        tokens: Tokens,
        on_tokens: Callable[[Tokens], None],
    ) -> None:
        self._session = session
        self.url = url
        self._supabase_url = supabase_url
        self._anon_key = anon_key
        self._tokens = tokens
        self._on_tokens = on_tokens
        self._lock = asyncio.Lock()

    async def _refresh(self, stale: str) -> None:
        async with self._lock:
            if self._tokens.access_token != stale:
                return
            self._tokens = await refresh_tokens(
                self._session, self._supabase_url, self._anon_key, self._tokens.refresh_token
            )
            self._on_tokens(self._tokens)

    async def _access_token(self) -> str:
        token = self._tokens.access_token
        if self._tokens.expires_at - REFRESH_MARGIN_SECONDS <= time.time():
            await self._refresh(token)
        return self._tokens.access_token

    async def _request(self, method: str, path: str, payload: Any = None) -> Any:
        for attempt in range(2):
            token = await self._access_token()
            status, body = await _call(
                self._session,
                method,
                f"{self.url}{path}",
                headers={"authorization": f"Bearer {token}", DEVICE_HEADER: DEVICE_NAME},
                payload=payload,
            )
            if status == 401 and attempt == 0:
                await self._refresh(token)
                continue
            if status == 401:
                raise BabbleAuthError(_message(body, "Signed out"))
            if status in (400, 403, 404, 409):
                raise BabbleActionError(_message(body, f"babble refused that ({status})"))
            if status != 200:
                raise BabbleConnectionError(_message(body, f"babble returned {status}"))
            return body
        raise BabbleAuthError("Signed out")

    async def babies(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/api/ha/v1/babies")

    async def state(self, baby_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/ha/v1/babies/{baby_id}/state")

    async def action(self, baby_id: str, name: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("POST", f"/api/ha/v1/babies/{baby_id}/actions/{name}", data or {})
