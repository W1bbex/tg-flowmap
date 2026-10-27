"""Регрессионные тесты исправлений аудита (Round 5):
- Унарный оператор 'not' в evaluate_ast_node
- Защита от TypeError (unhashable types) при обращении к dict.get и Subscript
- aiogram 3 CallbackData с методом .pack()
- Сохранение метаданных кнопок в list comprehension (url, style, emoji_id)
"""

import ast
import pytest
from pathlib import Path

from tg_flowmap.models import Button
from tg_flowmap.sast.evaluator import evaluate_ast_node
from tg_flowmap.sast.parser import AstParser


def test_evaluator_unary_not():
    """Проверка корректности вычисления унарного 'not'."""
    node_not_true = ast.parse("not True", mode="eval").body
    assert evaluate_ast_node(node_not_true) is False

    node_not_false = ast.parse("not False", mode="eval").body
    assert evaluate_ast_node(node_not_false) is True

    node_not_zero = ast.parse("not 0", mode="eval").body
    assert evaluate_ast_node(node_not_zero) is True

    node_not_str = ast.parse("not 'hello'", mode="eval").body
    assert evaluate_ast_node(node_not_str) is False


def test_evaluator_unhashable_types_graceful_handling():
    """Проверка, что нехэшируемые типы (list, dict) не роняют evaluate_ast_node с TypeError."""
    local_vars = {"my_dict": {"a": 1, "b": 2}, "my_list": [1, 2, 3]}

    # dict.get with list as key
    node_get = ast.parse("my_dict.get(my_list, 'default_val')", mode="eval").body
    assert evaluate_ast_node(node_get, local_vars) == "default_val"

    # Subscript with list as key: my_dict[my_list]
    node_sub = ast.parse("my_dict[my_list]", mode="eval").body
    assert evaluate_ast_node(node_sub, local_vars) is None


def test_aiogram3_callback_pack_parsing(tmp_path: Path):
    """Проверка извлечения имени фабрики при вызове MyCallback(action='pay').pack()."""
    code = (
        "from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup\n\n"
        "def get_kb():\n"
        "    buttons = [\n"
        "        [InlineKeyboardButton(\n"
        "            text='PayNow',\n"
        "            callback_data=OrderCallback(action='pay', order_id=42).pack(),\n"
        "        )]\n"
        "    ]\n"
        "    return InlineKeyboardMarkup(inline_keyboard=buttons)\n"
    )
    test_file = tmp_path / "bot_pack.py"
    test_file.write_text(code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(test_file)

    found_btn = None
    for kb in parser.keyboards.values():
        for row in kb.rows:
            for b in row:
                if b.text == "PayNow":
                    found_btn = b
                    break
    assert found_btn is not None
    assert found_btn.callback_data == "OrderCallback:pay"


def test_button_comprehension_metadata_preserved(tmp_path: Path):
    """Проверка сохранения url, style, icon_custom_emoji_id при генерации из list comprehension."""
    code = (
        "CATEGORIES = ['Clothes', 'Shoes']\n\n"
        "def get_kb():\n"
        "    buttons = [\n"
        "        InlineKeyboardButton(\n"
        "            text=cat,\n"
        "            callback_data='cat_select',\n"
        "            url='https://example.com',\n"
        "            icon_custom_emoji_id='54321',\n"
        "        )\n"
        "        for cat in CATEGORIES\n"
        "    ]\n"
        "    return InlineKeyboardMarkup(inline_keyboard=[buttons])\n"
    )
    test_file = tmp_path / "bot_comp.py"
    test_file.write_text(code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(test_file)

    all_btns = []
    for kb in parser.keyboards.values():
        for row in kb.rows:
            all_btns.extend(row)

    assert len(all_btns) >= 2
    for b in all_btns:
        assert b.callback_data == "cat_select"
        assert b.url == "https://example.com"
        assert b.icon_custom_emoji_id == "54321"
