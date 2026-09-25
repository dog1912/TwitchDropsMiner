from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import app, ui

from translate import _
from webui.adapters.login_form import WebSession
from webui.html_utils import close_popup_js, popup_js

if TYPE_CHECKING:
    from webui.manager import WebUIManager

_LOGIN_KEYS = ("logged_in", "logging_in", "required", "logged_out")


class LoginSection:
    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager
        self._login_state: str = ""
        self._user_str: str = "-"
        self._btn_enabled: bool = True
        self._popup_maybe_open: bool = False

    def update(self, status: str, user_id: int | None) -> None:
        self._login_state = self._key_for_status(status)
        self._user_str = str(user_id) if user_id is not None else "-"
        self._btn_enabled = True
        if self._popup_maybe_open and self._login_state == "logged_in":
            self._close_login_popup()

    def build(self) -> None:
        login = self._manager.login
        dialog = self._build_session_dialog()
        with (
            ui.card().props("flat bordered").classes("gap-1 grow shrink basis-[180px]")
        ):
            ui.label(_("gui", "login", "name")).classes("font-bold text-sm mb-1")
            with ui.row().classes("gap-4 items-start"):
                ui.label(_("gui", "login", "labels")).classes(
                    "text-xs whitespace-pre leading-relaxed"
                )
                ui.label().classes(
                    "text-xs whitespace-pre leading-relaxed"
                ).bind_text_from(
                    self,
                    "_login_state",
                    backward=lambda s: (
                        _("gui", "login", s) + "\n" + self._user_str
                        if s in _LOGIN_KEYS
                        else "\n-"
                    ),
                )
            with ui.row().classes("gap-2"):
                ui.button(
                    on_click=lambda: self._on_btn_click(dialog),
                ).props(
                    "dense"
                ).classes("text-xs").bind_text_from(
                    self,
                    "_login_state",
                    backward=lambda s: (
                        _("webui", "login", "logout")
                        if s == "logged_in"
                        else _("gui", "login", "button")
                    ),
                ).bind_visibility_from(
                    self,
                    "_login_state",
                    backward=lambda s: s in ("logged_in", "required"),
                ).bind_enabled_from(
                    self, "_btn_enabled"
                )
                # shown while the backend waits for a fresh Client-Integrity
                ui.button(
                    _("webui", "login", "integrity_button"),
                    on_click=dialog.open,
                    color="warning",
                ).props("dense").classes("text-xs").bind_visibility_from(
                    login,
                    "session_requested",
                    backward=lambda requested: requested and login.integrity_only,
                )

    def _build_session_dialog(self) -> ui.dialog:
        login = self._manager.login
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl gap-2"):
            ui.label(_("webui", "login", "session_title")).classes("font-bold")
            ui.markdown(_("webui", "login", "session_help")).classes("text-xs")
            token = (
                ui.input(_("webui", "login", "auth_token"), password=True)
                .props("dense outlined")
                .classes("w-full")
                .bind_visibility_from(login, "integrity_only", backward=lambda v: not v)
            )
            device = (
                ui.input(_("webui", "login", "device_id"))
                .props("dense outlined")
                .classes("w-full")
                .bind_visibility_from(login, "integrity_only", backward=lambda v: not v)
            )
            integrity = (
                ui.input(_("webui", "login", "integrity"), password=True)
                .props("dense outlined")
                .classes("w-full")
            )
            ui.label().classes("text-xs text-negative").bind_text_from(
                login, "form_error"
            )

            def submit() -> None:
                values = WebSession(
                    auth_token=(token.value or "").strip(),
                    device_id=(device.value or "").strip(),
                    integrity=(integrity.value or "").strip(),
                )
                required = (
                    (values.integrity,)
                    if login.integrity_only
                    else (values.auth_token, values.device_id, values.integrity)
                )
                if not all(required):
                    login.form_error = _("webui", "login", "required_fields")
                    return
                if not login.session_requested:
                    login.form_error = _("webui", "login", "not_requested")
                    return
                login.submit_web_session(values)
                token.value = device.value = integrity.value = ""
                dialog.close()

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(_("webui", "game_list", "cancel"), on_click=dialog.close).props(
                    "flat dense"
                )
                ui.button(_("webui", "login", "submit"), on_click=submit).props("dense")
        return dialog

    async def _open_login_popup(self) -> None:
        url = self._manager.login.page_url
        if url is not None:
            self._popup_maybe_open = True
            blocked = not await ui.run_javascript(popup_js(str(url), "twitch_login"))
            if blocked:
                self._manager.print(f"{str(url)}")
        self._manager.login.confirm()

    def _close_login_popup(self) -> None:
        self._popup_maybe_open = False
        js = close_popup_js("twitch_login")
        for client in app.clients():
            with client:
                ui.run_javascript(js)

    async def _on_btn_click(self, dialog: ui.dialog) -> None:
        if self._login_state == "logged_in":
            self._btn_enabled = False
            await self._manager.logout()
        elif self._manager.login.page_url is not None:
            await self._open_login_popup()
        else:
            dialog.open()

    @staticmethod
    def _key_for_status(status: str) -> str:
        for key in _LOGIN_KEYS:
            if status == _("gui", "login", key):
                return key
        return ""
