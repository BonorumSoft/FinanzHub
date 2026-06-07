from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, render_template, request, session
from sqlalchemy.engine import Engine

from app.config_loader import load_all
from app.data.db import execute
from app.web.auth import do_login, do_logout, login_required

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

        row = _latest_networth(engine)
        recent = _recent_transactions(engine, 10)
        nw_history = _networth_history(engine, 90)
        events = _recent_events(engine, 5)
        inbox_stats = _inbox_status(engine)
        balances = _account_balances(engine)

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
        rows = execute(
            engine,
            "SELECT transaction_id, account_id, booking_date, amount, "
            "description, counterparty_name, counterparty_iban, category "
            "FROM transactions WHERE booking_date >= :s "
            "ORDER BY booking_date DESC, id DESC LIMIT 200",
            {"s": since},
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
        sql = (
            "SELECT id, source_email, source_subject, received_at, "
            "original_filename, extracted_date, extracted_amount, "
            "extracted_merchant, status, match_confidence, steuerrelevant "
            "FROM receipts"
        )
        params: dict[str, Any] = {}
        if status_filter:
            sql += " WHERE status = :s"
            params["s"] = status_filter
        sql += " ORDER BY received_at DESC LIMIT 100"
        rows = execute(engine, sql, params) if engine else []
        counts = _inbox_status(engine) if engine else {}
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


def _redirect(path: str):
    from flask import redirect as r
    return r(path)


def _latest_networth(engine: Engine) -> dict[str, Any] | None:
    rows = execute(
        engine,
        "SELECT snapshot_date, bank_total, securities_total, "
        "real_estate_equity, net_worth FROM networth_history "
        "ORDER BY snapshot_date DESC LIMIT 1",
    )
    return rows[0] if rows else None


def _networth_history(engine: Engine, days: int) -> list[dict[str, Any]]:
    since = (date.today() - timedelta(days=days)).isoformat()
    return execute(
        engine,
        "SELECT snapshot_date, net_worth, bank_total, securities_total, real_estate_equity "
        "FROM networth_history WHERE snapshot_date >= :s ORDER BY snapshot_date",
        {"s": since},
    )


def _recent_transactions(engine: Engine, limit: int) -> list[dict[str, Any]]:
    return execute(
        engine,
        "SELECT transaction_id, account_id, booking_date, amount, "
        "description, counterparty_name FROM transactions "
        "ORDER BY booking_date DESC, id DESC LIMIT :l",
        {"l": limit},
    )


def _recent_events(engine: Engine, limit: int) -> list[dict[str, Any]]:
    return execute(
        engine,
        "SELECT event_type, entity_id, period, details, detected_at, severity "
        "FROM events ORDER BY detected_at DESC LIMIT :l",
        {"l": limit},
    )


def _inbox_status(engine: Engine) -> dict[str, int]:
    rows = execute(
        engine,
        "SELECT status, COUNT(*) as cnt FROM receipts GROUP BY status",
    )
    counts: dict[str, int] = {}
    for row in rows or []:
        counts[row["status"]] = row["cnt"]
    return counts


def _account_balances(engine: Engine) -> list[dict[str, Any]]:
    return execute(
        engine,
        "SELECT account_id, balance, currency, recorded_at "
        "FROM balances b WHERE recorded_at = (SELECT MAX(recorded_at) "
        "FROM balances b2 WHERE b2.account_id = b.account_id) "
        "ORDER BY account_id",
    )


def serve(engine: Engine, host: str = "0.0.0.0", port: int = 8080) -> None:
    app = _create_app(engine)
    logger = __import__("logging").getLogger("werkzeug")
    logger.setLevel(__import__("logging").WARNING)
    app.run(host=host, port=port, debug=False, use_reloader=False)
