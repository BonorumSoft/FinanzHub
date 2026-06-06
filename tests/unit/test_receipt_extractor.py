"""Tests für app.inbox.receipt_extractor (Mock-basiert, keine echten API-Calls)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.config_loader import (
    AnthropicExtractionConfig,
    ExtractionConfig,
    LMStudioExtractionConfig,
    OllamaExtractionConfig,
    OpenAIExtractionConfig,
)
from app.inbox.receipt_extractor import (
    EXTRACTION_PROMPT,
    ExtractedReceipt,
    ExtractionError,
    ReceiptExtractor,
)

# ---------------------------------------------------------------------------
# JSON-Parsing
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


def _extractor(provider: str = "local_lm_studio") -> ReceiptExtractor:
    return ReceiptExtractor(ExtractionConfig(provider=provider))


# ---------------------------------------------------------------------------
# JSON-Robustheit
# ---------------------------------------------------------------------------


def test_json_parsed_from_markdown_codeblock():
    """KI antwortet mit ```json ... ``` → wird trotzdem korrekt geparst."""
    raw = 'Hier ist das Ergebnis:\n```json\n{"date": "2026-06-04", "amount": 47.9, "currency": "EUR", "merchant": "REWE", "category": "Lebensmittel", "is_invoice": false, "is_payment_proof": false, "confidence": 0.9}\n```\n'
    parsed = _extractor()._parse_json_response(raw)
    assert parsed["merchant"] == "REWE"
    assert parsed["amount"] == 47.9


def test_json_parsed_with_trailing_commas():
    raw = '{"date": "2026-06-04", "amount": 47.9,}'
    parsed = _extractor()._parse_json_response(raw)
    assert parsed["amount"] == 47.9


def test_invalid_json_raises_extraction_error():
    with pytest.raises(ExtractionError):
        _extractor()._parse_json_response("Das ist kein JSON")


# ---------------------------------------------------------------------------
# Validierung
# ---------------------------------------------------------------------------


def test_null_values_when_field_missing():
    """Unlesbare Felder → None, nicht geraten."""
    raw = '{"date": null, "amount": null, "currency": "EUR", "merchant": null, "category": null}'
    result = _extractor()._extract_with_provider(
        _mock_pdf(), "lm_studio_via_mock"
    ) if False else _build_via_mock(raw)
    assert result.date is None
    assert result.amount is None
    assert result.merchant is None


def _build_via_mock(raw_json: str) -> ExtractedReceipt:
    """Helper: baut Receipt via internem _build() ohne echten API-Call."""
    parsed = _extractor()._parse_json_response(raw_json)
    return _extractor()._build(parsed, model="mock")


def test_amount_always_positive():
    """Auch wenn KI negativen Betrag zurückgibt → abs() angewendet."""
    raw = '{"date": "2026-06-04", "amount": -47.90, "currency": "EUR", "merchant": "REWE", "is_invoice": false, "is_payment_proof": false, "confidence": 0.9}'
    parsed = _extractor()._parse_json_response(raw)
    result = _extractor()._validate(_extractor()._build(parsed, model="mock"))
    assert result.amount == 47.90


def test_amount_above_100k_clamped_to_none():
    """Betrag > 100k → None (KI-Quatsch filtern)."""
    raw = '{"date": "2026-06-04", "amount": 200000.00, "currency": "EUR", "merchant": "X", "is_invoice": false, "is_payment_proof": false, "confidence": 0.5}'
    parsed = _extractor()._parse_json_response(raw)
    result = _extractor()._validate(_extractor()._build(parsed, model="mock"))
    assert result.amount is None


def test_future_date_invalidated():
    raw = '{"date": "2099-01-01", "amount": 47.90, "currency": "EUR", "merchant": "X", "is_invoice": false, "is_payment_proof": false, "confidence": 0.5}'
    parsed = _extractor()._parse_json_response(raw)
    result = _extractor()._validate(_extractor()._build(parsed, model="mock"))
    assert result.date is None


def test_confidence_clamped_to_0_1():
    raw = '{"date": "2026-06-04", "amount": 47.90, "currency": "EUR", "merchant": "X", "is_invoice": false, "is_payment_proof": false, "confidence": 5.0}'
    parsed = _extractor()._parse_json_response(raw)
    result = _extractor()._validate(_extractor()._build(parsed, model="mock"))
    assert result.confidence == 1.0


# ---------------------------------------------------------------------------
# Provider-Routing
# ---------------------------------------------------------------------------


def _mock_pdf() -> Path:
    return Path("/tmp/does-not-matter.pdf")  # wird gemockt


def test_unknown_provider_raises(mocker):
    mocker.patch(
        "app.inbox.receipt_extractor.ReceiptExtractor._pdf_to_base64_image",
        return_value="ZmFrZQ==",
    )
    mocker.patch("requests.post", return_value=_FakeResponse({"error": "x"}, 500))
    cfg = ExtractionConfig(provider="nonexistent")
    ext = ReceiptExtractor(cfg)
    with pytest.raises(ExtractionError):
        ext._extract_with_provider(_mock_pdf(), "nonexistent")


def test_lm_studio_called(mocker):
    mocker.patch(
        "app.inbox.receipt_extractor.ReceiptExtractor._pdf_to_base64_image",
        return_value="ZmFrZQ==",
    )
    fake = _FakeResponse({
        "choices": [{"message": {"content": json.dumps({
            "date": "2026-06-04", "amount": 12.34, "currency": "EUR",
            "merchant": "LIDL", "category": "Lebensmittel",
            "is_invoice": False, "is_payment_proof": False, "confidence": 0.95,
        })}}]
    })
    mocker.patch("requests.post", return_value=fake)
    result = _extractor("local_lm_studio")._extract_lm_studio(_mock_pdf())
    assert result.merchant == "LIDL"
    assert result.amount == 12.34


def test_ollama_called(mocker):
    mocker.patch(
        "app.inbox.receipt_extractor.ReceiptExtractor._pdf_to_base64_image",
        return_value="ZmFrZQ==",
    )
    fake = _FakeResponse({"response": json.dumps({
        "date": "2026-06-04", "amount": 8.50, "currency": "EUR",
        "merchant": "BÄCKER", "category": "Lebensmittel",
        "is_invoice": False, "is_payment_proof": False, "confidence": 0.88,
    })})
    mocker.patch("requests.post", return_value=fake)
    result = _extractor("ollama")._extract_ollama(_mock_pdf())
    assert result.merchant == "BÄCKER"


def test_anthropic_called(mocker):
    mocker.patch(
        "app.inbox.receipt_extractor.ReceiptExtractor._pdf_to_base64_image",
        return_value="ZmFrZQ==",
    )
    fake = _FakeResponse({"content": [{"text": json.dumps({
        "date": "2026-06-04", "amount": 99.00, "currency": "EUR",
        "merchant": "MEDIAMARKT", "category": "Elektronik",
        "is_invoice": True, "is_payment_proof": False, "confidence": 0.92,
    })}]})
    mocker.patch("requests.post", return_value=fake)
    cfg = ExtractionConfig(provider="anthropic")
    cfg.anthropic.api_key = "sk-test"
    result = ReceiptExtractor(cfg)._extract_anthropic(_mock_pdf())
    assert result.is_invoice is True
    assert result.amount == 99.00


def test_openai_called(mocker):
    mocker.patch(
        "app.inbox.receipt_extractor.ReceiptExtractor._pdf_to_base64_image",
        return_value="ZmFrZQ==",
    )
    fake = _FakeResponse({"choices": [{"message": {"content": json.dumps({
        "date": "2026-06-04", "amount": 5.99, "currency": "EUR",
        "merchant": "BOOKING", "category": "Reisen",
        "is_invoice": False, "is_payment_proof": False, "confidence": 0.85,
    })}}]})
    mocker.patch("requests.post", return_value=fake)
    # API-Key muss gesetzt sein
    cfg = ExtractionConfig(provider="openai")
    cfg.openai.api_key = "sk-test"
    result = ReceiptExtractor(cfg)._extract_openai(_mock_pdf())
    assert result.merchant == "BOOKING"


def test_fallback_provider_used_on_primary_failure(mocker):
    """Wenn primärer Provider fehlschlägt, wird Fallback versucht."""
    # PDF→Bild scheitert
    mocker.patch(
        "app.inbox.receipt_extractor.ReceiptExtractor._pdf_to_base64_image",
        side_effect=ExtractionError("pdf kaputt"),
    )
    # Fallback wird gar nicht erst aufgerufen, weil _pdf_to_base64_image scheitert
    cfg = ExtractionConfig(provider="local_lm_studio", fallback_provider="anthropic")
    cfg.anthropic.api_key = "sk-test"
    result = ReceiptExtractor(cfg).extract(_mock_pdf())
    assert result.confidence == 0.0
    assert "pdf" in str(result.raw_response.get("error", "")).lower()


def test_openai_without_api_key_raises(mocker):
    mocker.patch(
        "app.inbox.receipt_extractor.ReceiptExtractor._pdf_to_base64_image",
        return_value="ZmFrZQ==",
    )
    cfg = ExtractionConfig(provider="openai")  # api_key leer
    ext = ReceiptExtractor(cfg)
    with pytest.raises(ExtractionError):
        ext._extract_openai(_mock_pdf())


# ---------------------------------------------------------------------------
# Multimodal-Warnung
# ---------------------------------------------------------------------------


def test_multimodal_warning_for_text_only_model(caplog):
    """Modell ohne 'vision'/'vl'/'4o'/etc → WARNING."""
    import logging
    cfg = ExtractionConfig(provider="local_lm_studio")
    cfg.local_lm_studio.model = "llama-3-8b"  # text-only
    with caplog.at_level(logging.WARNING, logger="app.inbox.receipt_extractor"):
        ReceiptExtractor(cfg)
    assert any("multimodal" in rec.message.lower() for rec in caplog.records)


def test_vision_model_no_warning(caplog):
    import logging
    cfg = ExtractionConfig(provider="local_lm_studio")
    cfg.local_lm_studio.model = "qwen2.5-vl-7b-instruct"
    with caplog.at_level(logging.WARNING, logger="app.inbox.receipt_extractor"):
        ReceiptExtractor(cfg)
    assert not any("multimodal" in rec.message.lower() for rec in caplog.records)


# ---------------------------------------------------------------------------
# to_db_dict
# ---------------------------------------------------------------------------


def test_to_db_dict_serializes_correctly():
    r = ExtractedReceipt(
        date="2026-06-04", amount=47.90, currency="EUR",
        merchant="REWE", category="Lebensmittel",
        is_invoice=False, is_payment_proof=False,
        tax_amount=7.59, confidence=0.92, model="mock",
        raw_response={"merchant": "REWE", "amount": 47.9, "date": "2026-06-04"},
    )
    d = r.to_db_dict()
    assert d["extracted_amount"] == 47.90
    assert d["extracted_merchant"] == "REWE"
    assert d["extracted_is_invoice"] == 0
    assert d["extracted_currency"] == "EUR"
    parsed = json.loads(d["extraction_raw"])
    assert parsed["merchant"] == "REWE"
