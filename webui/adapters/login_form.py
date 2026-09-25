from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from translate import _

if TYPE_CHECKING:
    from yarl import URL
    from webui.manager import WebUIManager


@dataclass
class LoginData:
    username: str
    password: str
    token: str


@dataclass
class WebSession:
    """Values copied from a logged-in browser session on www.twitch.tv."""

    auth_token: str
    device_id: str
    integrity: str


class LoginFormAdapter:
    """
    Mirrors LoginForm - updates the login status labels and handles
    the device-code activation flow.

    The webui additionally implements the web-session login (see
    ``webui/patches.py``): ``ask_web_session`` shows a form asking for the
    browser's auth-token / X-Device-Id / Client-Integrity values and waits
    until ``submit_web_session`` is called from the UI.
    """

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager
        self._confirm = asyncio.Event()
        self.page_url: "URL | None" = None
        # web-session form state, read by LoginSection through bindings
        self.session_requested: bool = False
        self.integrity_only: bool = False
        self.form_error: str = ""
        self._session: WebSession | None = None

    def clear(self, login: bool = False, password: bool = False, token: bool = False):
        pass

    async def wait_for_login_press(self) -> None:
        self._confirm.clear()
        await self._manager.coro_unless_closed(self._confirm.wait())

    async def ask_login(self) -> LoginData:
        """Deprecated login flow; device-code flow is required."""
        return LoginData("", "", "")

    async def ask_enter_code(self, page_url: "URL", user_code: str) -> None:
        """Show the login button and wait for the user to click it before polling begins."""
        self.page_url = page_url
        self.update(_("gui", "login", "required"), None)
        self._manager.grab_attention(sound=False)
        self._manager.print(_("gui", "login", "request"))
        await self.wait_for_login_press()

    def confirm(self) -> None:
        """Signal that the user has pressed the login button."""
        self._confirm.set()

    async def ask_web_session(
        self, *, integrity_only: bool = False, error: str = ""
    ) -> WebSession:
        """
        Ask the user to paste a browser session and wait for it.

        With ``integrity_only`` the user is logged in already and only a fresh
        Client-Integrity value is needed, so the login status is left alone.
        """
        self.page_url = None
        self.integrity_only = integrity_only
        self.form_error = error
        self.session_requested = True
        if not integrity_only:
            self.update(_("gui", "login", "required"), None)
        self._manager.grab_attention(sound=False)
        self._manager.print(
            _("webui", "login", "integrity_request" if integrity_only else "session_request")
        )
        try:
            await self.wait_for_login_press()
        finally:
            self.session_requested = False
        assert self._session is not None
        return self._session

    def submit_web_session(self, session: WebSession) -> None:
        """Called by LoginSection when the user submits the web-session form."""
        self._session = session
        self.form_error = ""
        self._confirm.set()

    def update(self, status: str, user_id: int | None):
        self._manager.main_panel.update_login(status, user_id)
        # Mirror login state to the status bar when the main loop hasn't set it yet
        login_statuses = (
            _("gui", "login", "logging_in"),
            _("gui", "login", "required"),
            _("gui", "login", "logged_out"),
        )
        if status in login_statuses:
            self._manager.status.update(status)
