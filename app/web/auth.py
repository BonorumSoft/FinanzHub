from __future__ import annotations

import hashlib
import os
import secrets
from functools import wraps
from typing import Any

from flask import Response, redirect, request, session

from app.logger import get_logger

logger = get_logger(__name__)

SESSION_KEY = "finanzhub_user"
COOKIE_MAX_AGE = 86400


def _load_password() -> str:
    pw = os.environ.get("WEB_PASSWORD", "")
    if pw:
        return pw
    try:
        from app.config_loader import load_all
        cfg = load_all().get("settings", {})
        pw = getattr(cfg, "web", None) or {}
        pw = getattr(pw, "password", "") if hasattr(pw, "password") else ""
    except Exception:
        pass
    if not pw:
        pw = secrets.token_urlsafe(16)
        logger.warning("Kein WEB_PASSWORD gesetzt – verwende temporäres Passwort: %s", pw)
    return pw


_PASSWORD = ""


def _get_password() -> str:
    global _PASSWORD
    if not _PASSWORD:
        _PASSWORD = _load_password()
    return _PASSWORD


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def login_required(f):
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Response | Any:
        if session.get(SESSION_KEY) != _hash(_get_password()):
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper


def do_login(password: str) -> bool:
    if password == _get_password():
        session.clear()
        session[SESSION_KEY] = _hash(password)
        session.permanent = True
        return True
    return False


def do_logout() -> None:
    session.clear()
