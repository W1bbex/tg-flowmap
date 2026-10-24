"""Canonical screen fingerprint + backwards-compatible helpers.

Все базовые функции идентификации канонических экранов реализованы в
explorer.screen_identity и реэкспортируются отсюда для совместимости.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

from .screen_identity import (
    buttons_signature,
    entities_signature,
    match_button_instance,
    media_signature,
    normalize_text,
    screen_fingerprint,
    screen_id_of,
    stable_action_id,
)


def route_fingerprint(screen_fp: str, parent_route_fp: str | None, entry_action: str | None) -> str:
    """Fingerprint маршрута: canonical screen + родитель + действие входа."""
    payload = f"{screen_fp}|{parent_route_fp or ''}|{entry_action or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def button_fingerprint(label: str, callback_hex: str | None, url: str | None, button_type: str) -> str:
    """Стабильный идентификатор кнопки (совместимость с существующими тестами и отчётами)."""
    payload = f"{normalize_text(label)}|{callback_hex or url or ''}|{button_type}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def route_id_of(rfp: str) -> str:
    return "r_" + rfp[:16]


__all__ = [
    "normalize_text",
    "entities_signature",
    "buttons_signature",
    "media_signature",
    "screen_fingerprint",
    "screen_id_of",
    "stable_action_id",
    "match_button_instance",
    "route_fingerprint",
    "route_id_of",
    "button_fingerprint",
]
