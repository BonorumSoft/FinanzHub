"""CSV-Exporter: schreibt Report-CSVs in ``OUTPUT_DIR``."""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from app.core.portfolio_engine import NetWorth
from app.logger import get_logger

logger = get_logger(__name__)


def _ensure_dir(path: str | os.PathLike[str]) -> Path:
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def export_networth(nw: NetWorth, output_dir: str | os.PathLike[str]) -> Path:
    target = _ensure_dir(output_dir) / f"networth_{date.today().isoformat()}.csv"
    with target.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["section", "key", "value"])
        w.writerow(["summary", "bank_total", f"{nw.bank_total:.2f}"])
        w.writerow(["summary", "securities_total", f"{nw.securities_total:.2f}"])
        w.writerow(["summary", "real_estate_equity", f"{nw.real_estate_equity:.2f}"])
        w.writerow(["summary", "net_worth", f"{nw.net_worth:.2f}"])
        w.writerow([])
        w.writerow(["position", "isin", "name", "quantity", "current_price", "value", "pnl", "pnl_percent"])
        for p in nw.positions:
            w.writerow(
                [
                    "position",
                    p.isin,
                    p.name or "",
                    f"{p.quantity:.4f}",
                    f"{p.current_price:.4f}",
                    f"{p.value:.2f}",
                    f"{p.pnl:.2f}",
                    f"{p.pnl_percent:.2f}",
                ]
            )
    logger.info("CSV geschrieben: %s", target)
    return target


def export_transactions(rows: Iterable[dict[str, Any]], output_dir: str | os.PathLike[str]) -> Path:
    rows = list(rows)
    target = _ensure_dir(output_dir) / f"transactions_{date.today().isoformat()}.csv"
    if not rows:
        target.write_text("", encoding="utf-8")
        return target
    fieldnames = list(rows[0].keys())
    with target.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    logger.info("CSV geschrieben: %s (%d Zeilen)", target, len(rows))
    return target


__all__ = ["export_networth", "export_transactions"]
