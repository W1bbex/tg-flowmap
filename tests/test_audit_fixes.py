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
