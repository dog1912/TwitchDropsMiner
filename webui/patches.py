"""
WebUI-only monkey-patches that extend core classes without editing them.

Imported once from ``main_webui.py`` after the core modules are loaded, so the
fork keeps its diff against upstream minimal.
"""

from __future__ import annotations

import settings as _settings
import inventory as _inventory

import webui.translations  # noqa

_settings.default_settings["priority_link_override"] = False  # type: ignore[typeddict-unknown-key]


def _priority_link_override_get(self) -> bool:
    """
    True when the user has enabled the advanced "priority link override"
    setting and explicitly added this (unlinked) game to the Priority List.

    This does not change Twitch's reported account-link state; Twitch may
    still refuse to award drops for a campaign the account isn't linked to.
    """
    return (
        self._twitch.settings.priority_link_override
        and not self.linked
        and self.game.name in self._twitch.settings.priority
    )


setattr(
    _inventory.DropsCampaign,
    "priority_link_override",
    property(_priority_link_override_get),
)


def _eligible_get(self) -> bool:
    return _original_eligible(self) or (
        not self.has_badge_or_emote and self.priority_link_override
    )


_original_eligible = _inventory.DropsCampaign.__dict__["eligible"].fget

setattr(
    _inventory.DropsCampaign,
    "eligible",
    property(_eligible_get),
)


# --- Web-session login workaround ----------------------------------------
# Since 2026-09 Twitch answers the device-code login with HTTP 400 "invalid
# client" for every client the miner can present as (upstream issue #1165).
# The only client that still gets a device code (SMARTBOX) receives tokens that
# can't see drop campaigns, so that isn't a way out either.  What does work is
# a session issued to the real website: the ``auth-token`` cookie plus the
# ``X-Device-Id`` and ``Client-Integrity`` headers the browser sends to GQL.
# The patches below make the miner present as the WEB client, ask the user to
# paste those three values instead of running the device-code flow, attach
# ``Client-Integrity`` to every GQL request, and ask for a fresh one when Twitch
# rejects it (they expire after ~16h).  Remove once upstream login works again.

import asyncio
import json
import logging
from contextlib import suppress

import twitch as _twitch
from constants import CONFIG_PATH, ClientType
from exceptions import GQLException
from translate import _

# Holds the browser's X-Device-Id and Client-Integrity.  The auth-token itself
# lives in cookies.jar like any other session.  The device id can't be kept in
# the jar: _validate() re-saves a pre-login cookie snapshot that carries the
# random unique_id Twitch handed out, which would replace the browser's.
SESSION_PATH = CONFIG_PATH / "web_session.json"
_logger = logging.getLogger("TwitchDrops")


def _load_session() -> dict[str, str]:
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_session(device_id: str, integrity: str) -> None:
    SESSION_PATH.write_text(
        json.dumps({"device_id": device_id, "integrity": integrity}), encoding="utf-8"
    )
    with suppress(OSError):
        SESSION_PATH.chmod(0o600)


def _integrity(auth_state: _twitch._AuthState) -> str | None:
    if not hasattr(auth_state, "integrity_token"):
        auth_state.integrity_token = _load_session().get("integrity")
    return auth_state.integrity_token


def forget_session(auth_state: _twitch._AuthState) -> None:
    auth_state._delattrs("device_id")
    auth_state.integrity_token = None
    SESSION_PATH.unlink(missing_ok=True)


_original_twitch_init = _twitch.Twitch.__init__


def _twitch_init(self, settings) -> None:
    _original_twitch_init(self, settings)
    # Client-Integrity is only honoured together with the website's Client-Id.
    self._client_type = ClientType.WEB


setattr(_twitch.Twitch, "__init__", _twitch_init)

_original_validate = _twitch._AuthState._validate


async def _validate(self: _twitch._AuthState) -> None:
    # Restore the browser's device id before _validate() would mint one from
    # the unique_id cookie (also after clear() on reload).
    if not hasattr(self, "device_id") and (device_id := _load_session().get("device_id")):
        self.device_id = device_id
    await _original_validate(self)


setattr(_twitch._AuthState, "_validate", _validate)


async def _oauth_login(self: _twitch._AuthState) -> str:
    login_form = self._twitch.gui.login
    client_info = self._twitch._client_type
    error = ""
    while True:
        data = await login_form.ask_web_session(error=error)
        async with self._twitch.request(
            "GET",
            "https://id.twitch.tv/oauth2/validate",
            headers={"Authorization": f"OAuth {data.auth_token}"},
        ) as response:
            if response.status != 200:
                error = _("webui", "login", "invalid_token")
                continue
            client_id = (await response.json()).get("client_id")
        if client_id != client_info.CLIENT_ID:
            error = _("webui", "login", "wrong_client")
            continue
        break
    self.device_id = data.device_id
    self.integrity_token = data.integrity
    _save_session(data.device_id, data.integrity)
    return data.auth_token


setattr(_twitch._AuthState, "_oauth_login", _oauth_login)

_original_headers = _twitch._AuthState.headers


def _headers(self: _twitch._AuthState, *, user_agent: str = "", gql: bool = False):
    headers = _original_headers(self, user_agent=user_agent, gql=gql)
    if gql and (token := _integrity(self)):
        headers["Client-Integrity"] = token
    return headers


setattr(_twitch._AuthState, "headers", _headers)

_original_gql_request = _twitch.Twitch.gql_request


async def _gql_request(self: _twitch.Twitch, ops):
    while True:
        auth_state = await self.get_auth()
        used_token = _integrity(auth_state)
        try:
            return await _original_gql_request(self, ops)
        except GQLException as exc:
            if "failed integrity check" not in str(exc):
                raise
        await _refresh_integrity(self, used_token)


async def _refresh_integrity(twitch: _twitch.Twitch, used_token: str | None) -> None:
    auth_state = twitch._auth_state
    lock = auth_state.__dict__.setdefault("_integrity_lock", asyncio.Lock())
    async with lock:
        if _integrity(auth_state) != used_token:
            return  # another task already got a fresh token; just retry
        _logger.warning("Client-Integrity token rejected, asking for a new one")
        data = await twitch.gui.login.ask_web_session(integrity_only=True)
        auth_state.integrity_token = data.integrity
        _save_session(auth_state.device_id, data.integrity)


setattr(_twitch.Twitch, "gql_request", _gql_request)
