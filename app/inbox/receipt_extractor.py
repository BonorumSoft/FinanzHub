"""KI-gestützte Beleg-Extraktion mit provider-agnostischem Interface.

Unterstützte Provider:
  - ``local_lm_studio`` (default, OpenAI-kompatibel, lokal)
  - ``ollama`` (lokal, eigener Endpunkt)
  - ``openai`` (gpt-4o-mini)
  - ``anthropic`` (claude-haiku)

Robustheit:
  - Konfigurierbarer Fallback-Provider
  - JSON-Parsing tolerant gegen Markdown-Codeblöcke
  - Validierung der KI-Antwort (Wertebereiche, Datumsformat)
  - Bei Totalversagen: leere :class:`ExtractedReceipt` mit ``confidence=0.0``
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

from app.config_loader import ExtractionConfig
from app.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------


@dataclass
class ExtractedReceipt:
    """Strukturiertes Ergebnis der KI-Extraktion."""

    date: str | None = None
    amount: float | None = None
    currency: str = "EUR"
    merchant: str | None = None
    category: str | None = None
    invoice_number: str | None = None
    is_invoice: bool = False
    is_payment_proof: bool = False
    tax_amount: float | None = None
    confidence: float = 0.0
    raw_response: dict = field(default_factory=dict)
    model: str | None = None

    def to_db_dict(self) -> dict[str, Any]:
        """Konvertiert in DB-kompatibles Dict (nullable Felder, Booleans als int)."""
        return {
            "extracted_date": _parse_iso(self.date),
            "extracted_amount": abs(self.amount) if self.amount is not None else None,
            "extracted_currency": self.currency or "EUR",
            "extracted_merchant": self.merchant,
            "extracted_category": self.category,
            "extracted_invoice_number": self.invoice_number,
            "extracted_is_invoice": int(bool(self.is_invoice)),
            "extracted_is_payment_proof": int(bool(self.is_payment_proof)),
            "extracted_tax_amount": self.tax_amount,
            "extracted_confidence": float(self.confidence),
            "extraction_raw": json.dumps(self.raw_response, ensure_ascii=False),
            "extraction_model": self.model,
        }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ExtractionError(RuntimeError):
    """Provider lieferte keine verwertbare Antwort."""


class ExtractionParseError(ExtractionError):
    """KI-Antwort konnte nicht als JSON geparst werden."""


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


EXTRACTION_PROMPT = """\
Analysiere diesen Beleg/diese Rechnung und extrahiere die folgenden Informationen.
Antworte NUR mit einem JSON-Objekt, ohne Erklärungen, ohne Markdown-Blöcke.

Extrahiere:
{
  "date": "YYYY-MM-DD oder null",
  "amount": Gesamtbetrag als Zahl oder null,
  "currency": "EUR",
  "merchant": "Name des Händlers/Unternehmens oder null",
  "category": "Eine von: Lebensmittel, Restaurant, Tankstelle, Bürobedarf, Elektronik, Kleidung, Gesundheit, Versicherung, Handwerk/Dienstleistung, Transport, Sonstiges",
  "invoice_number": "Rechnungsnummer oder null",
  "is_invoice": true wenn formelle Rechnung mit MwSt-Ausweis, false wenn Kassenbon,
  "is_payment_proof": true wenn Zahlungsnachweis (Überweisungsbeleg, PayPal-Quittung etc.),
  "tax_amount": MwSt-Betrag als Zahl oder null,
  "confidence": Deine Konfidenz 0.0-1.0 wie sicher du dir bei den Angaben bist,
  "notes": "Kurze Anmerkungen wenn etwas unklar ist"
}

Wichtig:
- Wenn du einen Wert nicht sicher erkennen kannst, setze null (nicht raten)
- Bei mehreren Positionen: amount = Gesamtsumme (Brutto)
- Datum im Format YYYY-MM-DD
- amount immer als Dezimalzahl (Punkt als Trennzeichen)
- Beträge sind immer POSITIV (auch bei Erstattungen/Gutschriften)
"""


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class ReceiptExtractor:
    """Provider-agnostische Beleg-Extraktion."""

    def __init__(self, config: ExtractionConfig) -> None:
        self._config = config
        self._check_multimodal_warning()

    def extract(self, pdf_path: Path) -> ExtractedReceipt:
        """Hauptmethode: PDF → ExtractedReceipt (mit Fallback)."""
        try:
            result = self._extract_with_provider(pdf_path, self._config.provider)
            return self._validate(result)
        except (ExtractionError, requests.RequestException) as err:
            logger.warning(
                "Provider %s fehlgeschlagen: %s", self._config.provider, err
            )
            fallback = self._config.fallback_provider
            if fallback and fallback != self._config.provider:
                try:
                    result = self._extract_with_provider(pdf_path, fallback)
                    return self._validate(result)
                except (ExtractionError, requests.RequestException) as err2:
                    logger.error("Fallback %s fehlgeschlagen: %s", fallback, err2)
            return ExtractedReceipt(confidence=0.0, raw_response={"error": str(err)})

    # ------------------------------------------------------------------
    # Provider-Routing
    # ------------------------------------------------------------------

    def _extract_with_provider(self, pdf_path: Path, provider: str) -> ExtractedReceipt:
        if provider == "local_lm_studio":
            return self._extract_lm_studio(pdf_path)
        if provider == "ollama":
            return self._extract_ollama(pdf_path)
        if provider == "openai":
            return self._extract_openai(pdf_path)
        if provider == "anthropic":
            return self._extract_anthropic(pdf_path)
        raise ExtractionError(f"Unbekannter Provider: {provider}")

    def _extract_lm_studio(self, pdf_path: Path) -> ExtractedReceipt:
        cfg = self._config.local_lm_studio
        image_b64 = self._pdf_to_base64_image(pdf_path)
        payload = {
            "model": cfg.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }
            ],
            "temperature": 0.1,
            "max_tokens": 500,
        }
        resp = requests.post(
            f"{cfg.base_url.rstrip('/')}/chat/completions",
            json=payload,
            timeout=cfg.timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        parsed = self._parse_json_response(text)
        return self._build(parsed, model=cfg.model)

    def _extract_ollama(self, pdf_path: Path) -> ExtractedReceipt:
        cfg = self._config.ollama
        image_b64 = self._pdf_to_base64_image(pdf_path)
        payload = {
            "model": cfg.model,
            "prompt": EXTRACTION_PROMPT,
            "images": [image_b64],
            "stream": False,
        }
        resp = requests.post(
            f"{cfg.base_url.rstrip('/')}/api/generate",
            json=payload,
            timeout=cfg.timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("response", "")
        parsed = self._parse_json_response(text)
        return self._build(parsed, model=cfg.model)

    def _extract_openai(self, pdf_path: Path) -> ExtractedReceipt:
        cfg = self._config.openai
        if not cfg.api_key:
            raise ExtractionError("OPENAI_API_KEY nicht gesetzt")
        image_b64 = self._pdf_to_base64_image(pdf_path)
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            json={
                "model": cfg.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                            },
                            {"type": "text", "text": EXTRACTION_PROMPT},
                        ],
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 500,
            },
            timeout=cfg.timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        parsed = self._parse_json_response(text)
        return self._build(parsed, model=cfg.model)

    def _extract_anthropic(self, pdf_path: Path) -> ExtractedReceipt:
        cfg = self._config.anthropic
        if not cfg.api_key:
            raise ExtractionError("ANTHROPIC_API_KEY nicht gesetzt")
        image_b64 = self._pdf_to_base64_image(pdf_path)
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": cfg.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": cfg.model,
                "max_tokens": 500,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": EXTRACTION_PROMPT},
                        ],
                    }
                ],
            },
            timeout=cfg.timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"]
        parsed = self._parse_json_response(text)
        return self._build(parsed, model=cfg.model)

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------

    def _build(self, parsed: dict[str, Any], model: str) -> ExtractedReceipt:
        return ExtractedReceipt(
            date=parsed.get("date"),
            amount=_to_float(parsed.get("amount")),
            currency=parsed.get("currency") or "EUR",
            merchant=parsed.get("merchant"),
            category=parsed.get("category"),
            invoice_number=parsed.get("invoice_number"),
            is_invoice=bool(parsed.get("is_invoice", False)),
            is_payment_proof=bool(parsed.get("is_payment_proof", False)),
            tax_amount=_to_float(parsed.get("tax_amount")),
            confidence=float(parsed.get("confidence", 0.0) or 0.0),
            raw_response=parsed,
            model=model,
        )

    def _validate(self, receipt: ExtractedReceipt) -> ExtractedReceipt:
        """Bereinigt offensichtliche KI-Fehler."""
        # Betrag: positiv, < 100k
        if receipt.amount is not None:
            receipt.amount = abs(receipt.amount)
            if receipt.amount > 100_000:
                receipt.amount = None
        # Datum: nicht in der Zukunft, parsebar
        if receipt.date:
            try:
                d = date.fromisoformat(receipt.date)
                if d > date.today():
                    receipt.date = None
            except ValueError:
                receipt.date = None
        # Confidence: 0.0 - 1.0
        receipt.confidence = max(0.0, min(1.0, receipt.confidence))
        return receipt

    def _pdf_to_base64_image(self, pdf_path: Path) -> str:
        """Konvertiert erste PDF-Seite zu Base64-JPEG."""
        try:
            from pdf2image import convert_from_path  # type: ignore[import-not-found]
        except ImportError as err:
            raise ExtractionError("pdf2image nicht installiert") from err
        try:
            images = convert_from_path(str(pdf_path), dpi=200, first_page=1, last_page=1)
        except Exception as err:  # noqa: BLE001
            raise ExtractionError(f"PDF→Bild fehlgeschlagen: {err}") from err
        if not images:
            raise ExtractionError("PDF enthält keine Seite")
        import io  # noqa: PLC0415

        buf = io.BytesIO()
        images[0].convert("RGB").save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def _parse_json_response(self, raw: str) -> dict[str, Any]:
        """Robust gegen Markdown-Blöcke, Whitespace, Trailing Commas."""
        text = (raw or "").strip()
        # ```json ... ``` oder ``` ... ```
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        # Trailing commas (best-effort)
        text = re.sub(r",\s*([\}\]])", r"\1", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise ExtractionParseError(f"KI-Antwort ist kein JSON: {err}") from err

    def _check_multimodal_warning(self) -> None:
        provider = self._config.provider
        cfg_map: dict[str, Any] = {
            "local_lm_studio": self._config.local_lm_studio,
            "ollama": self._config.ollama,
            "openai": self._config.openai,
            "anthropic": self._config.anthropic,
        }
        cfg = cfg_map.get(provider)
        if not cfg:
            return
        model_lower = (getattr(cfg, "model", "") or "").lower()
        if not any(tag in model_lower for tag in ("vl", "vision", "llava", "4o", "haiku", "opus", "sonnet")):
            logger.warning(
                "Modell %s wirkt nicht multimodal — Belege können nicht gelesen werden.",
                getattr(cfg, "model", "?"),
            )


# ---------------------------------------------------------------------------
# Modul-Helpers
# ---------------------------------------------------------------------------


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "EXTRACTION_PROMPT",
    "ExtractedReceipt",
    "ExtractionError",
    "ExtractionParseError",
    "ReceiptExtractor",
]
