"""
Storage and update logic for the browser-session login workaround.

The monkey-patches that wire this into ``twitch.py`` live in ``webui/patches.py``;
this module deliberately does not import ``twitch`` so it can be unit-tested.
"""

from __future__ import annotations

import json
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from constants import CONFIG_PATH
from translate import _
from webui.adapters.login_form import WebSession

if TYPE_CHECKING:
    from twitch import Twitch, _AuthState

# Holds the browser's X-Device-Id and Client-Integrity.  The auth-token itself
# lives in cookies.jar like any other session.  The device id can't be kept in
# the jar: _validate() re-saves a pre-login cookie snapshot that carries the
# random unique_id Twitch handed out, which would replace the browser's.
SESSION_PATH = CONFIG_PATH / "web_session.json"


def load_session() -> dict[str, str]:
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_session(device_id: str, integrity: str) -> None:
    SESSION_PATH.write_text(
        json.dumps({"device_id": device_id, "integrity": integrity}), encoding="utf-8"
    )
    with suppress(OSError):
        SESSION_PATH.chmod(0o600)


def integrity_of(auth_state: "_AuthState") -> str | None:
    """Current Client-Integrity, loaded from disk on first use."""
    if not hasattr(auth_state, "integrity_token"):
        auth_state.integrity_token = load_session().get("integrity")
    return auth_state.integrity_token


def forget_session(auth_state: "_AuthState") -> None:
    auth_state._delattrs("device_id")
    auth_state.integrity_token = None
    SESSION_PATH.unlink(missing_ok=True)


def apply_pushed_session(twitch: "Twitch", data: dict[str, Any]) -> dict[str, str]:
    """
    Apply a session pushed by the browser userscript (POST /api/session).

    Resolves a pending login / integrity prompt if there is one, otherwise just
    stores the fresh Client-Integrity so the next rejection retries silently.
    """
    integrity = str(data.get("integrity") or "").strip()
    device_id = str(data.get("device_id") or "").strip()
    auth_token = str(data.get("auth_token") or "").strip()
    if not integrity or not device_id:
        return {"status": "error", "message": "integrity and device_id are required"}
    login = twitch.gui.login
    auth_state = twitch._auth_state
    if login.session_requested and not login.integrity_only:
        if not auth_token:
            return {"status": "error", "message": "auth_token is required for login"}
        login.submit_web_session(WebSession(auth_token, device_id, integrity))
        twitch.gui.print(_("webui", "login", "pushed_login"))
        return {"status": "submitted", "message": "login submitted"}
    current_device = getattr(auth_state, "device_id", None)
    if current_device is not None and device_id != current_device:
        twitch.gui.print(_("webui", "login", "pushed_other_device"))
        return {"status": "error", "message": "device_id differs from the logged-in session"}
    if login.session_requested:
        login.submit_web_session(WebSession(auth_token, device_id, integrity))
        twitch.gui.print(_("webui", "login", "pushed_integrity"))
        return {"status": "submitted", "message": "integrity submitted"}
    if integrity_of(auth_state) == integrity:
        return {"status": "unchanged", "message": "integrity already known"}
    auth_state.integrity_token = integrity
    save_session(device_id, integrity)
    twitch.gui.print(_("webui", "login", "pushed_integrity"))
    return {"status": "updated", "message": "integrity updated"}
