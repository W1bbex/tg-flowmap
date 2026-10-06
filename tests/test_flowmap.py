from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import pytest

from tg_flowmap.analyzer import GraphAnalyzer
from tg_flowmap.cli import run_analysis
from tg_flowmap.models import Button, Keyboard, MessageNode
from tg_flowmap.parser import AstParser
from tg_flowmap.visualizer import HtmlVisualizer


SAMPLE_BOT_CODE = '''
def main_menu():
    buttons = [
        [{"text": "Настройки", "callback_data": "settings"}],
        [{"text": "Помощь", "callback_data": "help"}],
        [{"text": "Сайт", "url": "https://example.com"}],
        [{"text": "Битая кнопка", "callback_data": "nowhere"}],
    ]
    return {"inline_keyboard": buttons}

def settings_menu():
    return {
        "inline_keyboard": [
            [{"text": "Звук", "callback_data": "volume:50"}],
            [{"text": "« Назад", "callback_data": "menu"}],
        ]
    }

def broken_emoji_menu():
    return {
        "inline_keyboard": [
            [{"text": "Ошибка", "callback_data": "settings", "icon_custom_emoji_id": "None"}],
            [{"text": "Длинный коллбек", "callback_data": "x" * 70}],
        ]
    }

def handle_update(data):
    if data == "menu":
        send_message("Главное меню", reply_markup=main_menu())
    elif data == "settings":
        send_message("Экран настроек", reply_markup=settings_menu())
    elif data.startswith("volume:"):
        send_message("Громкость изменена")
'''


def test_parser_extracts_keyboards_and_handlers():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_BOT_CODE)
        temp_path = Path(f.name)

    try:
        parser = AstParser()
        parser.parse_file(temp_path)

        assert "main_menu" in parser.keyboards
        assert "settings_menu" in parser.keyboards
        assert "broken_emoji_menu" in parser.keyboards

        # Check main_menu has 4 buttons
        kb = parser.keyboards["main_menu"]
        assert len(kb.all_buttons()) == 4

        # Check nodes extracted
        assert "cb:menu" in parser.nodes
        assert "cb:settings" in parser.nodes
        assert "cb:volume:*" in parser.nodes
    finally:
        temp_path.unlink(missing_ok=True)


def test_analyzer_detects_dead_ends_and_broken_emojis():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_BOT_CODE)
        temp_path = Path(f.name)

    try:
        parser = AstParser()
        parser.parse_file(temp_path)

        analyzer = GraphAnalyzer(parser.nodes, parser.keyboards)
        bot_map = analyzer.build_map()

        # Check dead end on "nowhere"
        dead_ends = [i for i in bot_map.issues if i.issue_type == "dead_end"]
        assert len(dead_ends) >= 1
        assert any("nowhere" in i.message for i in dead_ends)

        # Check dynamic route volume:* is resolved (not a dead end)
        assert not any("volume" in i.message for i in dead_ends)

        # Check broken emoji in broken_emoji_menu when assigned to a node
        node_with_broken = MessageNode(
            id="cb:broken_test",
            title="broken_test",
            keyboard=parser.keyboards["broken_emoji_menu"],
        )
        test_nodes = dict(parser.nodes)
        test_nodes["cb:broken_test"] = node_with_broken

        analyzer2 = GraphAnalyzer(test_nodes, parser.keyboards)
        bot_map2 = analyzer2.build_map()

        emoji_issues = [i for i in bot_map2.issues if i.issue_type == "null_emoji"]
        assert len(emoji_issues) >= 1
        assert "icon_custom_emoji_id" in emoji_issues[0].message

        len_issues = [i for i in bot_map2.issues if i.issue_type == "callback_too_long"]
        assert len(len_issues) >= 1
    finally:
        temp_path.unlink(missing_ok=True)


def test_visualizer_renders_valid_html():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_BOT_CODE)
        temp_path = Path(f.name)

    out_html = temp_path.parent / "test_out.html"
    try:
        parser = AstParser()
        parser.parse_file(temp_path)
        analyzer = GraphAnalyzer(parser.nodes, parser.keyboards)
        bot_map = analyzer.build_map()

        vis = HtmlVisualizer(bot_map)
        vis.render(out_html)

        assert out_html.exists()
        content = out_html.read_text(encoding="utf-8")
        assert "canvas-world" in content
        assert "tg-card" in content
        assert "tg-flowmap" in content
        assert "cb:menu" in content
    finally:
        temp_path.unlink(missing_ok=True)
        out_html.unlink(missing_ok=True)


def test_cli_execution():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_BOT_CODE)
        temp_path = Path(f.name)

    out_html = temp_path.parent / "cli_test_out.html"
    out_json = temp_path.parent / "cli_test_out.json"
    try:
        code = run_analysis(temp_path, output_html=out_html, output_json=out_json, strict=False)
        assert code == 0
        assert out_html.exists()
        assert out_json.exists()
    finally:
        temp_path.unlink(missing_ok=True)
        out_html.unlink(missing_ok=True)
        out_json.unlink(missing_ok=True)


def test_dir_parsing_with_cross_file_references():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ui_file = tmp_path / "ui.py"
        bot_file = tmp_path / "bot.py"

        ui_file.write_text(
            '''
class BotUI:
    def back_button(self, target="menu"):
        return [{"text": "« Назад", "callback_data": target}]

    def dashboard_markup(self):
        return {
            "inline_keyboard": [
                [{"text": "Профиль", "callback_data": "profile"}],
                self.back_button("menu"),
            ]
        }
''',
            encoding="utf-8",
        )

        bot_file.write_text(
            '''
from ui import BotUI

ui = BotUI()

def handle_update(data):
    if data == "menu":
        send_message("Главное меню", reply_markup=ui.dashboard_markup())
    elif data == "profile":
        send_message("Ваш профиль")
''',
            encoding="utf-8",
        )

        parser = AstParser()
        parser.parse_dir(tmp_path)

        assert "dashboard_markup" in parser.keyboards
        assert "cb:menu" in parser.nodes
        assert "cb:profile" in parser.nodes

        analyzer = GraphAnalyzer(parser.nodes, parser.keyboards)
        bot_map = analyzer.build_map()

        assert len(bot_map.nodes) == 2
        # Edges from cb:menu -> cb:profile and back to cb:menu
        profile_edge = next((e for e in bot_map.edges if e.callback_data == "profile"), None)
        assert profile_edge is not None
        assert profile_edge.to_node_id == "cb:profile"
        assert profile_edge.status == "ok"


def test_match_case_routing():
    code = '''
def handle(data):
    match data:
        case "tab_one":
            send_message("Первая вкладка")
        case "tab_two":
            send_message("Вторая вкладка")
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        p = Path(f.name)

    try:
        parser = AstParser()
        parser.parse_file(p)
        assert "cb:tab_one" in parser.nodes
        assert "cb:tab_two" in parser.nodes
    finally:
        p.unlink(missing_ok=True)


def test_builder_and_reply_markup_support():
    code = '''
from aiogram import Router, types
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.filters import Command

router = Router()

@router.message(Command("start"))
async def start_handler(msg: types.Message):
    builder = ReplyKeyboardBuilder()
    builder.button(text="Локация", request_location=True)
    builder.button(text="Контакт", request_contact=True)
    await msg.answer("Привет", reply_markup=builder.as_markup(resize_keyboard=True))

@router.callback_query(lambda c: c.data == "help")
async def help_handler(cb: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="start")
    await cb.message.edit_text("Помощь", reply_markup=builder.as_markup())
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        p = Path(f.name)

    try:
        parser = AstParser()
        parser.parse_file(p)
        assert "cmd:/start" in parser.nodes
        assert "cb:help" in parser.nodes

        start_node = parser.nodes["cmd:/start"]
        assert start_node.keyboard is not None
        assert start_node.keyboard.keyboard_type == "reply"

        analyzer = GraphAnalyzer(parser.nodes, parser.keyboards)
        bot_map = analyzer.build_map()

        # Reply buttons should not trigger invalid_button errors
        invalid_btn_issues = [i for i in bot_map.issues if i.issue_type == "invalid_button"]
        assert len(invalid_btn_issues) == 0
    finally:
        p.unlink(missing_ok=True)


def test_screen_deduplication_and_aliases():
    code = '''
def main_menu():
    return {"inline_keyboard": [[{"text": "LED", "callback_data": "led_menu"}]]}

def led_markup():
    return {"inline_keyboard": [[{"text": "Вкл", "callback_data": "led_on"}]]}

def handle(data, text):
    if text == "/start":
        send_message("Старт", reply_markup=main_menu())
    elif data == "menu":
        send_message("Меню", reply_markup=main_menu())
    elif text == "/led":
        send_message("LED Меню", reply_markup=led_markup())
    elif data == "led_menu":
        send_message("LED Меню", reply_markup=led_markup())
    elif data == "console_close":
        send_message("Возврат", reply_markup=main_menu())
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        p = Path(f.name)

    try:
        parser = AstParser()
        parser.parse_file(p)

        # /led should be merged into cb:led_menu
        assert "cmd:/led" not in parser.nodes
        assert "cb:led_menu" in parser.nodes
        assert "/led" in parser.nodes["cb:led_menu"].aliases

        # console_close should be converted to callback returning to hub
        assert "cb:console_close" in parser.nodes
        assert parser.nodes["cb:console_close"].node_type == "callback"
        assert "cb:console_close" in parser.hub_return_nodes

        analyzer = GraphAnalyzer(
            parser.nodes,
            parser.keyboards,
            screen_aliases=parser.screen_aliases,
            hub_return_nodes=parser.hub_return_nodes,
        )
        bot_map = analyzer.build_map()

        # Check return edge from console_close to cb:menu exists
        return_edges = [e for e in bot_map.edges if e.from_node_id == "cb:console_close" and e.to_node_id == "cb:menu"]
        assert len(return_edges) == 1
        assert return_edges[0].is_back is True

        # Check duplicate screens are reported for menu vs /start sharing main_menu
        dup_issues = [i for i in bot_map.issues if i.issue_type == "duplicate_screen"]
        assert len(dup_issues) >= 1
    finally:
        p.unlink(missing_ok=True)


