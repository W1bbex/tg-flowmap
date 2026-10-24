"""Идентификация канонических экранов, стабильных дескрипторов действий и экземпляров кнопок.

Принципы:
1. Canonical Screen:
   - нормализованный текст (с вырезанными volatile-шаблонами);
   - подпись entities с пересчитанными смещениями;
   - структура клавиатуры (row/col, normalized label, type, url, styles, requires_password);
   - НЕ содержит message_id, raw callback_data, callback_hex, tg_id медиа.
2. Stable Action:
   - детерминированный идентификатор действия на конкретном каноническом экране;
   - action_id = act_<sha256(source_screen_id:row:col:label_norm:type:styles)[:16]>;
   - не зависит от opaque callback_data токенов.
3. Button Instance Matching:
   - сопоставляет стабильное действие с актуальным экземпляром кнопки конкретной версии сообщения;
   - вычисляет confidence;
   - при неоднозначности возвращает None (безопасный отказ от нажатия).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

from .utf16 import char_index_for_utf16


def normalize_text(text: str, volatile_patterns: Iterable[re.Pattern] = ()) -> str:
    """Нормализует текст: удаляет volatile-шаблоны, приводит к нижнему регистру и сворачивает пробелы."""
    if not text:
        return ""
    t = text.strip().lower()
    for pat in volatile_patterns:
        t = pat.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _keep_prefix(text: str, volatile_patterns: Iterable[re.Pattern]) -> list[int]:
    """keep_prefix[i] = сколько сохранённых символов в text[:i] после вырезания volatile."""
    keep = [True] * len(text)
    for pat in volatile_patterns:
        for m in pat.finditer(text):
            for i in range(m.start(), m.end()):
                keep[i] = False
    prefix = [0] * (len(text) + 1)
    running = 0
    for i, k in enumerate(keep):
        running += 1 if k else 0
        prefix[i + 1] = running
    return prefix


def entities_signature(
    text: str,
    entities: list[dict],
    volatile_patterns: Iterable[re.Pattern] = (),
) -> list[list]:
    """Подпись entities с пересчётом offsets после вырезания volatile-фрагментов."""
    if not entities:
        return []
    prefix = _keep_prefix(text, volatile_patterns)
    out: list[list] = []
    for e in entities:
        off, ln = int(e.get("offset", 0)), int(e.get("length", 0))
        start_c = char_index_for_utf16(text, off)
        end_c = char_index_for_utf16(text, off + ln)
        if end_c <= start_c:
            continue
        if start_c >= len(text):
            continue
        new_start = prefix[min(start_c, len(prefix) - 1)]
        new_end = prefix[min(end_c, len(prefix) - 1)]
        new_len = new_end - new_start
        if new_len <= 0:
            continue
        out.append([
            str(e.get("type", "")),
            new_start,
            new_len,
        ])
    return out


def buttons_signature(buttons: list[dict | Any]) -> list[list]:
    """Каноническая структура кнопок: ряд, колонка, нормализованная подпись,
    тип, url и стили. НЕ включает raw callback_data / callback_hex!"""
    rows: dict[int, list] = {}
    for b in buttons:
        if hasattr(b, "to_dict"):
            b_dict = b.to_dict()
        elif isinstance(b, dict):
            b_dict = b
        else:
            b_dict = getattr(b, "__dict__", {})

        row = int(b_dict.get("row", 0))
        col = int(b_dict.get("col", 0))
        label = normalize_text(str(b_dict.get("label", "")))
        b_type = str(b_dict.get("button_type", ""))
        url = b_dict.get("url")

        style = b_dict.get("style", {}) if isinstance(b_dict.get("style"), dict) else {}
        bg_primary = int(style.get("bg_primary", b_dict.get("style_bg_primary", 0)) or 0)
        bg_success = int(style.get("bg_success", b_dict.get("style_bg_success", 0)) or 0)
        bg_danger = int(style.get("bg_danger", b_dict.get("style_bg_danger", 0)) or 0)
        icon_id = str(style.get("icon_document_id", b_dict.get("style_icon_id", "")) or "")
        req_pwd = int(style.get("requires_password", b_dict.get("style_requires_password", 0)) or 0)

        rows.setdefault(row, []).append([
            col,
            label,
            b_type,
            url,
            bg_primary,
            bg_success,
            bg_danger,
            icon_id,
            req_pwd,
        ])
    return [sorted(items) for _, items in sorted(rows.items())]


def media_signature(media: list[dict | Any]) -> list[list]:
    """Каноническая подпись медиа: тип и свойства. Без нестабильных Telegram ID."""
    out = []
    for m in media:
        if hasattr(m, "to_dict"):
            m_dict = m.to_dict()
        elif isinstance(m, dict):
            m_dict = m
        else:
            m_dict = getattr(m, "__dict__", {})
        out.append([
            str(m_dict.get("kind", "none")),
            bool(m_dict.get("is_qr_candidate", False)),
            bool(m_dict.get("has_caption_entities", False)),
        ])
    return sorted(out)


def screen_fingerprint(
    text: str,
    entities: list[dict | Any],
    buttons: list[dict | Any],
    media: list[dict | Any],
    volatile_patterns: Iterable[re.Pattern] = (),
    has_force_reply: bool = False,
) -> str:
    """Генерирует SHA-256 fingerprint канонического экрана."""
    raw_entities = [e.to_dict() if hasattr(e, "to_dict") else e for e in entities]
    raw_buttons = [b.to_dict() if hasattr(b, "to_dict") else b for b in buttons]
    raw_media = [m.to_dict() if hasattr(m, "to_dict") else m for m in media]

    payload = {
        "t": normalize_text(text, volatile_patterns),
        "e": entities_signature(text, raw_entities, volatile_patterns),
        "b": buttons_signature(raw_buttons),
        "m": media_signature(raw_media),
        "fr": bool(has_force_reply),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def screen_id_of(fp: str) -> str:
    return "s_" + fp[:16]


def stable_action_id(
    source_screen_id: str,
    row: int,
    col: int,
    label: str,
    button_type: str,
    style_icon_id: str | None = None,
    requires_password: bool = False,
    url: str | None = None,
) -> str:
    """Генерирует стабильный action_id для действия на каноническом экране.
    Не использует сырой callback_data!"""
    norm_label = normalize_text(label)
    payload = (
        f"{source_screen_id}:{row}:{col}:{norm_label}:{button_type}:"
        f"{style_icon_id or ''}:{int(requires_password)}:{url or ''}"
    )
    return "act_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _extract_field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        val = obj[key]
        return val if val is not None else default
    except (TypeError, KeyError, IndexError):
        pass
    val = getattr(obj, key, default)
    return val if val is not None else default


def match_button_instance(
    action: dict | Any,
    instances: list[dict | Any],
) -> tuple[Any | None, float, str]:
    """Сопоставляет целевое действие с доступными button instances текущего сообщения.
    
    Возвращает (matched_instance, confidence, match_reason).
    Confidence:
      1.0 — точное совпадение по row, col, label, button_type
      0.9 — уникальное совпадение по label, button_type, icon (позиция сместилась)
      0.0 — совпадение не найдено или неоднозначно (несколько одинаковых кнопок)
    """
    if not instances:
        return None, 0.0, "no_instances_available"

    a_row = int(_extract_field(action, "row", 0))
    a_col = int(_extract_field(action, "col", 0))
    a_label = normalize_text(str(_extract_field(action, "label", "")))
    a_type = str(_extract_field(action, "button_type", ""))
    a_icon = str(_extract_field(action, "style_icon_id", "") or "")

    # 1. Попытка точного позиционного совпадения
    exact_matches = []
    for inst in instances:
        i_row = int(_extract_field(inst, "row", 0))
        i_col = int(_extract_field(inst, "col", 0))
        i_label = normalize_text(str(_extract_field(inst, "label", "")))
        i_type = str(_extract_field(inst, "button_type", ""))
        i_icon = str(_extract_field(inst, "style_icon_id", "") or "")

        if i_row == a_row and i_col == a_col and i_label == a_label and i_type == a_type:
            exact_matches.append(inst)

    if len(exact_matches) == 1:
        return exact_matches[0], 1.0, "exact_position_and_label"

    # 2. Попытка структурного совпадения по тексту и типу (если позиция сместилась)
    label_matches = []
    for inst in instances:
        i_label = normalize_text(str(_extract_field(inst, "label", "")))
        i_type = str(_extract_field(inst, "button_type", ""))
        i_icon = str(_extract_field(inst, "style_icon_id", "") or "")

        if i_label == a_label and i_type == a_type:
            if not a_icon or a_icon == i_icon:
                label_matches.append(inst)

    if len(label_matches) == 1:
        return label_matches[0], 0.9, "unique_label_type_match"

    if len(label_matches) > 1:
        return None, 0.0, "ambiguous_multiple_matches"

    return None, 0.0, "no_match_found"
