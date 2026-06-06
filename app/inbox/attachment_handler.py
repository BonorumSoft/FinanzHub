"""Routing: PDF direkt weiterleiten, Bild konvertieren, Unbekanntes verwerfen."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.config_loader import InboxConfig
from app.inbox.image_converter import ImageConversionError, ImageConverter
from app.inbox.mail_fetcher import Attachment
from app.logger import get_logger

logger = get_logger(__name__)

RouteAction = Literal["convert_image", "direct_pdf", "skip"]


@dataclass
class ProcessedAttachment:
    """Ergebnis der Verarbeitung eines Anhangs."""

    original: Attachment
    action: RouteAction
    pdf_path: Path | None = None
    error: str | None = None


class AttachmentHandler:
    """Pro Anhang: entscheiden, wohin damit."""

    def __init__(
        self,
        config: InboxConfig,
        image_converter: ImageConverter | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._image_converter = image_converter or ImageConverter()
        self._output_dir = output_dir or Path(config.storage_path)

    def process(self, attachment: Attachment) -> ProcessedAttachment:
        """Pro Anhang: Bild konvertieren, PDF direkt übernehmen, sonst überspringen.

        Raises:
            Keine — Fehler werden in :class:`ProcessedAttachment.error` gemeldet.
        """
        mime = attachment.mimetype.lower()
        try:
            if mime.startswith("image/"):
                return self._handle_image(attachment)
            if mime == "application/pdf":
                return self._handle_pdf(attachment)
            return ProcessedAttachment(
                original=attachment,
                action="skip",
                error=f"MIME nicht unterstützt: {mime}",
            )
        except ImageConversionError as err:
            return ProcessedAttachment(original=attachment, action="skip", error=str(err))
        except Exception as err:  # noqa: BLE001
            logger.warning("Unerwarteter Fehler bei %s: %s", attachment.filename, err)
            return ProcessedAttachment(original=attachment, action="skip", error=str(err))

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _handle_image(self, attachment: Attachment) -> ProcessedAttachment:
        target = self._build_target_path(attachment)
        try:
            self._image_converter.convert(attachment.data, attachment.mimetype, target)
        except ImageConversionError as err:
            return ProcessedAttachment(
                original=attachment, action="skip", error=str(err)
            )
        return ProcessedAttachment(
            original=attachment, action="convert_image", pdf_path=target
        )

    def _handle_pdf(self, attachment: Attachment) -> ProcessedAttachment:
        target = self._build_target_path(attachment, force_ext=".pdf")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(attachment.data)
        except OSError as err:
            return ProcessedAttachment(
                original=attachment, action="skip", error=f"Speichern fehlgeschlagen: {err}"
            )
        return ProcessedAttachment(
            original=attachment, action="direct_pdf", pdf_path=target
        )

    def _build_target_path(self, attachment: Attachment, force_ext: str = ".pdf") -> Path:
        stem = Path(attachment.filename).stem
        # Sanitize: nur [a-zA-Z0-9_-]
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:80]
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return self._output_dir / f"{ts}_{safe}{force_ext}"


__all__ = ["AttachmentHandler", "ProcessedAttachment", "RouteAction"]
