"""Тесты capture: entities, Premium emoji (UTF-16/astral), кнопки, медиа,
HTML-рендер. Всё офлайн на TL-фикстурах."""

import base64
from datetime import datetime, timezone

import pytest
from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityBlockquote,
    MessageEntityCode,
    MessageEntityCustomEmoji,
    MessageEntityPre,
    MessageEntitySpoiler,
    MessageEntityTextUrl,
)

from tg_flowmap.dast.capture import (
    build_entity_infos,
    capture_message,
    extract_buttons,
    extract_emojis,
)
from tg_flowmap.dast.html_render import render_html

try:
    from telethon.tl.types import MessageEntityExpandableBlockquote
except ImportError:  # старые слои Telethon
    MessageEntityExpandableBlockquote = None

from conftest import FakeMessage, inline_markup


def test_entities_full_fields():
    text = "Привет мир"
    ents = [
        MessageEntityBold(offset=0, length=6),
        MessageEntityTextUrl(offset=7, length=3, url="https://x.com/?a=1&b=2"),
        MessageEntityPre(offset=0, length=6, language="python"),
    ]
    infos = build_entity_infos(text, ents)
    assert infos[0].type == "MessageEntityBold"
    assert (infos[0].offset, infos[0].length) == (0, 6)
    assert infos[1].url == "https://x.com/?a=1&b=2"
    assert infos[2].language == "python"
    assert infos[0].is_premium is False


def test_premium_emoji_after_astral_symbol():
    """Premium emoji после astral-символа: точный UTF-16 offset и срез."""
    # 𝄞 U+1D11E (2 юнита), 👍 U+1F44D (2 юнита), 🎯 U+1F3AF (2 юнита)
    text = "𝄞👍🎯"
    ents = [MessageEntityCustomEmoji(offset=4, length=2, document_id=999000111)]
    infos = build_entity_infos(text, ents)
    assert len(infos) == 1
    e = infos[0]
    assert e.is_premium and e.document_id == 999000111
    assert e.offset == 4          # UTF-16 offset сохранён точно
    assert e.symbol == "🎯"       # точный utf-16 срез — не 👍 и не половина символа
    assert e.order_index == 0


def test_premium_emoji_order_index():
    text = "a🥇b🥈"
    ents = [
        MessageEntityCustomEmoji(offset=1, length=2, document_id=1),
        MessageEntityCustomEmoji(offset=4, length=2, document_id=2),
    ]
    infos = build_entity_infos(text, ents)
    assert [i.order_index for i in infos] == [0, 1]
    assert [i.symbol for i in infos] == ["🥇", "🥈"]


def test_regular_emoji_positions_utf16():
    # a👍b → 👍 на char-индексе 1 → utf16 offset 1
    assert extract_emojis("a👍b")[0] == {"symbol": "👍", "utf16_offset": 1}
    # 𝄞😀x → 😀 идёт после astral (2 юнита) → utf16 offset 2
    assert extract_emojis("𝄞😀x")[0] == {"symbol": "😀", "utf16_offset": 2}


def test_binary_callback_data_byte_for_byte():
    data = b"\x00\xff\x10\x7f"
    markup = inline_markup([[("Go", data)]])
    buttons = extract_buttons(markup, message_id=42)
    assert len(buttons) == 1
    b = buttons[0]
    assert b.button_type == "callback"
    assert b.callback_data == data                    # байт-в-байт, без изменений
    assert b.callback_hex == "00ff107f"
    assert b.callback_b64 == base64.b64encode(data).decode()
    assert (b.row, b.col, b.message_id) == (0, 0, 42)


def test_url_button_recorded_not_callback():
    markup = inline_markup([[{"text": "Наш канал", "url": "https://t.me/x"}]])
    b = extract_buttons(markup, 1)[0]
    assert b.button_type == "url"
    assert b.callback_data is None
    assert b.url == "https://t.me/x"


def test_capture_message_versions_and_dates(state):
    msg = FakeMessage(5, "text", entities=[MessageEntityBold(0, 4)],
                      date=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc))
    cap = capture_message(msg, "@b", "new", state=state)
    assert cap.version == 1 and cap.event_type == "new"
    assert cap.date.startswith("2026-01-02")
    state.insert_message(cap, "s_x")           # версия фиксируется вставкой
    cap2 = capture_message(msg, "@b", "edit", state=state)
    assert cap2.version == 2 and cap2.event_type == "edit"


def test_media_and_caption():
    class Photo:
        id = 555
    msg = FakeMessage(7, "подпись", photo=Photo())
    cap = capture_message(msg, "@b", "new")
    assert len(cap.media) == 1
    m = cap.media[0]
    assert m.kind == "photo" and m.tg_id == "555"
    assert m.caption == "подпись"           # подпись вместе с entities
    assert m.has_caption_entities is False


# ------------------------------------------------------------- HTML рендер
def test_html_bold_code():
    text = "bold code"
    ents = [MessageEntityBold(0, 4), MessageEntityCode(5, 4)]
    assert render_html(text, ents) == "<b>bold</b> <code>code</code>"


def test_html_spoiler_and_blockquote():
    assert render_html("secret", [MessageEntitySpoiler(0, 6)]) == \
        "<tg-spoiler>secret</tg-spoiler>"
    assert render_html("quote", [MessageEntityBlockquote(0, 5)]) == \
        "<blockquote>quote</blockquote>"
    if MessageEntityExpandableBlockquote is not None:
        assert render_html(
            "quote", [MessageEntityExpandableBlockquote(0, 5)]
        ) == '<blockquote expandable>quote</blockquote>'


def test_html_link_escapes_url():
    text = "abc"
    ents = [MessageEntityTextUrl(0, 3, url='https://a.b/?x=1&y="2"')]
    html = render_html(text, ents)
    assert html.startswith('<a href="https://a.b/?x=1&amp;y=&quot;2&quot;">')
    assert html.endswith(">abc</a>")


def test_html_custom_emoji_tag():
    text = "🎯x"
    ents = [MessageEntityCustomEmoji(0, 2, document_id=777)]
    assert render_html(text, ents) == '<tg-emoji emoji-id="777">🎯</tg-emoji>x'


def test_html_escapes_text():
    assert render_html("a<b>&c", [MessageEntityBold(0, 6)]) == \
        "<b>a&lt;b&gt;&amp;c</b>"


def test_html_nested_entities():
    text = "abcdef"
    ents = [MessageEntityBold(0, 6), MessageEntityCode(2, 3)]
    assert render_html(text, ents) == "<b>ab<code>cde</code>f</b>"


def test_html_astral_offsets():
    text = "𝄞bold"
    # utf16 offset 2 == char 1
    ents = [MessageEntityBold(2, 4)]
    assert render_html(text, ents) == "𝄞<b>bold</b>"
