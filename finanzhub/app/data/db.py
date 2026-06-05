"""Datenbankschicht (SQLAlchemy Core, kein ORM).

Stellt eine einheitliche Schnittstelle für Verbindungen, Migrationen und
atomare Operationen bereit. Bewusst ORM-frei: alle Module außerhalb von
``data/`` arbeiten nur mit reinen Dataclasses.

Diese Schicht kennt keine Geschäftslogik. Sie ist außerdem der einzige Ort
im Projekt, an dem ``sqlalchemy`` direkt verwendet wird.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DB_URL = "postgresql://finanzhub:finanzhub@localhost:5432/finanzhub"
DEFAULT_MIGRATIONS_DIR = "migrations"

# ---------------------------------------------------------------------------
# Engine-Management
# ---------------------------------------------------------------------------


def build_engine(database_url: str | None = None) -> Engine:
    """Erzeugt eine SQLAlchemy-Engine.

    SQLite benötigt spezielle Args (check_same_thread=False) und ignoriert
    pool_size/Max_overflow.
    """
    url = database_url or os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    connect_args: dict[str, Any] = {}
    engine_kwargs: dict[str, Any] = {"future": True, "echo": False}

    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        engine_kwargs["connect_args"] = connect_args
    else:
        engine_kwargs.update({"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10})
    return create_engine(url, **engine_kwargs)


def wait_for_db(engine: Engine, attempts: int = 15, delay: float = 3.0) -> None:
    """Pollt die DB bis sie antwortet, dann gibt sie zurück oder bricht ab."""
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Datenbank erreichbar (Versuch %d/%d)", attempt, attempts)
            return
        except OperationalError as err:
            last_err = err
            logger.warning("DB nicht erreichbar (%d/%d): %s", attempt, attempts, err)
            time.sleep(delay)
    raise RuntimeError(f"Datenbank nicht erreichbar nach {attempts} Versuchen: {last_err}")


@contextmanager
def transaction(engine: Engine) -> Iterator[Any]:
    """Context-Manager: liefert eine Transaktion mit automatischem Commit/Rollback."""
    with engine.begin() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Migrationen
# ---------------------------------------------------------------------------


_SQLITE_REPLACEMENTS: Sequence[tuple[re.Pattern[str], str]] = (
    (re.compile(r"\bSERIAL\s+PRIMARY\s+KEY\b", re.IGNORECASE), "INTEGER PRIMARY KEY AUTOINCREMENT"),
    (re.compile(r"\bSERIAL\b", re.IGNORECASE), "INTEGER"),
    (re.compile(r"\bTIMESTAMPTZ\b", re.IGNORECASE), "TIMESTAMP"),
    (re.compile(r"\bJSONB\b", re.IGNORECASE), "TEXT"),
    (re.compile(r"\bNUMERIC\(\s*(\d+)\s*,\s*(\d+)\s*\)", re.IGNORECASE), r"NUMERIC(\1,\2)"),
    (re.compile(r"\bBOOLEAN\b", re.IGNORECASE), "BOOLEAN"),
    (re.compile(r"\bTRUE\b"), "1"),
    (re.compile(r"\bFALSE\b"), "0"),
    (re.compile(r"\bNOW\(\s*\)", re.IGNORECASE), "CURRENT_TIMESTAMP"),
)


def _adapt_sql_for_sqlite(sql: str) -> str:
    """Ersetzt Postgres-spezifische Konstrukte für SQLite-Tests."""
    for pattern, replacement in _SQLITE_REPLACEMENTS:
        sql = pattern.sub(replacement, sql)
    return sql


def _split_statements(sql: str) -> list[str]:
    """Zerlegt eine SQL-Datei in einzelne Statements (naiv, aber ausreichend)."""
    cleaned_lines = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    joined = "\n".join(cleaned_lines)
    return [stmt.strip() for stmt in joined.split(";") if stmt.strip()]


def _ensure_schema_migrations(engine: Engine) -> None:
    ddl = text(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    is_sqlite = engine.dialect.name == "sqlite"
    if is_sqlite:
        ddl = text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
    with engine.begin() as conn:
        conn.execute(ddl)


def _applied_versions(engine: Engine) -> set[str]:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {row[0] for row in rows}


def _record_version(engine: Engine, version: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:v)"),
            {"v": version},
        )


def apply_migrations(engine: Engine, migrations_dir: str | os.PathLike[str] = DEFAULT_MIGRATIONS_DIR) -> list[str]:
    """Wendet alle *.sql-Dateien aus ``migrations_dir`` lexikografisch an.

    Bereits angewendete Migrationen (in ``schema_migrations``) werden übersprungen.
    Gibt die Liste der neu angewendeten Versionsnummern zurück.
    """
    _ensure_schema_migrations(engine)
    applied = _applied_versions(engine)
    mig_path = Path(migrations_dir)
    if not mig_path.exists():
        logger.warning("Migrations-Verzeichnis %s existiert nicht", mig_path)
        return []

    is_sqlite = engine.dialect.name == "sqlite"
    new_versions: list[str] = []

    for sql_file in sorted(mig_path.glob("*.sql")):
        version = sql_file.stem
        if version in applied:
            logger.debug("Migration %s bereits angewendet, überspringe", version)
            continue

        logger.info("Wende Migration %s an", version)
        sql = sql_file.read_text(encoding="utf-8")
        statements = _split_statements(sql)
        with engine.begin() as conn:
            for stmt in statements:
                if is_sqlite:
                    stmt = _adapt_sql_for_sqlite(stmt)
                conn.execute(text(stmt))
        _record_version(engine, version)
        new_versions.append(version)

    if new_versions:
        logger.info("%d neue Migration(en) angewendet: %s", len(new_versions), new_versions)
    return new_versions


# ---------------------------------------------------------------------------
# High-level Dataclass für Connection-Result
# ---------------------------------------------------------------------------


@dataclass
class CollectionResult:
    """Ergebnis eines Bank-Sammellaufs."""

    success: bool
    transactions_imported: int
    balances_imported: int
    fallback_used: bool = False
    error_message: str | None = None
    adapter_name: str | None = None
    period_start: Any | None = None
    period_end: Any | None = None


# ---------------------------------------------------------------------------
# Hilfsfunktionen für andere data/-Module
# ---------------------------------------------------------------------------


def execute(engine: Engine, stmt: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Führt ein SELECT aus und liefert die Zeilen als Liste von Dicts."""
    with engine.begin() as conn:
        result = conn.execute(text(stmt), params or {})
        return [dict(row._mapping) for row in result]


def execute_write(engine: Engine, stmt: str, params: dict[str, Any] | None = None) -> int:
    """Führt ein INSERT/UPDATE/DELETE aus und liefert die Rowcount."""
    with engine.begin() as conn:
        result = conn.execute(text(stmt), params or {})
        return result.rowcount or 0


def insert_or_ignore(engine: Engine, table: str, conflict_keys: Sequence[str], values: dict[str, Any]) -> bool:
    """Führt INSERT ... ON CONFLICT DO NOTHING aus. Liefert True wenn eingefügt."""
    cols = ", ".join(values.keys())
    placeholders = ", ".join(f":{k}" for k in values)
    conflict = ", ".join(conflict_keys)
    stmt = (
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict}) DO NOTHING"
    )
    with engine.begin() as conn:
        result = conn.execute(text(stmt), values)
        return (result.rowcount or 0) > 0


__all__ = [
    "CollectionResult",
    "DEFAULT_DB_URL",
    "DEFAULT_MIGRATIONS_DIR",
    "apply_migrations",
    "build_engine",
    "execute",
    "execute_write",
    "insert_or_ignore",
    "transaction",
    "wait_for_db",
]


def _safe_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Hilfs-Wrapper für ``try/except`` an Aufrufstellen — vermeidet leere excepts."""
    try:
        return fn(*args, **kwargs)
    except SQLAlchemyError as err:
        logger.error("SQL-Fehler in %s: %s", fn.__name__, err)
        raise
