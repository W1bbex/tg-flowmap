from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from tg_flowmap.analyzer import GraphAnalyzer
from tg_flowmap.ast_evaluator import evaluate_ast_node, extract_module_constants
from tg_flowmap.models import Button, Keyboard, MessageNode
from tg_flowmap.parser import AstParser
from tg_flowmap.visualizer import HtmlVisualizer


def test_local_vars_button_text_not_raw_ast():
    code = '''
def checkout_markup():
    pay_title = "Оплатить заказ"
    pay_cb = "pay_order"
    return {
        "inline_keyboard": [
            [{"text": pay_title, "callback_data": pay_cb}]
        ]
    }
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        p = Path(f.name)

    try:
        parser = AstParser()
        parser.parse_file(p)
        assert "checkout_markup" in parser.keyboards
        kb = parser.keyboards["checkout_markup"]
        btn = kb.rows[0][0]
        assert btn.text == "Оплатить заказ"
        assert btn.callback_data == "pay_order"
        assert "ast.Constant" not in btn.text
    finally:
        p.unlink(missing_ok=True)


def test_ann_assign_global_constants():
    code = '''
ICONS: dict[str, str] = {"fire": "🔥", "bolt": "⚡"}
APP_TITLE: str = "My Telegram Bot"

def menu():
    return {
        "inline_keyboard": [
            [{"text": ICONS.get("fire", "X"), "callback_data": "fire_action"}]
        ]
    }
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        p = Path(f.name)

    try:
        parser = AstParser()
        parser.parse_file(p)
        assert "ICONS" in parser.global_constants
        assert parser.global_constants["ICONS"]["fire"] == "🔥"
        assert "APP_TITLE" in parser.global_constants
        assert parser.global_constants["APP_TITLE"] == "My Telegram Bot"

        kb = parser.keyboards["menu"]
        assert kb.rows[0][0].text == "🔥"
    finally:
        p.unlink(missing_ok=True)


def test_catch_all_callback_does_not_mask_dead_ends():
    nodes = {
        "cb:menu": MessageNode(
            id="cb:menu",
            title="Menu",
            keyboard=Keyboard(
                name="menu_kb",
                rows=[
                    [Button(text="Valid", callback_data="valid_act")],
                    [Button(text="Broken", callback_data="non_existent_action")],
                ],
            ),
        ),
        "cb:valid_act": MessageNode(id="cb:valid_act", title="Valid Action"),
        "cb:*": MessageNode(id="cb:*", title="Catch All Fallback"),
    }
    analyzer = GraphAnalyzer(nodes, {})
    bot_map = analyzer.build_map()

    dead_ends = [i for i in bot_map.issues if i.issue_type == "dead_end"]
    # Broken button MUST still be detected as dead end even with cb:* present
    assert len(dead_ends) == 1
    assert "non_existent_action" in dead_ends[0].message


def test_back_button_heuristic_does_not_match_other_helpers():
    code = '''
def callback_button(label, target):
    return {"text": label, "callback_data": target}

def feedback_button():
    return {"text": "Оставить отзыв", "callback_data": "feedback"}

def back_button(target="menu"):
    return {"text": "« Назад", "callback_data": target}

def my_menu():
    return {
        "inline_keyboard": [
            [callback_button("Действие", "action")],
            [feedback_button()],
            back_button("menu"),
        ]
    }
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        p = Path(f.name)

    try:
        parser = AstParser()
        parser.parse_file(p)
        kb = parser.keyboards["my_menu"]
        buttons = kb.all_buttons()
        # callback_button must NOT be converted to "« Назад"
        cb_btn = next((b for b in buttons if b.callback_data == "action"), None)
        assert cb_btn is not None
        assert cb_btn.text == "Действие"

        # back_button must correctly produce "« Назад" to "menu"
        back_btn = next((b for b in buttons if b.text == "« Назад"), None)
        assert back_btn is not None
        assert back_btn.callback_data == "menu"
    finally:
        p.unlink(missing_ok=True)


def test_html_script_tag_escaping():
    nodes = {
        "cb:test": MessageNode(
            id="cb:test",
            title="XSS Test </script><script>alert(1)</script>",
            text_template="Dangerous content: </script><!-- test -->",
        )
    }
    analyzer = GraphAnalyzer(nodes, {})
    bot_map = analyzer.build_map()

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        out_html = Path(f.name)

    try:
        vis = HtmlVisualizer(bot_map)
        vis.render(out_html)
        content = out_html.read_text(encoding="utf-8")
        # Ensure raw </script> is NOT inside rawData script block
        assert "<\\/script>" in content
    finally:
        out_html.unlink(missing_ok=True)


def test_emoji_variable_does_not_trigger_null_emoji_error():
    nodes = {
        "cb:test": MessageNode(
            id="cb:test",
            title="Emoji Test",
            keyboard=Keyboard(
                name="emoji_kb",
                rows=[
                    [Button(text="Rocket", callback_data="launch", icon_custom_emoji_id="$ROCKET_EMOJI_ID")],
                ],
            ),
        )
    }
    analyzer = GraphAnalyzer(nodes, {})
    bot_map = analyzer.build_map()

    emoji_errors = [i for i in bot_map.issues if i.issue_type == "null_emoji"]
    assert len(emoji_errors) == 0


def test_reply_keyboard_text_routing():
    nodes = {
        "cmd:/start": MessageNode(
            id="cmd:/start",
            title="Start",
            keyboard=Keyboard(
                name="main_reply",
                keyboard_type="reply",
                rows=[
                    [Button(text="/help")],
                ],
            ),
        ),
        "cmd:/help": MessageNode(id="cmd:/help", title="Help Screen"),
    }
    analyzer = GraphAnalyzer(nodes, {})
    bot_map = analyzer.build_map()

    edges = [e for e in bot_map.edges if e.from_node_id == "cmd:/start" and e.to_node_id == "cmd:/help"]
    assert len(edges) == 1
    assert edges[0].button_text == "/help"


def test_reply_keyboard_back_button_detection():
    nodes = {
        "cb:settings": MessageNode(
            id="cb:settings",
            title="Settings",
            keyboard=Keyboard(
                name="settings_reply",
                keyboard_type="reply",
                rows=[
                    [Button(text="« Назад")],
                ],
            ),
        ),
        "cmd:/start": MessageNode(id="cmd:/start", title="Start Screen"),
    }
    analyzer = GraphAnalyzer(nodes, {})
    bot_map = analyzer.build_map()

    missing_backs = [i for i in bot_map.issues if i.issue_type == "missing_back" and i.node_id == "cb:settings"]
    assert len(missing_backs) == 0


def test_underscore_callback_prefix_resolution():
    nodes = {
        "cb:menu": MessageNode(
            id="cb:menu",
            title="Menu",
            keyboard=Keyboard(
                name="menu_kb",
                rows=[
                    [Button(text="Купить 42", callback_data="buy_42")],
                ],
            ),
        ),
        "cb:buy_*": MessageNode(id="cb:buy_*", title="Buy Handler"),
    }
    analyzer = GraphAnalyzer(nodes, {})
    bot_map = analyzer.build_map()

    edge = next(e for e in bot_map.edges if e.button_text == "Купить 42")
    assert edge.to_node_id == "cb:buy_*"
    assert edge.status == "dynamic"


def test_ast_evaluator_preserves_regular_lists_and_numbers():
    import ast
    # 1. Regular list
    list_expr = ast.parse("[1, 2, 3]", mode="eval").body
    res = evaluate_ast_node(list_expr, {})
    assert res == [1, 2, 3]

    # 2. Number cast
    int_expr = ast.parse("int('42')", mode="eval").body
    num_res = evaluate_ast_node(int_expr, {})
    assert num_res == 42
    assert isinstance(num_res, int)


def test_parser_finds_edit_text_dispatch():
    code = '''
def main_kb():
    return {"inline_keyboard": [[{"text": "OK", "callback_data": "ok"}]]}

@dp.callback_query(F.data == "refresh_data")
async def on_refresh(call: CallbackQuery):
    await call.message.edit_text("Обновлённый текст", reply_markup=main_kb())
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        p = Path(f.name)

    try:
        parser = AstParser()
        parser.parse_file(p)
        assert "cb:refresh_data" in parser.nodes
        node = parser.nodes["cb:refresh_data"]
        assert node.text_template == "Обновлённый текст"
        assert node.keyboard is not None
        assert node.keyboard.name == "main_kb"
    finally:
        p.unlink(missing_ok=True)


def test_strict_mode_fails_on_any_error_severity():
    from tg_flowmap.cli import run_analysis
    code = '''
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def bad_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        # 70 bytes exceeds Telegram 64 bytes callback_data limit
        [InlineKeyboardButton(text="Too Long", callback_data="a" * 70)]
    ])

@dp.message(Command("start"))
async def start_cmd(message):
    await message.answer("Hello", reply_markup=bad_kb())
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        p = Path(f.name)

    try:
        exit_code = run_analysis(p, strict=True)
        assert exit_code == 1
    finally:
        p.unlink(missing_ok=True)

