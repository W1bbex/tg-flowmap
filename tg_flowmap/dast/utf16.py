"""UTF-16 утилиты: entities Telegram используют offsets в UTF-16 code units."""

from __future__ import annotations


def utf16_length(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def char_index_for_utf16(text: str, u16_index: int) -> int:
    """Индекс Python-символа для UTF-16 offset (учитывает astral-символы)."""
    if u16_index <= 0:
        return 0
    units = 0
    for i, ch in enumerate(text):
        if units >= u16_index:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
    return len(text)


def utf16_slice(text: str, offset: int, length: int) -> str:
    """Точный срез текста по UTF-16 offset/length (как это делает Telegram)."""
    start = char_index_for_utf16(text, offset)
    end = char_index_for_utf16(text, offset + length)
    return text[start:end]


def utf16_offset_of_char(text: str, char_index: int) -> int:
    """UTF-16 offset для индекса Python-символа."""
    units = 0
    for i, ch in enumerate(text):
        if i >= char_index:
            return units
        units += 2 if ord(ch) > 0xFFFF else 1
    return units
