"""Bild → PDF Konvertierung (JPEG, PNG, HEIC/HEIF, WEBP)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import img2pdf

from app.logger import get_logger

logger = get_logger(__name__)


class ImageConversionError(RuntimeError):
    """Fehler bei der Bild-Konvertierung."""


class ImageConverter:
    """Konvertiert Bilder in ein einspuriges, durchsuchbares PDF.

    Unterstützte Eingabeformate:
      - JPEG, PNG, WEBP: direkt via ``img2pdf``
      - HEIC/HEIF: via ``pillow-heif`` in PIL laden, EXIF-Rotation normalisieren,
        dann in JPEG konvertieren, dann via ``img2pdf``.

    Schreibt nach ``output_path`` und gibt denselben Pfad zurück.
    """

    def convert(self, image_data: bytes, mimetype: str, output_path: Path) -> Path:
        """Konvertiert Bilddaten in eine PDF-Datei.

        Args:
            image_data: Rohdaten des Bildes.
            mimetype: Quell-MIME-Type (``image/jpeg``, ``image/heic`` etc.).
            output_path: Ziel-Pfad (inkl. ``.pdf``-Endung).

        Returns:
            Der gleiche ``output_path``.

        Raises:
            ImageConversionError: Bei jedem Konvertierungsfehler.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mime = mimetype.lower()
        try:
            if mime in {"image/heic", "image/heif"}:
                return self._convert_heic(image_data, output_path)
            if mime in {"image/jpeg", "image/jpg", "image/png", "image/webp"}:
                return self._convert_via_img2pdf(image_data, output_path)
            raise ImageConversionError(f"Nicht unterstützter MIME-Type: {mimetype}")
        except ImageConversionError:
            raise
        except Exception as err:  # noqa: BLE001
            raise ImageConversionError(f"Konvertierung fehlgeschlagen: {err}") from err

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _convert_via_img2pdf(self, image_data: bytes, output_path: Path) -> Path:
        with output_path.open("wb") as fh:
            fh.write(img2pdf.convert(image_data))
        logger.debug("PDF erstellt (img2pdf): %s", output_path)
        return output_path

    def _convert_heic(self, image_data: bytes, output_path: Path) -> Path:
        # pillow-heif ist optional; bei fehlender Installation → klare Fehlermeldung
        try:
            from pillow_heif import register_heif_opener  # type: ignore[import-not-found]
        except ImportError as err:
            raise ImageConversionError(
                "pillow-heif nicht installiert (pip install pillow-heif)"
            ) from err
        register_heif_opener()
        from PIL import Image  # noqa: PLC0415 — nach pillow-heif-Registrierung

        try:
            img = Image.open(io.BytesIO(image_data))
            img = self._normalize_orientation(img)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=85)
            return self._convert_via_img2pdf(buf.getvalue(), output_path)
        except ImageConversionError:
            raise
        except Exception as err:  # noqa: BLE001
            raise ImageConversionError(f"HEIC-Konvertierung fehlgeschlagen: {err}") from err

    @staticmethod
    def _normalize_orientation(img: Any) -> Any:
        """Korrigiert EXIF-Rotation (Smartphone-Fotos)."""
        from PIL import ImageOps  # noqa: PLC0415

        try:
            return ImageOps.exif_transpose(img)
        except Exception:  # noqa: BLE001
            return img


__all__ = ["ImageConversionError", "ImageConverter"]
