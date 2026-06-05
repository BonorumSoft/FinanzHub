"""Click-basiertes CLI für FinanzHub.

Wichtige Kommandos:

- ``finanzhub init`` – validiert Config + DB und druckt eine Zusammenfassung
- ``finanzhub pull`` – Bank-Daten importieren
- ``finanzhub pull-all`` – Pull + Portfolio + Events + Notify
- ``finanzhub wealth`` – Nettovermögen anzeigen
- ``finanzhub rent-check YYYY-MM`` – Mietabgleich
- ``finanzhub forecast`` – Rentenprognose
- ``finanzhub events detect`` – Events erkennen
- ``finanzhub notify test <id>`` – Test-Mail
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

import click

from app.alerts.payment_monitor import check_rent
from app.banking.base import BankBalance
from app.config_loader import (
    load_all,
    load_assets,
    load_banks,
    load_forecast,
    load_income,
    load_settings,
)
from app.core.cashflow_engine import monthly_cashflow
from app.core.forecast_engine import project
from app.core.portfolio_engine import calculate as calc_networth
from app.core.rentability_engine import reports as calc_rentability
from app.data.bank_collector import BankCollector
from app.data.db import build_engine, wait_for_db
from app.data.event_detector import EventDetector
from app.data.price_service import PriceService
from app.logger import configure_logging, get_logger
from app.output.report_generator import (
    forecast_table,
    positions_table,
    rent_matrix_table,
    rentability_table,
    wealth_table,
)

logger = get_logger(__name__)


def _engine_from_env() -> Any:
    url = click.get_current_context().obj or _resolve_engine_url()
    return build_engine(url)


def _resolve_engine_url() -> str:
    import os

    return os.environ.get("DATABASE_URL", "postgresql://finanzhub:finanzhub@localhost:5432/finanzhub")


@click.group(help="FinanzHub – Self-hosted Finanzmanagementsystem")
@click.option(
    "--config-dir",
    default=None,
    envvar="CONFIG_DIR",
    help="Konfigurationsverzeichnis (default: ./config)",
)
@click.option(
    "--log-level",
    default=None,
    envvar="LOG_LEVEL",
    help="Log-Level (DEBUG, INFO, WARNING, ERROR)",
)
@click.pass_context
def main(ctx: click.Context, config_dir: str | None, log_level: str | None) -> None:
    """Initialisiert Logging und Konfiguration."""
    ctx.ensure_object(dict)
    configure_logging(level=log_level or "INFO")
    ctx.obj["config_dir"] = config_dir or "./config"
    ctx.obj["engine_url"] = _resolve_engine_url()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@main.command(help="Konfiguration und Datenbank initial prüfen.")
@click.pass_context
def init(ctx: click.Context) -> None:
    """Validiert die YAML-Konfiguration und testet die DB-Verbindung."""
    from app.data.db import apply_migrations

    config_dir = ctx.obj["config_dir"]
    try:
        cfgs = load_all(config_dir)
    except SystemExit:
        click.echo("Konfigurationsfehler – siehe Meldung oben", err=True)
        sys.exit(1)

    click.echo(f"[OK] Konfiguration geladen aus {config_dir}/")
    click.echo("      - settings: matching/vermoegen Schwellwerte gesetzt")
    click.echo(f"      - assets: {len(cfgs['assets'].securities)} Wertpapiere, {len(cfgs['assets'].real_estate)} Immobilien")
    click.echo(f"      - banks: {len(cfgs['banks'].adapters)} Adapter konfiguriert")
    click.echo(f"      - notifications: {len(cfgs['notifications'].rules)} Regeln")

    engine = build_engine(ctx.obj["engine_url"])
    try:
        wait_for_db(engine, attempts=2, delay=1.0)
        click.echo("[OK] Datenbank erreichbar")
    except RuntimeError as err:
        click.echo(f"[FEHLER] Datenbank nicht erreichbar: {err}", err=True)
        sys.exit(1)

    try:
        applied = apply_migrations(engine)
        click.echo(f"[OK] Migrationen: {len(applied)} neue angewendet")
    except Exception as err:
        click.echo(f"[FEHLER] Migrationen fehlgeschlagen: {err}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------


@main.command(help="Bank-Daten importieren (idempotent).")
@click.option("--since", default=None, help="Start-Datum (YYYY-MM-DD)")
@click.pass_context
def pull(ctx: click.Context, since: str | None) -> None:
    """Bank-Import: einzelner Sammellauf."""
    config_dir = ctx.obj["config_dir"]
    settings = load_settings(config_dir)
    banks_cfg = load_banks(config_dir)
    engine = build_engine(ctx.obj["engine_url"])
    collector = BankCollector(engine, banks_cfg)
    since_date = date.fromisoformat(since) if since else None
    result = collector.collect_and_persist(since=since_date)
    if not result.success:
        click.echo(
            f"[WARN] Fallback aktiv: {result.error_message or 'unbekannt'}", err=True
        )
    click.echo(
        f"Adapter={result.adapter_name} | Transaktionen={result.transactions_imported} | "
        f"Salden={result.balances_imported} | Fallback={result.fallback_used}"
    )


# ---------------------------------------------------------------------------
# pull-all
# ---------------------------------------------------------------------------


@main.command(help="Vollständiger Zyklus: Pull → Portfolio → Events → Notify.")
@click.option("--skip-prices", is_flag=True, help="Marktdaten überspringen (für Tests)")
@click.pass_context
def pull_all(ctx: click.Context, skip_prices: bool) -> None:
    """Ein-Klick-Vollzyklus."""
    config_dir = ctx.obj["config_dir"]
    settings = load_settings(config_dir)
    banks_cfg = load_banks(config_dir)
    assets = load_assets(config_dir)
    engine = build_engine(ctx.obj["engine_url"])

    # 1. Pull
    collector = BankCollector(engine, banks_cfg)
    res = collector.collect_and_persist()
    click.echo(f"[pull] {res.transactions_imported} Buchungen, Fallback={res.fallback_used}")

    # 2. Prices
    if not skip_prices:
        try:
            price_service = PriceService(engine=engine)
            price_service.enrich_assets(assets)
        except Exception as err:
            click.echo(f"[warn] Marktdaten fehlgeschlagen: {err}", err=True)

    # 3. NetWorth + Snapshot
    balances = _load_balances(engine)
    valuations = []
    if not skip_prices:
        valuations = _load_valuation_snapshot(assets, engine)
    nw = calc_networth(assets, balances, valuations)
    _save_networth_snapshot(engine, nw)
    click.echo(f"[wealth] Nettovermögen: {nw.net_worth:,.2f} €")

    # 4. Events
    detector = EventDetector(engine, assets, load_income(config_dir), settings)
    events = detector.detect_all()
    click.echo(f"[events] {len(events)} neue Events")

    # 5. Notify
    from app.config_loader import load_mail, load_notifications
    from app.notifications.engine import NotificationEngine
    from app.output.mail_service import MailService

    mail_cfg = load_mail(config_dir)
    notif_cfg = load_notifications(config_dir)
    mail = MailService(mail_cfg)
    engine_notif = NotificationEngine(engine, notif_cfg, mail, mail_cfg)
    results = engine_notif.run_due()
    click.echo(f"[notify] {len(results)} Benachrichtigungen versendet")


# ---------------------------------------------------------------------------
# wealth
# ---------------------------------------------------------------------------


@main.command(help="Aktuelles Nettovermögen anzeigen.")
@click.option("--skip-prices", is_flag=True, help="Marktdaten überspringen")
@click.option("--export-csv", is_flag=True, help="Zusätzlich CSV schreiben")
@click.pass_context
def wealth(ctx: click.Context, skip_prices: bool, export_csv: bool) -> None:
    """Berechnet und zeigt das Nettovermögen."""
    config_dir = ctx.obj["config_dir"]
    settings = load_settings(config_dir)
    assets = load_assets(config_dir)
    engine = build_engine(ctx.obj["engine_url"])

    balances = _load_balances(engine)
    valuations: list[dict[str, Any]] = []
    if not skip_prices:
        price_service = PriceService(engine=engine)
        valuations = price_service.enrich_assets(assets)

    nw = calc_networth(assets, balances, valuations)
    click.echo(wealth_table(nw))
    if nw.positions:
        click.echo("\nDepot-Positionen:")
        click.echo(positions_table(nw))
    if export_csv:
        from app.output.csv_exporter import export_networth

        path = export_networth(nw, settings.export_dir)
        click.echo(f"\nCSV: {path}")


# ---------------------------------------------------------------------------
# rent-check
# ---------------------------------------------------------------------------


@main.command(help="Mietabgleich für den angegebenen Monat.")
@click.argument("period", metavar="YYYY-MM")
@click.pass_context
def rent_check(ctx: click.Context, period: str) -> None:
    """Mietabgleich."""
    config_dir = ctx.obj["config_dir"]
    settings = load_settings(config_dir)
    assets = load_assets(config_dir)
    engine = build_engine(ctx.obj["engine_url"])

    period_date = date.fromisoformat(period + "-01")
    results = check_rent(engine, assets, period_date, settings.matching)
    click.echo(rent_matrix_table(results, period))


# ---------------------------------------------------------------------------
# forecast
# ---------------------------------------------------------------------------


@main.command(help="Vermögensprognose bis Renteneintritt.")
@click.option("--years", type=int, default=None, help="Manuelle Override-Anzahl Jahre")
@click.pass_context
def forecast(ctx: click.Context, years: int | None) -> None:
    """Prognose."""
    config_dir = ctx.obj["config_dir"]
    assets = load_assets(config_dir)
    fc = load_forecast(config_dir)
    settings = load_settings(config_dir)
    engine = build_engine(ctx.obj["engine_url"])

    balances = _load_balances(engine)
    securities_total = 0.0
    if fc.current_age:
        try:
            price_service = PriceService(engine=engine)
            valuations = price_service.enrich_assets(assets)
            securities_total = sum(v["value"] for v in valuations)
        except Exception as err:
            click.echo(f"[warn] Marktdaten fehlgeschlagen: {err}", err=True)
    starting_liquid = securities_total + sum(b.balance for b in balances)
    fc.current_age = fc.current_age  # type: ignore[assignment]
    result = project(fc, starting_liquid, assets.real_estate)
    click.echo(forecast_table(result))


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


@main.group(help="Event-Operationen.")
def events() -> None:
    pass


@events.command("detect")
@click.option("--days", type=int, default=90, help="Lookback in Tagen")
@click.pass_context
def events_detect(ctx: click.Context, days: int) -> None:
    """Erkennt alle Events und gibt sie aus."""
    config_dir = ctx.obj["config_dir"]
    settings = load_settings(config_dir)
    assets = load_assets(config_dir)
    income = load_income(config_dir)
    engine = build_engine(ctx.obj["engine_url"])
    detector = EventDetector(engine, assets, income, settings)
    detected = detector.detect_all()
    if not detected:
        click.echo("(keine neuen Events)")
        return
    for e in detected:
        click.echo(
            f"[{e.severity.upper():>8}] {e.event_type:<32} {e.entity_id:<20} {e.period}"
        )


@events.command("list")
@click.pass_context
def events_list(ctx: click.Context) -> None:
    """Listet alle gespeicherten Events."""
    from app.data.db import execute

    engine = build_engine(ctx.obj["engine_url"])
    rows = execute(
        engine,
        "SELECT event_type, entity_id, period, severity_value, detected_at, notified "
        "FROM ("
        "  SELECT event_type, entity_id, period, details, detected_at, notified FROM events"
        ") e "
        "ORDER BY detected_at DESC LIMIT 100",
    )
    for r in rows:
        click.echo(
            f"{r['detected_at']} | {r['event_type']:<32} | {r['entity_id']:<20} | {r['period']}"
        )


# ---------------------------------------------------------------------------
# notify
# ---------------------------------------------------------------------------


@main.group(help="Notification-Operationen.")
def notify() -> None:
    pass


@notify.command("test")
@click.argument("notification_id")
@click.pass_context
def notify_test(ctx: click.Context, notification_id: str) -> None:
    """Versendet eine Test-Mail sofort."""
    config_dir = ctx.obj["config_dir"]
    from app.config_loader import load_mail, load_notifications
    from app.notifications.engine import NotificationEngine
    from app.output.mail_service import MailService

    notif_cfg = load_notifications(config_dir)
    engine = build_engine(ctx.obj["engine_url"])
    mail = MailService(load_mail(config_dir))
    ne = NotificationEngine(engine, notif_cfg, mail, load_mail(config_dir))
    result = ne.send_test(notification_id)
    if result.success:
        click.echo(f"[OK] Mail an {result.recipients} versendet")
    else:
        click.echo(f"[FEHLER] {result.error_message}", err=True)
        sys.exit(1)


@notify.command("run")
@click.pass_context
def notify_run(ctx: click.Context) -> None:
    """Sendet alle fälligen Benachrichtigungen."""
    config_dir = ctx.obj["config_dir"]
    from app.config_loader import load_mail, load_notifications
    from app.notifications.engine import NotificationEngine
    from app.output.mail_service import MailService

    engine = build_engine(ctx.obj["engine_url"])
    mail_cfg = load_mail(config_dir)
    notif_cfg = load_notifications(config_dir)
    ne = NotificationEngine(engine, notif_cfg, MailService(mail_cfg), mail_cfg)
    results = ne.run_due()
    click.echo(f"{len(results)} Benachrichtigungen verarbeitet")


# ---------------------------------------------------------------------------
# nk
# ---------------------------------------------------------------------------


@main.command(help="NK-Abrechnung für ein Objekt im aktuellen Jahr.")
@click.option("--asset", default=None, help="Asset-Name (default: alle)")
@click.option("--year", type=int, default=None, help="Abrechnungsjahr")
@click.pass_context
def nk(ctx: click.Context, asset: str | None, year: int | None) -> None:
    """Berechnet die NK-Abrechnung."""
    from app.core.nk_calculator import distribute

    config_dir = ctx.obj["config_dir"]
    assets = load_assets(config_dir)
    y = year or date.today().year
    selected = (
        [a for a in assets.real_estate if (a.id or a.name) == asset]
        if asset
        else assets.real_estate
    )
    if not selected:
        click.echo("Kein passendes Objekt gefunden", err=True)
        sys.exit(1)
    for a in selected:
        result = distribute(a, y)
        click.echo(f"\n=== {a.name} · {y} · {result.distribution_key.value} ===")
        for tenant, share in result.per_tenant.items():
            click.echo(f"  {tenant:<30} {share:>10,.2f} €")
        click.echo(f"  {'SUMME':<30} {sum(result.per_tenant.values()):>10,.2f} €")
        click.echo(
            f"  Umlagefähig ges.: {sum(result.umlagefaehig_per_tenant.values()):>10,.2f} €  "
            f"(Soll: {result.total_costs - result.nicht_umlagefaehig:.2f} €)"
        )


# ---------------------------------------------------------------------------
# rentability
# ---------------------------------------------------------------------------


@main.command(help="Rentabilitäts-Kennzahlen aller Objekte.")
@click.pass_context
def rentability(ctx: click.Context) -> None:
    """Berechnet und zeigt KPIs."""
    config_dir = ctx.obj["config_dir"]
    assets = load_assets(config_dir)
    reports = calc_rentability(assets.real_estate)
    click.echo(rentability_table(reports))


# ---------------------------------------------------------------------------
# cashflow
# ---------------------------------------------------------------------------


@main.command(help="Monatlicher Cashflow eines Objekts.")
@click.option("--asset", required=True, help="Asset-Name oder -ID")
@click.option("--months", default=12, type=int, help="Anzahl Monate")
@click.pass_context
def cashflow(ctx: click.Context, asset: str, months: int) -> None:
    """Cashflow-Tabelle."""
    from app.output.report_generator import cashflow_table

    config_dir = ctx.obj["config_dir"]
    assets = load_assets(config_dir)
    a = next((x for x in assets.real_estate if (x.id or x.name) == asset), None)
    if a is None:
        click.echo("Objekt nicht gefunden", err=True)
        sys.exit(1)
    flows = monthly_cashflow(a, months)
    click.echo(cashflow_table(flows))


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _load_balances(engine: Any) -> list[BankBalance]:
    from app.data.db import execute

    rows = execute(
        engine,
        "SELECT account_id, balance, currency, recorded_at "
        "FROM balances b "
        "WHERE recorded_at = (SELECT MAX(recorded_at) FROM balances b2 "
        "                       WHERE b2.account_id = b.account_id) "
        "ORDER BY account_id",
    )
    out: list[BankBalance] = []
    for r in rows:
        out.append(
            BankBalance(
                account_id=r["account_id"],
                account_name=r["account_id"],
                iban=None,
                balance=float(r["balance"]),
                currency=r.get("currency", "EUR"),
            )
        )
    return out


def _load_valuation_snapshot(assets: Any, engine: Any) -> list[dict[str, Any]]:
    """Lädt den letzten bekannten Wert pro ISIN aus dem Cache."""
    from app.data.db import execute

    rows = execute(
        engine,
        "SELECT isin, price_eur, recorded_at "
        "FROM price_history p "
        "WHERE recorded_at = (SELECT MAX(recorded_at) FROM price_history p2 "
        "                       WHERE p2.isin = p.isin) "
        "ORDER BY isin",
    )
    latest: dict[str, float] = {r["isin"]: float(r["price_eur"]) for r in rows}
    out: list[dict[str, Any]] = []
    for sec in assets.securities:
        price = latest.get(sec.isin)
        if price is None:
            continue
        out.append(
            {
                "isin": sec.isin,
                "name": sec.name,
                "quantity": sec.quantity,
                "purchase_price": sec.purchase_price,
                "current_price": price,
                "value": price * sec.quantity,
            }
        )
    return out


def _save_networth_snapshot(engine: Any, nw: Any) -> None:
    """Persistiert einen NetWorth-Snapshot in networth_history (idempotent je Datum)."""
    from app.data.db import insert_or_ignore

    row = {
        "snapshot_date": date.today().isoformat(),
        "bank_total": f"{nw.bank_total:.2f}",
        "securities_total": f"{nw.securities_total:.2f}",
        "real_estate_equity": f"{nw.real_estate_equity:.2f}",
        "net_worth": f"{nw.net_worth:.2f}",
        "net_worth_real": f"{nw.net_worth:.2f}",
    }
    try:
        insert_or_ignore(engine, "networth_history", ("snapshot_date",), row)
    except Exception as err:
        logger.warning("Konnte NetWorth-Snapshot nicht speichern: %s", err)


if __name__ == "__main__":
    main(obj={})
