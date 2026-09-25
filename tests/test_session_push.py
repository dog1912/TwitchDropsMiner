"""Tests for the pushed-session handling in webui/web_session.py (POST /api/session)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def patches():
    import webui.web_session as p

    return p


@pytest.fixture
def twitch(patches, tmp_path, monkeypatch):
    from webui.adapters.login_form import LoginFormAdapter

    monkeypatch.setattr(patches, "SESSION_PATH", tmp_path / "web_session.json")
    login = LoginFormAdapter(MagicMock())
    auth_state = SimpleNamespace(device_id="dev-1", integrity_token="old")
    return SimpleNamespace(gui=SimpleNamespace(login=login, print=MagicMock()), _auth_state=auth_state)


def test_missing_fields(patches, twitch):
    assert patches.apply_pushed_session(twitch, {"integrity": "x"})["status"] == "error"
    assert patches.apply_pushed_session(twitch, {"device_id": "dev-1"})["status"] == "error"


def test_updates_stored_integrity(patches, twitch):
    result = patches.apply_pushed_session(twitch, {"integrity": "new", "device_id": "dev-1"})
    assert result["status"] == "updated"
    assert twitch._auth_state.integrity_token == "new"
    assert patches.load_session() == {"device_id": "dev-1", "integrity": "new"}


def test_unchanged_integrity(patches, twitch):
    result = patches.apply_pushed_session(twitch, {"integrity": "old", "device_id": "dev-1"})
    assert result["status"] == "unchanged"


def test_rejects_other_device(patches, twitch):
    result = patches.apply_pushed_session(twitch, {"integrity": "new", "device_id": "dev-2"})
    assert result["status"] == "error"
    assert twitch._auth_state.integrity_token == "old"


def test_resolves_integrity_prompt(patches, twitch):
    login = twitch.gui.login
    login.session_requested = True
    login.integrity_only = True
    result = patches.apply_pushed_session(twitch, {"integrity": "new", "device_id": "dev-1"})
    assert result["status"] == "submitted"
    assert login._session.integrity == "new"
    assert login._confirm.is_set()


def test_login_prompt_needs_auth_token(patches, twitch):
    login = twitch.gui.login
    login.session_requested = True
    login.integrity_only = False
    assert patches.apply_pushed_session(
        twitch, {"integrity": "new", "device_id": "dev-9"}
    )["status"] == "error"
    result = patches.apply_pushed_session(
        twitch, {"integrity": "new", "device_id": "dev-9", "auth_token": "tok"}
    )
    assert result["status"] == "submitted"
    assert login._session == patches.WebSession("tok", "dev-9", "new")
