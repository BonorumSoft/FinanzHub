"""Jinja2-Template-Loader für FinanzHub-Mail-Templates.

Lädt HTML- und Text-Varianten aller Templates aus ``app/templates/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.logger import get_logger

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def get_environment() -> Environment:
    """Liefert eine Jinja2-Umgebung mit auto-escape (HTML) und trim_blocks."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


def render(template_name: str, context: dict[str, Any]) -> tuple[str, str]:
    """Rendert ein Template-Paar (HTML + Text).

    Pro ``template_name`` (z. B. ``daily_wealth_report``) wird sowohl
    ``<name>.html.j2`` als auch ``<name>.txt.j2`` geladen — fällt eine
    Variante weg, wird ein Stub-Text verwendet.
    """
    env = get_environment()
    html_path = f"{template_name}.html.j2"
    text_path = f"{template_name}.txt.j2"
    html = env.get_template(html_path).render(**context) if (TEMPLATES_DIR / html_path).exists() else ""
    if (TEMPLATES_DIR / text_path).exists():
        text = env.get_template(text_path).render(**context)
    else:
        text = f"{context.get('title', 'FinanzHub')}\n\n{context.get('summary', '')}\n"
    return html, text


__all__ = ["TEMPLATES_DIR", "get_environment", "render"]
