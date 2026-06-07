"""Lädt, validiert und normalisiert alle YAML-Konfigurationsdateien.

Dieses Modul ist die einzige Quelle der Wahrheit für Konfigurationsstrukturen.
Alle anderen Module erhalten fertig validierte Pydantic-Modelle als Parameter,
niemals als globale Modul-Variable.

Bei einem Validierungsfehler wird eine klare, parserfreundliche Fehlermeldung
auf stderr ausgegeben und das Programm mit Exit-Code 1 beendet.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.logger import get_logger

logger = get_logger(__name__)

DEFAULT_CONFIG_DIR: Final[str] = "./config"

# ---------------------------------------------------------------------------
# Kleine, wiederverwendbare Building-Blocks
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    """Gemeinsame Basiskonfiguration für alle Config-Modelle."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ---------------------------------------------------------------------------
# settings.yaml
# ---------------------------------------------------------------------------


class MatchingConfig(_StrictModel):
    standard_toleranz_euro: float = 1.00
    standard_toleranz_tage: int = 5
    warnung_ab_tag: int = 3


class VermoegenConfig(_StrictModel):
    schwellwert_liquiditaet_euro: float = 1500.0
    schwellwert_grosse_buchung_euro: float = 500.0
    schwellwert_substanz_prozent: float = 2.0
    schwellwert_substanz_tage: int = 30
    substance_consecutive_months: int = 3
    schwellwert_ruecklage_prozent: float = 60.0
    schwellwert_portfolio_verlust_prozent: float = 10.0


class AppSettings(_StrictModel):
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    vermoegen: VermoegenConfig = Field(default_factory=VermoegenConfig)
    zeitzone: str = "Europe/Berlin"
    export_dir: str = "data/export"
    abrechnungsjahr: int = Field(default_factory=lambda: date.today().year)


# ---------------------------------------------------------------------------
# inbox.yaml
# ---------------------------------------------------------------------------


class InboxIMAPConfig(_StrictModel):
    host: str = "imap.gmail.com"
    port: int = 993
    use_ssl: bool = True
    username: str = ""
    password: str = ""
    folder: str = "INBOX"
    poll_interval_seconds: int = 60
    mark_as_read: bool = True
    move_to_folder: str = "Belege/Verarbeitet"


class LMStudioExtractionConfig(_StrictModel):
    base_url: str = "http://localhost:1234/v1"
    model: str = "qwen2.5-vl-7b-instruct"
    timeout_seconds: int = 30


class OllamaExtractionConfig(_StrictModel):
    base_url: str = "http://localhost:11434"
    model: str = "llava:13b"
    timeout_seconds: int = 45


class OpenAIExtractionConfig(_StrictModel):
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 20


class AnthropicExtractionConfig(_StrictModel):
    api_key: str = ""
    model: str = "claude-haiku-4-5-20251001"
    timeout_seconds: int = 20


class ExtractionConfig(_StrictModel):
    provider: str = "local_lm_studio"
    local_lm_studio: LMStudioExtractionConfig = Field(default_factory=LMStudioExtractionConfig)
    ollama: OllamaExtractionConfig = Field(default_factory=OllamaExtractionConfig)
    openai: OpenAIExtractionConfig = Field(default_factory=OpenAIExtractionConfig)
    anthropic: AnthropicExtractionConfig = Field(default_factory=AnthropicExtractionConfig)
    fallback_provider: str = "anthropic"
    min_confidence_for_match: float = 0.75


class InboxMatchingConfig(_StrictModel):
    date_tolerance_days: int = 3
    amount_tolerance_eur: float = 0.50
    amount_tolerance_percent: float = 0.02
    lookback_days: int = 14


class InboxConfirmationConfig(_StrictModel):
    enabled: bool = True
    reply_to_sender: bool = True
    include_match_details: bool = True
    include_extracted_data: bool = True


class InboxConfig(_StrictModel):
    enabled: bool = False
    imap: InboxIMAPConfig = Field(default_factory=InboxIMAPConfig)
    allowed_senders: list[str] = Field(default_factory=list)
    accepted_mimetypes: list[str] = Field(
        default_factory=lambda: [
            "image/jpeg",
            "image/png",
            "image/heic",
            "image/heif",
            "image/webp",
            "application/pdf",
        ]
    )
    storage_path: str = "/app/output/receipts"
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    matching: InboxMatchingConfig = Field(default_factory=InboxMatchingConfig)
    confirmation: InboxConfirmationConfig = Field(default_factory=InboxConfirmationConfig)


# ---------------------------------------------------------------------------
# assets.yaml
# ---------------------------------------------------------------------------


class SecurityPosition(_StrictModel):
    """Eine Depot-Position. Akzeptiert legacy-Aliase via model_validator."""

    isin: str
    name: str | None = None
    ticker: str | None = None
    quantity: float
    purchase_price: float
    current_value: float | None = None
    value_growth: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "value" in data and "current_value" not in data:
                data["current_value"] = data.pop("value")
            if "growth" in data and "value_growth" not in data:
                data["value_growth"] = data.pop("growth")
        return data


class TenantConfig(_StrictModel):
    name: str
    unit_id: str | None = None
    wohnflaeche: float | None = None
    personen: int | None = None
    verbrauch_anteil: float | None = None
    iban: str | None = None
    keyword: str | None = None
    cold_rent_monthly: float = 0.0
    expected_by_day: int = 3


class LoanConfig(_StrictModel):
    loan_remaining: float
    interest_rate: float
    loan_payment_monthly: float
    fixed_interest_until: date | None = None


class OperatingCost(_StrictModel):
    """Periodische Betriebs-/Verwaltungskosten (monatlich, in EUR)."""

    name: str
    amount_monthly: float
    umlagefaehig: bool = True


class RealEstateAsset(_StrictModel):
    id: str | None = None
    name: str
    current_value: float
    purchase_price: float
    value_growth: float
    units: int = 1
    living_area: float | None = None
    rent_monthly: float
    rent_growth: float = 0.02
    operating_costs_monthly: float = 0.0
    maintenance_reserve_monthly: float = 0.0
    loan: LoanConfig | None = None
    tenants: list[TenantConfig] = Field(default_factory=list)
    operating_costs: list[OperatingCost] = Field(default_factory=list)
    build_year: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_aliases(cls, data: Any) -> Any:
        """Erlaubt `loan_remaining`, `interest_rate`, `loan_payment_monthly`
        auf Top-Level (Spec-Beispiel) sowie ältere `value`/`growth`-Aliase.
        """
        if isinstance(data, dict):
            if "value" in data and "current_value" not in data:
                data["current_value"] = data.pop("value")
            if "growth" in data and "value_growth" not in data:
                data["value_growth"] = data.pop("growth")
            nested_loan_keys = {"loan_remaining", "interest_rate", "loan_payment_monthly"}
            if nested_loan_keys & set(data.keys()) and "loan" not in data:
                data["loan"] = {k: data.pop(k) for k in nested_loan_keys if k in data}
        return data

    def loan_balance(self) -> float:
        return self.loan.loan_remaining if self.loan else 0.0


class AssetsConfig(_StrictModel):
    securities: list[SecurityPosition] = Field(default_factory=list)
    real_estate: list[RealEstateAsset] = Field(default_factory=list)
    bank_accounts: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict) and "immobilien" in data and "real_estate" not in data:
            data["real_estate"] = data.pop("immobilien")
        return data


# ---------------------------------------------------------------------------
# banks.yaml
# ---------------------------------------------------------------------------


class BankAdapterConfig(_StrictModel):
    name: str
    provider: str
    enabled: bool = True
    options: dict[str, Any] = Field(default_factory=dict)


class BanksConfig(_StrictModel):
    adapters: list[BankAdapterConfig] = Field(default_factory=list)
    active_adapter: str | None = None


# ---------------------------------------------------------------------------
# forecast.yaml
# ---------------------------------------------------------------------------


class ForecastConfig(_StrictModel):
    market_return: float = 0.07
    inflation: float = 0.02
    withdrawal_rate: float = 0.04
    retirement_age: int = 65
    current_age: int
    safety_buffer_years: int = 0

    @model_validator(mode="before")
    @classmethod
    def _ensure_current_age(cls, data: Any) -> Any:
        if isinstance(data, dict) and "current_age" not in data:
            from datetime import date

            today = date.today()
            data["current_age"] = today.year - 1990  # sinnvoller Default falls fehlend
        return data


# ---------------------------------------------------------------------------
# mail.yaml
# ---------------------------------------------------------------------------


class MailConfig(_StrictModel):
    host: str = "localhost"
    port: int = 587
    username: str = ""
    password: str = ""
    from_address: str = "finanzhub@localhost"
    test_recipient: str = ""
    test_mode: bool = False
    use_tls: bool = True
    timeout: int = 30


# ---------------------------------------------------------------------------
# notifications.yaml
# ---------------------------------------------------------------------------


class NotificationRule(_StrictModel):
    id: str
    description: str = ""
    schedule: str  # "daily", "monthly", "quarterly", "manual", cron-Ausdruck
    hour: int = 6
    minute: int = 0
    day_of_month: int = 1
    recipients: list[str] = Field(default_factory=list)
    enabled: bool = True
    template: str  # Verweist auf Jinja2-Template
    min_severity: str = "info"  # "info" | "warning" | "critical"


class NotificationsConfig(_StrictModel):
    rules: list[NotificationRule] = Field(default_factory=list)

    def get(self, notification_id: str) -> NotificationRule | None:
        for rule in self.rules:
            if rule.id == notification_id:
                return rule
        return None


# ---------------------------------------------------------------------------
# income.yaml
# ---------------------------------------------------------------------------


class ExpectedIncome(_StrictModel):
    name: str
    amount_min: float
    amount_max: float | None = None
    expected_by_day: int = 25
    keywords: list[str] = Field(default_factory=list)
    counterparty_iban: str | None = None


class IncomeConfig(_StrictModel):
    expected_income: list[ExpectedIncome] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# immobilien.yaml (legacy-Alias, fällt auf AssetsConfig zurück)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Loader-Funktionen
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def _format_validation_error(err: ValidationError, source: str) -> str:
    parts = [f"Konfigurationsfehler in {source}:"]
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"])
        msg = e["msg"]
        parts.append(f"  - Feld '{loc}': {msg}")
    return "\n".join(parts)


def _validate(model_cls: type[_StrictModel], data: dict[str, Any], source: str) -> _StrictModel:
    try:
        return model_cls.model_validate(data)
    except ValidationError as err:
        sys.stderr.write(_format_validation_error(err, source) + "\n")
        logger.error("Validierung von %s fehlgeschlagen", source)
        raise SystemExit(1) from err


def load_settings(config_dir: str | os.PathLike[str] | None = None) -> AppSettings:
    return _validate(AppSettings, _read_yaml(Path(config_dir or DEFAULT_CONFIG_DIR) / "settings.yaml"), "settings.yaml")


def load_assets(config_dir: str | os.PathLike[str] | None = None) -> AssetsConfig:
    return _validate(
        AssetsConfig,
        _read_yaml(Path(config_dir or DEFAULT_CONFIG_DIR) / "assets.yaml"),
        "assets.yaml",
    )


def load_banks(config_dir: str | os.PathLike[str] | None = None) -> BanksConfig:
    return _validate(
        BanksConfig,
        _read_yaml(Path(config_dir or DEFAULT_CONFIG_DIR) / "banks.yaml"),
        "banks.yaml",
    )


def load_forecast(config_dir: str | os.PathLike[str] | None = None) -> ForecastConfig:
    return _validate(
        ForecastConfig,
        _read_yaml(Path(config_dir or DEFAULT_CONFIG_DIR) / "forecast.yaml"),
        "forecast.yaml",
    )


def load_mail(config_dir: str | os.PathLike[str] | None = None) -> MailConfig:
    return _validate(
        MailConfig,
        _read_yaml(Path(config_dir or DEFAULT_CONFIG_DIR) / "mail.yaml"),
        "mail.yaml",
    )


def load_notifications(config_dir: str | os.PathLike[str] | None = None) -> NotificationsConfig:
    return _validate(
        NotificationsConfig,
        _read_yaml(Path(config_dir or DEFAULT_CONFIG_DIR) / "notifications.yaml"),
        "notifications.yaml",
    )


def load_income(config_dir: str | os.PathLike[str] | None = None) -> IncomeConfig:
    return _validate(
        IncomeConfig,
        _read_yaml(Path(config_dir or DEFAULT_CONFIG_DIR) / "income.yaml"),
        "income.yaml",
    )


def load_inbox(config_dir: str | os.PathLike[str] | None = None) -> InboxConfig:
    data = _read_yaml(Path(config_dir or DEFAULT_CONFIG_DIR) / "inbox.yaml")
    if "inbox" in data:
        data = data["inbox"]
    return _validate(InboxConfig, data, "inbox.yaml")


def load_all(config_dir: str | os.PathLike[str] | None = None) -> dict[str, BaseModel]:
    """Lädt alle Konfigurationen in einem Rutsch."""
    base = Path(config_dir or os.environ.get("CONFIG_DIR", DEFAULT_CONFIG_DIR))
    return {
        "settings": load_settings(base),
        "assets": load_assets(base),
        "banks": load_banks(base),
        "forecast": load_forecast(base),
        "mail": load_mail(base),
        "notifications": load_notifications(base),
        "income": load_income(base),
        "inbox": load_inbox(base),
    }


__all__ = [
    "AnthropicExtractionConfig",
    "AppSettings",
    "ExtractionConfig",
    "InboxConfig",
    "InboxConfirmationConfig",
    "InboxIMAPConfig",
    "InboxMatchingConfig",
    "LMStudioExtractionConfig",
    "OllamaExtractionConfig",
    "OpenAIExtractionConfig",
    "AssetsConfig",
    "BankAdapterConfig",
    "BanksConfig",
    "ExpectedIncome",
    "ForecastConfig",
    "IncomeConfig",
    "LoanConfig",
    "MailConfig",
    "MatchingConfig",
    "NotificationRule",
    "NotificationsConfig",
    "OperatingCost",
    "RealEstateAsset",
    "SecurityPosition",
    "TenantConfig",
    "VermoegenConfig",
    "load_all",
    "load_assets",
    "load_banks",
    "load_forecast",
    "load_income",
    "load_mail",
    "load_notifications",
    "load_settings",
]
