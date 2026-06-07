from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, render_template, request, session
from sqlalchemy.engine import Engine

from app.config_loader import load_all
from app.data.db import execute
from app.logger import get_logger
from app.web.auth import do_login, do_logout, login_required

logger = get_logger(__name__)

HERE = Path(__file__).resolve().parent


def _sql_date(d: date) -> str:
    return d.isoformat()


def _create_app(engine: Engine) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(HERE / "templates"),
        static_folder=str(HERE / "static"),
        static_url_path="/static/web",
    )
    app.secret_key = "".join(str(hash(str(engine.url))) * 2)
    app.config["SESSION_COOKIE_MAX_AGE"] = 86400

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if do_login(request.form.get("password", "")):
                return _redirect("/")
            return render_template("web/login.html", error="Falsches Passwort")
        return render_template("web/login.html", error=None)

    @app.route("/logout")
    def logout():
        do_logout()
        return _redirect("/login")

    @app.route("/")
    @login_required
    def dashboard():
        today = date.today()
        start_30 = today - timedelta(days=30)

        row = _safe_query(engine, _LATEST_NW_SQL)
        row = row[0] if row else None
        recent = _safe_query(engine, _RECENT_TX_SQL, {"l": 10}, default=[])
        nw_history = _safe_query(engine, _NW_HISTORY_SQL, {"s": (date.today() - timedelta(days=90)).isoformat()}, default=[])
        events = _safe_query(engine, _EVENTS_SQL, {"l": 5}, default=[])
        inbox_stats_raw = _safe_query(engine, _INBOX_SQL, default=[])
        inbox_stats = {r["status"]: r["cnt"] for r in inbox_stats_raw} if inbox_stats_raw else {}
        balances = _safe_query(engine, _BALANCES_SQL, default=[])

        return render_template(
            "web/dashboard.html",
            nw=row,
            recent=recent,
            nw_history=nw_history,
            events=events,
            inbox_stats=inbox_stats,
            balances=balances,
            today=today.isoformat(),
        )

    @app.route("/transactions")
    @login_required
    def transactions():
        days = request.args.get("days", "30")
        try:
            days_int = max(1, min(365, int(days)))
        except ValueError:
            days_int = 30
        since = (date.today() - timedelta(days=days_int)).isoformat()
        rows = _safe_query(
            engine,
            "SELECT transaction_id, account_id, booking_date, amount, "
            "description, counterparty_name, counterparty_iban, category "
            "FROM transactions WHERE booking_date >= :s "
            "ORDER BY booking_date DESC, id DESC LIMIT 200",
            {"s": since},
            default=[],
        )
        total = sum(r["amount"] for r in rows) if rows else 0
        return render_template(
            "web/transactions.html",
            rows=rows,
            days=days_int,
            since=since,
            total=total,
        )

    @app.route("/inbox")
    @login_required
    def inbox():
        status_filter = request.args.get("status", "")
        base_sql = (
            "SELECT id, source_email, source_subject, received_at, "
            "original_filename, extracted_date, extracted_amount, "
            "extracted_merchant, status, match_confidence, steuerrelevant "
            "FROM receipts"
        )
        params: dict[str, Any] = {}
        if status_filter:
            base_sql += " WHERE status = :s"
            params["s"] = status_filter
        base_sql += " ORDER BY received_at DESC LIMIT 100"
        rows = _safe_query(engine, base_sql, params, default=[])
        inbox_stats_raw = _safe_query(engine, _INBOX_SQL, default=[])
        counts = {r["status"]: r["cnt"] for r in inbox_stats_raw} if inbox_stats_raw else {}
        return render_template(
            "web/inbox.html",
            rows=rows,
            counts=counts,
            current_status=status_filter,
        )

    @app.route("/settings")
    @login_required
    def settings():
        try:
            cfg = load_all()
        except Exception:
            cfg = {}
        return render_template("web/settings.html", config=cfg)

    return app


def _safe_query(engine: Engine, sql: str, params: dict[str, Any] | None = None,
                default: Any = None) -> Any:
    try:
        return execute(engine, sql, params or {})
    except Exception as err:
        logger.warning("Web-UI Query fehlgeschlagen: %s", err)
        return default


def _redirect(path: str):
    from flask import redirect as r
    return r(path)


_LATEST_NW_SQL = (
    "SELECT snapshot_date, bank_total, securities_total, "
    "real_estate_equity, net_worth FROM networth_history "
    "ORDER BY snapshot_date DESC LIMIT 1"
)

_NW_HISTORY_SQL = (
    "SELECT snapshot_date, net_worth, bank_total, securities_total, "
    "real_estate_equity FROM networth_history WHERE snapshot_date >= :s "
    "ORDER BY snapshot_date"
)

_RECENT_TX_SQL = (
    "SELECT transaction_id, account_id, booking_date, amount, "
    "description, counterparty_name FROM transactions "
    "ORDER BY booking_date DESC, id DESC LIMIT :l"
)

_EVENTS_SQL = (
    "SELECT event_type, entity_id, period, details, detected_at "
    "FROM events ORDER BY detected_at DESC LIMIT :l"
)

_INBOX_SQL = "SELECT status, COUNT(*) as cnt FROM receipts GROUP BY status"

_BALANCES_SQL = (
    "SELECT account_id, balance, currency, recorded_at "
    "FROM balances b WHERE recorded_at = (SELECT MAX(recorded_at) "
    "FROM balances b2 WHERE b2.account_id = b.account_id) "
    "ORDER BY account_id"
)


def serve(engine: Engine, host: str = "0.0.0.0", port: int = 8080) -> None:
    app = _create_app(engine)
    logger = __import__("logging").getLogger("werkzeug")
    logger.setLevel(__import__("logging").WARNING)
    app.run(host=host, port=port, debug=False, use_reloader=False)
