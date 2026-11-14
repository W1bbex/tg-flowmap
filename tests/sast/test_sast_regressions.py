import ast
from pathlib import Path
import pytest
from run import clean_input_path
from tg_flowmap.sast.parser import AstParser
from tg_flowmap.sast.analyzer import GraphAnalyzer
from tg_flowmap.core.models import Button, MessageNode


def test_clean_input_path_windows_illegal_characters():
    """Verify clean_input_path does not crash on Windows illegal path characters."""
    assert clean_input_path("C:\\invalid*dir?:name<>|") is None
    assert clean_input_path("") is None
    assert clean_input_path("   ") is None


def test_ast_parser_circular_commands_recursion_guard():
    """Verify _parse_commands_list handles circular assignments without RecursionError."""
    source = """
COMMANDS = COMMANDS
"""
    tree = ast.parse(source)
    parser = AstParser()
    assign_node = tree.body[0].value
    parser._parse_commands_list(assign_node, tree)
    assert isinstance(parser.registered_menu_commands, set)


def test_ast_parser_callback_query_in_list():
    """Verify decorator parser recognizes F.data.in_([...]) routes."""
    source = """
@router.callback_query(F.data.in_(["profile_view", "profile_edit"]))
async def handle_profile(call):
    await call.message.answer("Profile")
"""
    tree = ast.parse(source)
    func_node = tree.body[0]
    parser = AstParser()
    parser._inspect_decorated_handler(func_node, Path("handlers.py"))

    assert "cb:profile_view" in parser.nodes
    assert "cb:profile_edit" in parser.nodes


def test_button_supports_web_app_and_switch_inline():
    code = """
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="App", web_app=WebAppInfo(url="https://app.com"))],
    [InlineKeyboardButton(text="Share", switch_inline_query="query")],
    [InlineKeyboardButton(text="Pay", pay=True)]
])
"""
    tree = ast.parse(code)
    parser = AstParser()
    parser.parse_file(Path("fake_bot.py"))
    parser._extract_keyboards(tree, Path("fake_bot.py"))

    assert "kb" in parser.keyboards
    buttons = parser.keyboards["kb"].all_buttons()
    assert len(buttons) == 3

    assert buttons[0].web_app is not None
    assert buttons[1].switch_inline_query == "query"
    assert buttons[2].pay is True

    node = MessageNode(id="cmd:/start", title="Start", keyboard=parser.keyboards["kb"])
    parser.nodes["cmd:/start"] = node
    analyzer = GraphAnalyzer(parser.nodes, parser.keyboards)
    bot_map = analyzer.build_map()
    invalid_issues = [i for i in bot_map.issues if i.issue_type == "invalid_button"]
    assert len(invalid_issues) == 0


def test_aiogram3_routes_with_dots_and_slashes(tmp_path: Path):
    bot_code = """
from aiogram import Router, F
from aiogram.types import CallbackQuery

router = Router()

@router.callback_query(F.data == "user.profile.edit")
async def edit_profile(call: CallbackQuery):
    pass

@router.callback_query(F.data.startswith("item/buy:"))
async def buy_item(call: CallbackQuery):
    pass
"""
    f = tmp_path / "bot_router.py"
    f.write_text(bot_code, encoding="utf-8")

    parser = AstParser()
    parser.parse_dir(tmp_path)

    assert "cb:user.profile.edit" in parser.nodes
    assert "cb:item/buy:*" in parser.nodes


def test_map_render_handles_null_confidence(tmp_path: Path):
    from tg_flowmap.dast.state import State
    from tg_flowmap.dast.map_render import generate_maps

    state = State(tmp_path / "test.db")
    bot = "@testbot"
    state.register_bot(bot)
    state.upsert_screen(bot, "s_1", "fp_1", 0, "Home", False)
    state.upsert_screen(bot, "s_2", "fp_2", 1, "Catalog", False)
    state.upsert_graph_edge(bot, {
        "source_screen_id": "s_1",
        "action_id": "act_null",
        "destination_screen_id": "s_2",
        "confidence": None,
        "is_stable": None,
        "observations_count": None,
    })

    maps = generate_maps(state, bot, tmp_path / "out")
    html_content = maps["html"].read_text(encoding="utf-8")
    assert "s_1" in html_content
    state.close()


def test_button_text_falsy_zero(tmp_path: Path):
    """Verify that integer zero '0' is preserved as button label and not replaced by 'Button'."""
    bot_code = """
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=0, callback_data="zero_call")],
    [{"text": 0, "callback_data": "dict_zero"}]
])
"""
    f = tmp_path / "bot_zero.py"
    f.write_text(bot_code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(f)

    assert "kb" in parser.keyboards
    buttons = parser.keyboards["kb"].all_buttons()
    assert len(buttons) == 2
    assert buttons[0].text == "0"
    assert buttons[1].text == "0"


def test_aiogram3_builder_fluent_chaining(tmp_path: Path):
    """Verify InlineKeyboardBuilder fluent method chaining (.button(...).button(...).adjust(...))."""
    bot_code = """
from aiogram.utils.keyboard import InlineKeyboardBuilder

def build_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="One", callback_data="btn_1").button(text="Two", callback_data="btn_2").adjust(2)
    return builder.as_markup()
"""
    f = tmp_path / "bot_builder.py"
    f.write_text(bot_code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(f)

    assert "build_menu" in parser.keyboards
    kb = parser.keyboards["build_menu"]
    assert len(kb.rows) == 1
    assert len(kb.rows[0]) == 2
    assert kb.rows[0][0].text == "One"
    assert kb.rows[0][0].callback_data == "btn_1"
    assert kb.rows[0][1].text == "Two"
    assert kb.rows[0][1].callback_data == "btn_2"


def test_ast_parser_route_conditions_constant_list(tmp_path: Path):
    """Verify routes are extracted when checking membership in a constant collection."""
    bot_code = """
ACTIONS = ["confirm_action", "cancel_action"]

async def handler(call):
    if call.data in ACTIONS:
        await call.message.answer("Handled")
"""
    f = tmp_path / "bot_routes.py"
    f.write_text(bot_code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(f)

    assert "cb:confirm_action" in parser.nodes
    assert "cancel_action" in parser.nodes["cb:confirm_action"].aliases


def test_keyboard_deduplicate_rows_preserves_cross_row_buttons():
    """Verify _deduplicate_rows preserves duplicate buttons across different rows (e.g. Back button)."""
    btn_back1 = Button(text="Back", callback_data="back")
    btn_back2 = Button(text="Back", callback_data="back")
    btn_item = Button(text="Item", callback_data="item")

    rows = [
        [btn_back1],
        [btn_item],
        [btn_back2],
    ]
    deduped = AstParser._deduplicate_rows(rows)
    assert len(deduped) == 3
    assert deduped[0][0].text == "Back"
    assert deduped[1][0].text == "Item"
    assert deduped[2][0].text == "Back"


def test_parse_file_records_oserror_in_skipped_files(tmp_path: Path):
    """Verify parse_file records OSError/missing files into skipped_files rather than silent return."""
    parser = AstParser()
    non_existent = tmp_path / "does_not_exist.py"
    parser.parse_file(non_existent)
    assert len(parser.skipped_files) == 1
    assert parser.skipped_files[0][0] == non_existent
