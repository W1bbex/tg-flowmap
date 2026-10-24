"""Общие фикстуры и фейковые объекты для офлайн-тестов."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tg_flowmap.dast.config import Config  # noqa: E402
from tg_flowmap.dast.crawler import BotCrawler  # noqa: E402
from tg_flowmap.dast.models import CallbackResult, PressOutcome  # noqa: E402
from tg_flowmap.dast.safety import SafetyFilter  # noqa: E402
from tg_flowmap.dast.state import State  # noqa: E402
from tg_flowmap.dast.timeline_log import ActionLogger, TimelineWriter  # noqa: E402

from telethon.tl.types import (  # noqa: E402
    KeyboardButton,
    KeyboardButtonCallback,
    KeyboardButtonRow,
    KeyboardButtonUrl,
    PeerUser,
    ReplyInlineMarkup,
    ReplyKeyboardMarkup,
)

CHAT_ID = 777


class FakeMessage:
    """Duck-typed аналог Telethon Message."""

    def __init__(self, id, text, entities=None, reply_markup=None,
                 photo=None, document=None, edit_date=None, reply_to=None,
                 chat_id=CHAT_ID, date=None, out=False):
        self.id = id
        self.message = text
        self.entities = entities or []
        self.reply_markup = reply_markup
        self.chat_id = chat_id
        self.chat = PeerUser(user_id=chat_id)
        self.date = date or datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        self.edit_date = edit_date
        self.reply_to_msg_id = reply_to
        self.photo = photo
        self.document = document
        self.video = None
        self.animation = None
        self.voice = None
        self.audio = None
        self.sticker = None
        self.web_preview = None
        self.media = None
        self.out = out  # True = исходящее (наш собственный запрос боту)


def inline_markup(spec: list[list[tuple | dict]]):
    """spec: список рядов; элемент — (label, data_bytes) | (label, data, 'url', url)
    | dict(text=..., url=...)."""
    rows = []
    for row in spec:
        btns = []
        for item in row:
            if isinstance(item, dict):
                btns.append(KeyboardButtonUrl(text=item.get("text", ""),
                                              url=item.get("url", "")))
                continue
            label, data = item[0], item[1]
            if len(item) >= 3 and item[2] == "url":
                btns.append(KeyboardButtonUrl(text=label, url=item[3] or ""))
            else:
                btns.append(KeyboardButtonCallback(text=label, data=data))
        rows.append(KeyboardButtonRow(buttons=btns))
    return ReplyInlineMarkup(rows=rows)


def reply_markup(labels: list[list[str]]):
    rows = [KeyboardButtonRow(buttons=[KeyboardButton(text=l) for l in row])
            for row in labels]
    return ReplyKeyboardMarkup(rows=rows, resize=None, single_use=None,
                               selective=None, placeholder=None, is_persistent=None)


class FakeNavigator:
    """Скриптованный навигатор: переходы по callback_data.

    transitions: {callback_data: {"kind": "edit"|"new"|"answer_only"|"timeout",
                                   "msg": FakeMessage|None,
                                   "callback": CallbackResult|None}}
    При send_start возвращается start_msg (или значения из списка start_sequence).
    """

    def __init__(self, start_msg, transitions, start_sequence=None,
                 on_press=None):
        self.start_msg = start_msg
        self.transitions = transitions
        self.start_iter = iter(start_sequence or [])
        self.presses: list[bytes] = []
        self.starts = 0
        self.on_press = on_press

    async def send_start(self):
        self.starts += 1
        try:
            msg = next(self.start_iter)
        except StopIteration:
            msg = self.start_msg
        if msg is None:
            return PressOutcome(kind="timeout")
        return PressOutcome(kind="new", message=msg)

    async def press_button(self, button, message_id):
        self.presses.append(button.callback_data)
        if self.on_press is not None:
            override = self.on_press(button, message_id)
            if override is not None:
                return override
        spec = self.transitions.get(button.callback_data)
        if spec is None:
            return PressOutcome(kind="timeout", action_id="fake")
        kind = spec.get("kind", "edit")
        msg = spec.get("msg")
        cb = spec.get("callback")
        extras = [tuple(e) for e in (spec.get("extras") or [])]
        return PressOutcome(kind=kind, message=msg, callback=cb, action_id="fake",
                            extra_messages=extras)

    async def send_text(self, text, why="manual_answer"):
        self.sent_texts = list(getattr(self, "sent_texts", [])) + [text]
        if getattr(self, "text_msg", None) is not None:
            return PressOutcome(kind="new", message=self.text_msg)
        return PressOutcome(kind="timeout")

    async def download_media(self, msg, media_dir):
        return None


def make_crawler(cfg, state, nav, bot="@fake_bot", tmp_path=None):
    writer = TimelineWriter((tmp_path or cfg.root) / f"timeline_{bot}.jsonl")
    logger = ActionLogger(state, writer)
    safety = SafetyFilter(cfg)
    return BotCrawler(cfg, state, logger, safety, nav, {}, bot,
                      media_dir=(tmp_path or cfg.root) / "media"), writer


@pytest.fixture
def cfg(tmp_path):
    return Config(
        root=tmp_path,
        delay_min=0.01, delay_max=0.02,
        wait_response_timeout=0.5, wait_stabilization=0.05,
        start_cooldown=0.0, max_depth=4, max_actions_per_bot=100,
    )


@pytest.fixture
def state(cfg):
    s = State(cfg.db_path)
    yield s
    s.close()
