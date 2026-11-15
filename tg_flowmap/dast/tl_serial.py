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


def clean(value, _seen=None, _depth: int = 0, max_depth: int = 30):
    """Рекурсивно превращает значение в JSON-совместимое с защитой от циклов."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if _depth >= max_depth:
        return {"$unknown": type(value).__name__, "repr": repr(value)[:_MAX_REPR]}

    if _seen is None:
        _seen = set()
    val_id = id(value)
    if isinstance(value, (dict, list, tuple, set, frozenset)):
        if val_id in _seen:
            return {"$cycle": type(value).__name__, "id": val_id}
        _seen.add(val_id)

    if isinstance(value, (bytes, bytearray)):
        return {
            "$bytes": {
                "b64": base64.b64encode(bytes(value)).decode("ascii"),
                "hex": bytes(value).hex(),
            }
        }
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): clean(v, _seen, _depth + 1, max_depth) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [clean(v, _seen, _depth + 1, max_depth) for v in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        if val_id in _seen:
            return {"$cycle": type(value).__name__, "id": val_id}
        _seen.add(val_id)
        try:
            return clean(value.to_dict(), _seen, _depth + 1, max_depth)
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
