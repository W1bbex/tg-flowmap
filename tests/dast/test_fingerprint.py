"""Тесты canonical fingerprint (без parent_id) и route_fingerprint."""

from tg_flowmap.dast.config import DEFAULT_VOLATILE_PATTERNS
from tg_flowmap.dast.fingerprint import (
    buttons_signature,
    entities_signature,
    normalize_text,
    route_fingerprint,
    screen_fingerprint,
    screen_id_of,
)
import re


def compiled():
    return [re.compile(p) for p in DEFAULT_VOLATILE_PATTERNS]


BUTTONS = [
    {"row": 0, "col": 0, "label": "Catalog", "button_type": "callback",
     "callback_data": b"cat", "url": None},
    {"row": 0, "col": 1, "label": "Profile", "button_type": "callback",
     "callback_data": b"prof", "url": None},
]
ENTITIES = [{"type": "MessageEntityBold", "offset": 0, "length": 4}]
MEDIA = [{"kind": "photo", "tg_id": "111"}]


def test_same_screen_same_fingerprint():
    args = ("Main menu", ENTITIES, BUTTONS, MEDIA, compiled())
    assert screen_fingerprint(*args) == screen_fingerprint(*args)


def test_fingerprint_stable_regardless_of_parent():
    """canonical fingerprint НЕ зависит от родителя (поправка ТЗ №1)."""
    fp1 = screen_fingerprint("Main menu", ENTITIES, BUTTONS, MEDIA, compiled())
    fp2 = screen_fingerprint("Main menu", ENTITIES, BUTTONS, MEDIA, compiled())
    assert fp1 == fp2
    # route_fingerprint зависит от родителя/пути
    rf_a = route_fingerprint(fp1, None, None)
    rf_b = route_fingerprint(fp1, "r_parent", "Catalog")
    assert rf_a != rf_b
    assert screen_id_of(fp1).startswith("s_")


def test_different_buttons_different_fingerprint():
    fp1 = screen_fingerprint("Main menu", ENTITIES, BUTTONS, MEDIA, compiled())
    changed = [dict(b) for b in BUTTONS] + [
        {"row": 1, "col": 0, "label": "Support", "button_type": "callback",
         "callback_data": b"sup", "url": None}]
    fp2 = screen_fingerprint("Main menu", ENTITIES, changed, MEDIA, compiled())
    assert fp1 != fp2


def test_different_callback_data_different_fingerprint():
    """Случайный/разный callback_data при одинаковой структуре не создаёт новый canonical экран."""
    b100 = [dict(BUTTONS[0], callback_data=b"item_100")]
    b300 = [dict(BUTTONS[0], callback_data=b"item_300")]
    fp1 = screen_fingerprint("Card $100", [], b100, [], compiled())
    fp2 = screen_fingerprint("Card $300", [], b300, [], compiled())
    assert fp1 == fp2, "random callback при одинаковом экране не должен менять canonical screen fingerprint"


def test_volatile_text_differences_same_screen():
    """Динамические остатки/цены/даты не создают новый canonical экран."""
    fp1 = screen_fingerprint("Остаток: 5 штук", [], BUTTONS, [], compiled())
    fp2 = screen_fingerprint("Остаток: 7 штук", [], BUTTONS, [], compiled())
    assert fp1 == fp2


def test_volatile_price_same_screen_same_callbacks():
    fp1 = screen_fingerprint("Card: $100", [], BUTTONS, [], compiled())
    fp2 = screen_fingerprint("Card: $300", [], BUTTONS, [], compiled())
    assert fp1 == fp2


def test_normalize_text_collapses_whitespace_and_case():
    assert normalize_text("  Main   MENU \n text ") == "main menu text"


def test_entity_inside_volatile_dropped():
    """Entity, целиком попавший в вырезанный volatile-фрагмент, отбрасывается."""
    text = "Остаток: 5 штук"
    ents = [
        {"type": "MessageEntityBold", "offset": 8, "length": 1},   # внутри «5»
        {"type": "MessageEntityItalic", "offset": 10, "length": 4},  # «штук»
    ]
    sig = entities_signature(text, ents, compiled())
    types = [t for t, _, _ in sig]
    assert "MessageEntityBold" not in types
    assert "MessageEntityItalic" in types


def test_buttons_signature_rows_sorted():
    sig = buttons_signature(BUTTONS)
    assert sig == [[[0, "catalog", "callback", None, 0, 0, 0, "", 0],
                    [1, "profile", "callback", None, 0, 0, 0, "", 0]]]
