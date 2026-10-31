"""Message (Telethon) → MessageCapture: полное сохранение всех полей ТЗ.

Ничего не декодируем и не меняем: callback_data байт-в-байт, текст как есть,
offsets entities в UTF-16 (как отдаёт Telegram).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from .html_render import render_html
from .models import ButtonRef, EntityInfo, MediaInfo, MessageCapture
from .utf16 import utf16_offset_of_char, utf16_slice
from .state import State

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF"
    "\u2705\u274C\u2764\u2B50\uFE0F\u200D\u20E3]+"
)

_BUTTON_TYPE_MAP = {
    "KeyboardButtonCallback": "callback",
    "KeyboardButtonUrl": "url",
    "KeyboardButton": "reply",
    "KeyboardButtonSwitchInline": "switch_inline",
    "KeyboardButtonSwitchInlineSame": "switch_inline",
    "KeyboardButtonGame": "game",
    "KeyboardButtonWebView": "web_app",
    "KeyboardButtonSimpleWebView": "web_app",
    "KeyboardButtonLoginUrl": "login_url",
    "KeyboardButtonUserProfile": "user_profile",
    "KeyboardButtonRequestPoll": "request_poll",
    "KeyboardButtonRequestGeoLocation": "request_location",
    "KeyboardButtonRequestPhone": "request_contact",
}


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


def build_entity_infos(text: str, entities) -> list[EntityInfo]:
    """Все MessageEntity → EntityInfo (type/offset/length/url/language/document_id)."""
    out: list[EntityInfo] = []
    premium_order = 0
    for e in entities or []:
        etype = type(e).__name__
        offset = int(getattr(e, "offset", 0))
        length = int(getattr(e, "length", 0))
        url = getattr(e, "url", None)
        language = getattr(e, "language", None)
        document_id = getattr(e, "document_id", None)
        is_premium = etype == "MessageEntityCustomEmoji" and document_id is not None
        symbol = None
        order_index = None
        if is_premium:
            order_index = premium_order
            premium_order += 1
            # точный utf-16 срез: символ/placeholder на позиции entity
            symbol = utf16_slice(text, offset, length) or "\ufffd"
        out.append(EntityInfo(
            type=etype, offset=offset, length=length,
            url=url if isinstance(url, str) else None,
            language=language if isinstance(language, str) else None,
            document_id=document_id,
            is_premium=is_premium, order_index=order_index, symbol=symbol,
            collapsed=bool(getattr(e, "collapsed", False)),  # expandable quote
        ))
    return out


def extract_emojis(text: str) -> list[dict]:
    """Обычные (не premium) emoji с UTF-16 offset; последовательности
    (emoji + VS16 + ZWJ + ключевые капы) склеиваются в один символ."""
    out: list[dict] = []
    if not text:
        return out
    prev_end = -1
    for m in EMOJI_RE.finditer(text):
        if out and m.start() == prev_end:
            out[-1]["symbol"] += m.group()
        else:
            out.append({
                "symbol": m.group(),
                "utf16_offset": utf16_offset_of_char(text, m.start()),
            })
        prev_end = m.end()
    return out


def _doc_kind(doc) -> tuple[str, bool]:
    """(kind, is_qr_candidate) по mime/attributes документа."""
    mime = (getattr(doc, "mime_type", None) or "").lower()
    attrs = getattr(doc, "attributes", None) or []
    attr_names = " ".join(type(a).__name__.lower() for a in attrs)
    attrs_str = ""
    for a in attrs:
        fn = getattr(a, "file_name", None)
        if fn:
            attrs_str += f" {fn.lower()}"
    kind = "document"
    if "animated" in attr_names or "gif" in mime:
        kind = "animation"
    elif "sticker" in attr_names or "sticker" in mime:
        kind = "sticker"
    elif "audio" in attr_names or mime.startswith("audio"):
        kind = "audio" if "voice" not in attr_names else "voice"
    elif "video" in attr_names or mime.startswith("video"):
        kind = "video"
    elif mime.startswith("image"):
        kind = "image"
    is_qr = "qr" in attrs_str or "qr" in mime
    return kind, is_qr


def extract_media(msg) -> list[MediaInfo]:
    """Медиа сообщения (duck-typed: достаточно атрибутов Telethon Message)."""
    out: list[MediaInfo] = []
    text = getattr(msg, "message", None) or ""
    entities = getattr(msg, "entities", None) or []

    photo = getattr(msg, "photo", None)
    if photo is not None:
        out.append(MediaInfo(kind="photo", tg_id=str(getattr(photo, "id", None) or ""),
                             caption=text or None,
                             has_caption_entities=bool(entities)))
    for attr_name in ("animation", "voice", "audio", "video", "sticker"):
        obj = getattr(msg, attr_name, None)
        if obj is not None:
            out.append(MediaInfo(
                kind=attr_name, tg_id=str(getattr(obj, "id", None) or ""),
                size=getattr(obj, "size", None),
                caption=text or None, has_caption_entities=bool(entities)))
            break
    if not out:
        doc = getattr(msg, "document", None)
        if doc is not None:
            kind, is_qr = _doc_kind(doc)
            out.append(MediaInfo(
                kind=kind, tg_id=str(getattr(doc, "id", None) or ""),
                size=getattr(doc, "size", None), caption=text or None,
                has_caption_entities=bool(entities), is_qr_candidate=is_qr))
    web = getattr(msg, "web_preview", None)
    if web is not None:
        out.append(MediaInfo(kind="web_preview",
                             tg_id=str(getattr(web, "id", None) or ""),
                             caption=text or None))
    return out


def extract_buttons(reply_markup, message_id: int | None) -> list[ButtonRef]:
    """Кнопки из reply_markup: inline (callback/url/…) и reply-клавиатура.
    Telethon 1.44: KeyboardButtonCallback.style (KeyboardButtonStyle:
    bg_primary/bg_success/bg_danger/icon) и requires_password на самой кнопке."""
    out: list[ButtonRef] = []
    rows = getattr(reply_markup, "rows", None) or []
    for ri, row in enumerate(rows):
        for ci, btn in enumerate(getattr(row, "buttons", None) or []):
            cls = type(btn).__name__
            label = getattr(btn, "text", None) or ""
            data = getattr(btn, "data", None)
            if not isinstance(data, (bytes, bytearray)):
                data = None
            btype = _BUTTON_TYPE_MAP.get(cls, "other")
            # custom_emoji_id/icon_custom_emoji_id — дженерик-скан raw TL кнопки
            custom_emoji_id = None
            for attr in ("icon_custom_emoji_id", "custom_emoji_id"):
                v = getattr(btn, attr, None)
                if v:
                    custom_emoji_id = str(v)
                    break
            # стиль кнопки (Telethon 1.44): style = KeyboardButtonStyle(...)
            style = getattr(btn, "style", None)
            style_icon = getattr(style, "icon", None) if style is not None else None
            requires_password = bool(getattr(btn, "requires_password", False))
            out.append(ButtonRef(
                row=ri, col=ci, label=label, button_type=btype,
                callback_data=bytes(data) if data is not None else None,
                url=getattr(btn, "url", None),
                custom_emoji_id=custom_emoji_id or (
                    str(style_icon) if style_icon else None),
                message_id=message_id,
                style_bg_primary=bool(getattr(style, "bg_primary", False)),
                style_bg_success=bool(getattr(style, "bg_success", False)),
                style_bg_danger=bool(getattr(style, "bg_danger", False)),
                style_icon_id=str(style_icon) if style_icon else None,
                requires_password=requires_password,
            ))
    return out


def is_force_reply(reply_markup) -> bool:
    return type(reply_markup).__name__ in ("ReplyForceReply", "ReplyKeyboardForceReply")


def capture_message(
    msg,
    bot: str,
    event_type: str,
    state: State | None = None,
    version: int | None = None,
) -> MessageCapture:
    """Собирает MessageCapture. version: из state (next) или явно."""
    chat_id = int(getattr(msg, "chat_id", 0) or getattr(getattr(msg, "chat", None), "id", 0) or 0)
    message_id = int(getattr(msg, "id", 0) or 0)
    if version is None and state is not None:
        version = state.next_message_version(bot, chat_id, message_id)
    version = version or 1
    text = getattr(msg, "message", None) or ""
    entities = getattr(msg, "entities", None) or []
    reply_markup = getattr(msg, "reply_markup", None)
    media = extract_media(msg)
    entity_infos = build_entity_infos(text, entities)
    return MessageCapture(
        bot=bot, chat_id=chat_id, message_id=message_id, version=version,
        event_type=event_type,
        captured_at=datetime.now(timezone.utc).isoformat(),
        raw_text=text,
        html=render_html(text, entities),
        date=_iso(getattr(msg, "date", None)),
        edit_date=_iso(getattr(msg, "edit_date", None)),
        reply_to_msg_id=getattr(msg, "reply_to_msg_id", None),
        entities=entity_infos,
        media=media,
        emojis=extract_emojis(text),
        has_force_reply=is_force_reply(reply_markup),
    )
