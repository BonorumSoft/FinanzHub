"""Tests für app.inbox.attachment_handler."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.config_loader import InboxConfig
from app.inbox.attachment_handler import AttachmentHandler
from app.inbox.image_converter import ImageConversionError
from app.inbox.mail_fetcher import Attachment

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jpeg() -> bytes:
    img = Image.new("RGB", (40, 30), color="white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_pdf() -> bytes:
    """Minimale gültige PDF-Bytes (1 Seite leer)."""
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000053 00000 n \n0000000097 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n141\n%%EOF"


@pytest.fixture()
def tmp_storage(tmp_path: Path) -> Path:
    return tmp_path / "receipts"


@pytest.fixture()
def config(tmp_storage: Path) -> InboxConfig:
    cfg = InboxConfig()
    cfg.storage_path = str(tmp_storage)
    cfg.accepted_mimetypes = ["image/jpeg", "image/png", "application/pdf"]
    return cfg


# ---------------------------------------------------------------------------
# Routing-Tests
# ---------------------------------------------------------------------------


def test_jpeg_routed_to_image_converter(config, tmp_storage):
    handler = AttachmentHandler(config, output_dir=tmp_storage)
    att = Attachment(filename="bon.jpg", mimetype="image/jpeg", data=_make_jpeg())
    result = handler.process(att)
    assert result.action == "convert_image"
    assert result.pdf_path is not None
    assert result.pdf_path.exists()
    assert result.pdf_path.suffix == ".pdf"


def test_png_routed_to_image_converter(config, tmp_storage):
    handler = AttachmentHandler(config, output_dir=tmp_storage)
    img = Image.new("RGB", (10, 10), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    att = Attachment(filename="bon.png", mimetype="image/png", data=buf.getvalue())
    result = handler.process(att)
    assert result.action == "convert_image"
    assert result.pdf_path is not None


def test_pdf_routed_directly(config, tmp_storage):
    handler = AttachmentHandler(config, output_dir=tmp_storage)
    att = Attachment(filename="rechnung.pdf", mimetype="application/pdf", data=_make_pdf())
    result = handler.process(att)
    assert result.action == "direct_pdf"
    assert result.pdf_path is not None
    assert result.pdf_path.read_bytes() == _make_pdf()


def test_unsupported_mimetype_skipped_with_warning(config, tmp_storage, caplog):
    import logging
    handler = AttachmentHandler(config, output_dir=tmp_storage)
    att = Attachment(filename="virus.exe", mimetype="application/x-msdownload", data=b"")
    with caplog.at_level(logging.WARNING, logger="app.inbox.attachment_handler"):
        result = handler.process(att)
    assert result.action == "skip"
    assert result.error is not None


def test_invalid_image_data_skipped(config, tmp_storage):
    """Nicht-Bild-Daten mit image/-MIME → skip mit Error."""
    handler = AttachmentHandler(config, output_dir=tmp_storage)
    att = Attachment(filename="kaputt.jpg", mimetype="image/jpeg", data=b"kein JPEG")
    result = handler.process(att)
    assert result.action == "skip"
    assert result.error is not None


def test_filename_sanitized(config, tmp_storage):
    """Sonderzeichen im Dateinamen werden ersetzt."""
    handler = AttachmentHandler(config, output_dir=tmp_storage)
    att = Attachment(filename="Kassenbon (REWE) 2026.jpg", mimetype="image/jpeg", data=_make_jpeg())
    result = handler.process(att)
    assert result.action == "convert_image"
    assert result.pdf_path is not None
    # Sollte keine Klammern oder Leerzeichen mit pathologischen Zeichen enthalten
    assert "(" not in result.pdf_path.name
    assert ")" not in result.pdf_path.name


def test_filename_uniqueness(config, tmp_storage):
    """Gleiche Datei zweimal → unterschiedliche Ziel-Pfade (Timestamp)."""
    import time
    handler = AttachmentHandler(config, output_dir=tmp_storage)
    att1 = Attachment(filename="a.jpg", mimetype="image/jpeg", data=_make_jpeg())
    r1 = handler.process(att1)
    time.sleep(1.05)  # timestamp-Auflösung = Sekunden
    att2 = Attachment(filename="a.jpg", mimetype="image/jpeg", data=_make_jpeg())
    r2 = handler.process(att2)
    assert r1.pdf_path != r2.pdf_path


def test_pdf_saves_exact_bytes(config, tmp_storage):
    """PDF: Bytes 1:1 kopiert."""
    handler = AttachmentHandler(config, output_dir=tmp_storage)
    payload = _make_pdf() + b"\n%extra"
    att = Attachment(filename="doc.pdf", mimetype="application/pdf", data=payload)
    result = handler.process(att)
    assert result.pdf_path.read_bytes() == payload
