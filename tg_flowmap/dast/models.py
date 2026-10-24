"""Модели данных (dataclass), используемые обходчиком и отчётами."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field


def bytes_b64(data: bytes | None) -> str | None:
    return base64.b64encode(data).decode("ascii") if isinstance(data, (bytes, bytearray)) else None


def bytes_hex(data: bytes | None) -> str | None:
    return bytes(data).hex() if isinstance(data, (bytes, bytearray)) else None


@dataclass
class EntityInfo:
    """Один MessageEntity (offset/length — в UTF-16 code units, как у Telegram)."""

    type: str
    offset: int
    length: int
    url: str | None = None
    language: str | None = None
    document_id: int | None = None
    is_premium: bool = False
    order_index: int | None = None   # порядок Premium emoji в тексте
    symbol: str | None = None        # символ на позиции entity (utf-16 срез)
    collapsed: bool = False          # expandable blockquote (Telethon 1.44)

    def to_dict(self) -> dict:
        return {
            "type": self.type, "offset": self.offset, "length": self.length,
            "url": self.url, "language": self.language,
            "document_id": str(self.document_id) if self.document_id is not None else None,
            "is_premium": self.is_premium, "order_index": self.order_index,
            "symbol": self.symbol, "collapsed": self.collapsed,
        }


@dataclass
class MediaInfo:
    kind: str = "none"
    tg_id: str | None = None
    size: int | None = None
    file_path: str | None = None
    caption: str | None = None
    has_caption_entities: bool = False
    is_qr_candidate: bool = False  # документ-изображение с qr в имени/без текста — эвристика

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "tg_id": self.tg_id, "size": self.size,
            "file_path": self.file_path, "caption": self.caption,
            "has_caption_entities": self.has_caption_entities,
            "is_qr_candidate": self.is_qr_candidate,
        }


@dataclass
class MessageCapture:
    """Снимок одной версии сообщения (new/edit/snapshot)."""

    bot: str
    chat_id: int
    message_id: int
    version: int
    event_type: str                 # new | edit | snapshot
    captured_at: str                # ISO 8601
    raw_text: str
    html: str
    date: str | None
    edit_date: str | None
    reply_to_msg_id: int | None
    entities: list[EntityInfo] = field(default_factory=list)
    media: list[MediaInfo] = field(default_factory=list)
    emojis: list[dict] = field(default_factory=list)   # {symbol, utf16_offset}
    has_force_reply: bool = False

    def to_dict(self) -> dict:
        return {
            "bot": self.bot, "chat_id": self.chat_id, "message_id": self.message_id,
            "version": self.version, "event_type": self.event_type,
            "captured_at": self.captured_at, "raw_text": self.raw_text, "html": self.html,
            "date": self.date, "edit_date": self.edit_date,
            "reply_to_msg_id": self.reply_to_msg_id,
            "entities": [e.to_dict() for e in self.entities],
            "media": [m.to_dict() for m in self.media],
            "emojis": self.emojis,
            "has_force_reply": self.has_force_reply,
        }


@dataclass
class ButtonRef:
    """Кнопка, извлечённая из reply_markup сообщения."""

    row: int
    col: int
    label: str
    button_type: str                 # callback | reply | url | switch_inline | game | other
    callback_data: bytes | None = None
    url: str | None = None
    custom_emoji_id: str | None = None
    message_id: int | None = None    # сообщение, на котором висит кнопка
    blocked_reason: str | None = None
    db_id: int | None = None
    button_fp: str | None = None     # стабильный идентификатор для replay
    # --- стиль кнопки (Telethon 1.44: KeyboardButtonCallback.style / requires_password)
    style_bg_primary: bool = False
    style_bg_success: bool = False
    style_bg_danger: bool = False
    style_icon_id: str | None = None     # document_id иконки (Premium emoji)
    requires_password: bool = False      # кнопка требует пароль — всегда блокируется

    @property
    def callback_b64(self) -> str | None:
        return bytes_b64(self.callback_data)

    @property
    def callback_hex(self) -> str | None:
        return bytes_hex(self.callback_data)

    def to_dict(self) -> dict:
        return {
            "row": self.row, "col": self.col, "label": self.label,
            "button_type": self.button_type,
            "callback_data": self.callback_b64, "callback_hex": self.callback_hex,
            "url": self.url, "custom_emoji_id": self.custom_emoji_id,
            "message_id": self.message_id, "blocked_reason": self.blocked_reason,
            "db_id": self.db_id, "button_fp": self.button_fp,
            "style": {
                "bg_primary": self.style_bg_primary,
                "bg_success": self.style_bg_success,
                "bg_danger": self.style_bg_danger,
                "icon_document_id": self.style_icon_id,
                "requires_password": self.requires_password,
            },
        }


@dataclass
class CallbackResult:
    """Полный результат GetBotCallbackAnswerRequest."""

    message: str | None = None       # текст answer
    alert: bool = False
    url: str | None = None
    cache_time: int | None = None
    duration_ms: int | None = None
    exception: str | None = None
    raw: dict | None = None          # безопасно сериализованный raw TL объект

    def to_dict(self) -> dict:
        return {
            "message": self.message, "alert": self.alert, "url": self.url,
            "cache_time": self.cache_time, "duration_ms": self.duration_ms,
            "exception": self.exception, "raw": self.raw,
        }


@dataclass
class PressOutcome:
    """Результат одного действия навигатора."""

    kind: str                        # edit | new | answer_only | timeout | error
    message: object | None = None    # Telethon Message (или стаб) — до capture
    callback: CallbackResult | None = None
    duration_ms: int = 0
    extra_messages: list = field(default_factory=list)
    error: str | None = None
    action_id: str | None = None     # связь с timeline/callbacks

    @property
    def is_message_result(self) -> bool:
        return self.kind in ("edit", "new")


@dataclass
class ScreenRef:
    screen_id: str                   # s_<fp[:16]>
    fingerprint: str
    depth: int = 0
    requires_input: bool = False
    text_norm: str = ""


@dataclass
class StableAction:
    """Стабильный дескриптор действия на каноническом экране (без привязки к opaque callback_data)."""
    action_id: str
    source_screen_id: str
    row: int
    col: int
    label: str
    label_norm: str
    button_type: str
    style_bg_primary: bool = False
    style_bg_success: bool = False
    style_bg_danger: bool = False
    style_icon_id: str | None = None
    requires_password: bool = False
    url: str | None = None
    blocked_reason: str | None = None
    explored: bool = False

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "source_screen_id": self.source_screen_id,
            "row": self.row,
            "col": self.col,
            "label": self.label,
            "label_norm": self.label_norm,
            "button_type": self.button_type,
            "style_bg_primary": self.style_bg_primary,
            "style_bg_success": self.style_bg_success,
            "style_bg_danger": self.style_bg_danger,
            "style_icon_id": self.style_icon_id,
            "requires_password": self.requires_password,
            "url": self.url,
            "blocked_reason": self.blocked_reason,
            "explored": self.explored,
        }


@dataclass
class ButtonInstance:
    """Экземпляр кнопки конкретной версии сообщения с актуальным сырым callback_data."""
    message_rowid: int
    action_id: str
    row: int
    col: int
    label: str
    button_type: str
    callback_data: bytes | None = None
    callback_b64: str | None = None
    callback_hex: str | None = None
    url: str | None = None
    custom_emoji_id: str | None = None
    blocked_reason: str | None = None
    db_id: int | None = None
    style_bg_primary: bool = False
    style_bg_success: bool = False
    style_bg_danger: bool = False
    style_icon_id: str | None = None
    requires_password: bool = False

    def to_dict(self) -> dict:
        return {
            "db_id": self.db_id,
            "message_rowid": self.message_rowid,
            "action_id": self.action_id,
            "row": self.row,
            "col": self.col,
            "label": self.label,
            "button_type": self.button_type,
            "callback_data": self.callback_b64,
            "callback_hex": self.callback_hex,
            "url": self.url,
            "custom_emoji_id": self.custom_emoji_id,
            "blocked_reason": self.blocked_reason,
            "style": {
                "bg_primary": self.style_bg_primary,
                "bg_success": self.style_bg_success,
                "bg_danger": self.style_bg_danger,
                "icon_document_id": self.style_icon_id,
                "requires_password": self.requires_password,
            },
        }


@dataclass
class CrawlerMetrics:
    """Метрики эффективности graph-first навигации."""
    telegram_actions: int = 0
    callbacks_pressed: int = 0
    reply_buttons_pressed: int = 0
    text_answers_sent: int = 0
    start_count: int = 0
    recovery_start_count: int = 0
    successful_local_returns: int = 0
    replans: int = 0
    unstable_edges: int = 0
    avoided_replays: int = 0
    estimated_actions_saved: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "telegram_actions": self.telegram_actions,
            "callbacks_pressed": self.callbacks_pressed,
            "reply_buttons_pressed": self.reply_buttons_pressed,
            "text_answers_sent": self.text_answers_sent,
            "start_count": self.start_count,
            "recovery_start_count": self.recovery_start_count,
            "successful_local_returns": self.successful_local_returns,
            "replans": self.replans,
            "unstable_edges": self.unstable_edges,
            "avoided_replays": self.avoided_replays,
            "estimated_actions_saved": self.estimated_actions_saved,
        }

