"""Безопасный сериализатор raw TL-объектов и любых данных в JSON.

Правила:
- TLObject (всё с to_dict()) -> рекурсивно очищенный dict;
- bytes/bytearray -> {"$bytes": {"b64": ..., "hex": ...}};
- datetime -> ISO 8601;
- set/tuple -> list;
- неизвестное -> {"$unknown": type, "repr": ...}.

Ошибка сериализации никогда не прерывает обход: safe_dumps возвращет
заглушку с описанием ошибки.
"""

from __future__ import annotations

import base64
import datetime
import json
from pathlib import Path

_MAX_REPR = 500


def clean(value):
    """Рекурсивно превращает значение в JSON-совместимое."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return {
            "$bytes": {
                "b64": base64.b64encode(bytes(value)).decode("ascii"),
                "hex": bytes(value).hex(),
            }
        }
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [clean(v) for v in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return clean(value.to_dict())
        except Exception:  # noqa: BLE001 - падение to_dict не должно ломать обход
            pass
    return {
        "$unknown": type(value).__name__,
        "repr": repr(value)[:_MAX_REPR],
    }


def safe_dumps(obj, indent: int | None = None) -> str:
    """json.dumps, который не падает ни на чём."""
    try:
        return json.dumps(clean(obj), ensure_ascii=False, indent=indent)
    except Exception as e:  # noqa: BLE001
        fallback = {"$error": f"serialization failed: {type(e).__name__}: {e}"}
        try:
            return json.dumps(fallback, ensure_ascii=False, indent=indent)
        except Exception:  # noqa: BLE001 - совсем безнадёжный случай
            return '{"$error": "serialization failed"}'
