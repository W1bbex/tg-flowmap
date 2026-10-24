"""Entity→HTML рендер текста Telegram (offsets в UTF-16, astral-безопасно).

Поддержка: bold, italic, underline, strike, code, pre(+language), spoiler,
blockquote, expandable_blockquote, text_url/url, custom_emoji (<tg-emoji>).
Неизвестные типы entities не ломают рендер (текст без тега).
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from .utf16 import char_index_for_utf16


@dataclass
class _Span:
    start: int
    end: int
    etype: str
    entity: object


_SIMPLE_TAGS = {
    "MessageEntityBold": ("<b>", "</b>"),
    "MessageEntityItalic": ("<i>", "</i>"),
    "MessageEntityUnderline": ("<u>", "</u>"),
    "MessageEntityStrike": ("<s>", "</s>"),
    "MessageEntityCode": ("<code>", "</code>"),
    "MessageEntitySpoiler": ("<tg-spoiler>", "</tg-spoiler>"),
}
# Telethon 1.44: expandable quote = MessageEntityBlockquote(collapsed=True)
_BLOCKQUOTE_TAGS = {
    False: ("<blockquote>", "</blockquote>"),
    True: ('<blockquote expandable>', "</blockquote>"),
}


def _safe_href(url: str) -> str:
    u = (url or "").strip()
    if u.lower().startswith(("http://", "https://", "tg://")):
        return html.escape(u, quote=True)
    return "#"


def _open_tag(span: _Span, text: str) -> str:
    etype = span.etype
    if etype in _SIMPLE_TAGS:
        return _SIMPLE_TAGS[etype][0]
    if etype == "MessageEntityBlockquote":
        return _BLOCKQUOTE_TAGS[bool(getattr(span.entity, "collapsed", False))][0]
    if etype == "MessageEntityPre":
        lang = getattr(span.entity, "language", None)
        if lang:
            return f'<pre><code class="language-{html.escape(str(lang))}">'
        return "<pre>"
    if etype == "MessageEntityTextUrl":
        url = getattr(span.entity, "url", None) or ""
        return f'<a href="{_safe_href(url)}">'
    if etype == "MessageEntityUrl":
        inner = text[span.start:span.end]
        return f'<a href="{_safe_href(inner)}">'
    if etype == "MessageEntityCustomEmoji":
        doc_id = getattr(span.entity, "document_id", None)
        if doc_id is not None:
            return f'<tg-emoji emoji-id="{html.escape(str(doc_id), quote=True)}">'
        return "<tg-emoji>"
    return ""


def _close_tag(span: _Span) -> str:
    etype = span.etype
    if etype in _SIMPLE_TAGS:
        return _SIMPLE_TAGS[etype][1]
    if etype == "MessageEntityBlockquote":
        return _BLOCKQUOTE_TAGS[bool(getattr(span.entity, "collapsed", False))][1]
    if etype == "MessageEntityPre":
        lang = getattr(span.entity, "language", None)
        return "</code></pre>" if lang else "</pre>"
    if etype in ("MessageEntityTextUrl", "MessageEntityUrl"):
        return "</a>"
    if etype == "MessageEntityCustomEmoji":
        return "</tg-emoji>"
    return ""


def _to_spans(text: str, entities) -> list[_Span]:
    spans: list[_Span] = []
    for e in entities or []:
        off, ln = int(getattr(e, "offset", 0)), int(getattr(e, "length", 0))
        start = char_index_for_utf16(text, off)
        end = char_index_for_utf16(text, off + ln)
        if end <= start or start >= len(text):
            continue
        end = min(end, len(text))
        spans.append(_Span(start, end, type(e).__name__, e))
    # вложенность: сначала внешние (старт раньше, длиннее)
    spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
    # делаем span'ы корректно вложенными (clamp к родителю)
    stack: list[_Span] = []
    fixed: list[_Span] = []
    for s in spans:
        while stack and stack[-1].end <= s.start:
            stack.pop()
        if stack and s.end > stack[-1].end:
            s.end = stack[-1].end
        if s.end <= s.start:
            continue
        fixed.append(s)
        stack.append(s)
    return fixed


def _build(text: str, spans: list[_Span], lo: int, hi: int) -> str:
    out: list[str] = []
    pos = lo
    i = 0
    while i < len(spans):
        s = spans[i]
        out.append(html.escape(text[pos:s.start]))
        # все span'ы, лежащие внутри s (они уже корректно вложены)
        j = i + 1
        children: list[_Span] = []
        while j < len(spans) and spans[j].start < s.end:
            children.append(spans[j])
            j += 1
        inner = _build(text, children, s.start, s.end)
        out.append(_open_tag(s, text) + inner + _close_tag(s))
        pos = s.end
        i = j
    out.append(html.escape(text[pos:hi]))
    return "".join(out)


def render_html(text: str, entities) -> str:
    """text — сырой текст, entities — список TL MessageEntity."""
    if not text:
        return ""
    spans = _to_spans(text, entities)
    return _build(text, spans, 0, len(text))
