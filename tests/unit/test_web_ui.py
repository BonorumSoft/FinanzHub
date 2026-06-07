"""Tests für das Web-UI Dashboard."""

from __future__ import annotations

import os

from app.data.db import build_engine
from app.web.server import _create_app


def test_app_creation() -> None:
    """Die Flask-App kann mit einem SQLite-In-Memory-Engine erstellt werden."""
    engine = build_engine()
    app = _create_app(engine)
    assert app is not None
    assert app.name == "app.web.server"


def test_login_page_returns_200() -> None:
    """Die Login-Seite liefert Status 200."""
    engine = build_engine()
    app = _create_app(engine)
    client = app.test_client()
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"FinanzHub" in resp.data


def test_dashboard_redirects_without_login() -> None:
    """Ohne Login wird / zur Login-Seite umgeleitet."""
    engine = build_engine()
    app = _create_app(engine)
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_transactions_redirects_without_login() -> None:
    engine = build_engine()
    app = _create_app(engine)
    client = app.test_client()
    resp = client.get("/transactions")
    assert resp.status_code == 302


def test_inbox_redirects_without_login() -> None:
    engine = build_engine()
    app = _create_app(engine)
    client = app.test_client()
    resp = client.get("/inbox")
    assert resp.status_code == 302


def test_settings_redirects_without_login() -> None:
    engine = build_engine()
    app = _create_app(engine)
    client = app.test_client()
    resp = client.get("/settings")
    assert resp.status_code == 302


def test_login_with_correct_password(monkeypatch) -> None:
    """Login mit korrektem Passwort gibt Session-Cookie."""
    monkeypatch.setenv("WEB_PASSWORD", "geheim")
    # auth-Modul muss neu geladen werden, da _PASSWORD cached
    import importlib
    from app.web import auth
    importlib.reload(auth)
    engine = build_engine()
    app = _create_app(engine)
    client = app.test_client()
    resp = client.post("/login", data={"password": "geheim"}, follow_redirects=True)
    assert resp.status_code == 200
    # nach erfolgreichem Login landen wir auf /
    assert resp.request.path == "/"


def test_login_with_wrong_password() -> None:
    """Login mit falschem Passwort gibt Fehlermeldung."""
    engine = build_engine()
    app = _create_app(engine)
    client = app.test_client()
    resp = client.post("/login", data={"password": "falsch"})
    assert resp.status_code == 200
    assert b"Falsches Passwort" in resp.data
