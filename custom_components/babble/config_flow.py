from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
import time
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import (
    BabbleError,
    BabbleLinkExpired,
    Tokens,
    fetch_config,
    normalize_url,
    poll_link,
    start_link,
    token_data,
    verify_link,
)
from .const import (
    CONF_ANON_KEY,
    CONF_SUPABASE_URL,
    CONF_URL,
    DOMAIN,
    LINK_POLL_SECONDS,
    LINK_TIMEOUT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}" if len(code) == 8 else code


class BabbleConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._url: str | None = None
        self._server: dict[str, Any] = {}
        self._link: dict[str, Any] | None = None
        self._task: asyncio.Task[Tokens] | None = None
        self._tokens: Tokens | None = None

    async def _connect(self, url: str) -> str | None:
        try:
            self._server = await fetch_config(async_get_clientsession(self.hass), url)
        except BabbleError:
            return "cannot_connect"
        if not self._server.get("device_sign_in"):
            return "no_device_sign_in"
        self._url = url
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._connect(normalize_url(user_input[CONF_URL]))
            if error is None:
                return await self.async_step_link()
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_URL, default=(user_input or {}).get(CONF_URL, "")): str}
            ),
            errors=errors,
        )

    async def _wait_for_approval(self) -> Tokens:
        assert self._url and self._link
        session = async_get_clientsession(self.hass)
        deadline = time.monotonic() + LINK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            token_hash = await poll_link(session, self._url, self._link["id"], self._link["secret"])
            if token_hash:
                return await verify_link(
                    session, self._server["supabase_url"], self._server["supabase_anon_key"], token_hash
                )
            await asyncio.sleep(LINK_POLL_SECONDS)
        raise BabbleLinkExpired

    async def async_step_link(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._url
        if self._task is None:
            try:
                self._link = await start_link(async_get_clientsession(self.hass), self._url)
            except BabbleError:
                return self.async_abort(reason="cannot_connect")
            self._task = self.hass.async_create_task(self._wait_for_approval())
        if not self._task.done():
            code = self._link["code"] if self._link else ""
            return self.async_show_progress(
                step_id="link",
                progress_action="approve",
                progress_task=self._task,
                description_placeholders={
                    "code": format_code(code),
                    "url": f"{self._server.get('public_url') or self._url}/link/{code}",
                },
            )
        task, self._task = self._task, None
        try:
            self._tokens = task.result()
        except BabbleLinkExpired:
            return self.async_show_progress_done(next_step_id="expired")
        except BabbleError:
            _LOGGER.exception("Signing in to babble failed")
            return self.async_show_progress_done(next_step_id="failed")
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_expired(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_form(step_id="retry")

    async def async_step_retry(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_link()

    async def async_step_failed(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_abort(reason="sign_in_failed")

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._tokens and self._url
        await self.async_set_unique_id(self._tokens.user_id)
        data = {
            CONF_URL: self._url,
            CONF_SUPABASE_URL: self._server["supabase_url"],
            CONF_ANON_KEY: self._server["supabase_anon_key"],
            **token_data(self._tokens),
        }
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self._tokens.email or "babble", data=data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._url = entry_data[CONF_URL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm", description_placeholders={"url": self._url or ""}
            )
        assert self._url
        error = await self._connect(self._url)
        if error:
            return self.async_abort(reason=error)
        return await self.async_step_link()
