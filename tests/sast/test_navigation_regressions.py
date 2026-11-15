from __future__ import annotations

import ast
import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from tg_flowmap.core.comparator import BotComparator
from tg_flowmap.core.llm_exporter import generate_llm_benchmark_prompt
from tg_flowmap.dast.config import Config
from tg_flowmap.dast.models import ButtonRef, CallbackResult, PressOutcome
from tg_flowmap.dast.navigation_executor import NavigationExecutor
from tg_flowmap.dast.safety import SafetyFilter
from tg_flowmap.dast.screen_identity import match_button_instance
from tg_flowmap.dast.state import State
from tg_flowmap.sast.evaluator import evaluate_ast_node
from tg_flowmap.sast.parser import AstParser


def test_safety_tron_and_price_regex():
    """Verifies that TRON addresses and USD prices in buttons are blocked correctly."""
    cfg = Config()
    safety = SafetyFilter(cfg)

    # TRON wallet address
    tron_addr = "TEkxiTehnFdKuAAxjf3umKy6R123456789"
    ctx = safety.screen_context(f"Отправьте оплату на адрес: {tron_addr}")
    assert ctx["has_wallet"] is True
    assert safety.screen_is_sensitive(f"Отправьте оплату на адрес: {tron_addr}") is True

    # Price with action word in uppercase USD
    allowed, reason = safety.button_verdict("Купить 15 USD", "callback", "")
    assert allowed is False
    assert reason == "price_with_action_word"

    allowed_lower, reason_lower = safety.button_verdict("купить 15 usd", "callback", "")
    assert allowed_lower is False
    assert reason_lower == "price_with_action_word"


def test_navigator_outcome_cb_parameter():
    """Verifies PressOutcome callback parameter doesn't raise TypeError."""
    cb = CallbackResult(alert=False)
    outcome = PressOutcome(kind="error", action_id="a1", error="rpc_err", callback=cb)
    assert outcome.kind == "error"
    assert outcome.callback == cb


def test_state_exec_rollback_on_error(tmp_path: Path):
    """Ensures failed _exec rolls back implicit transaction and avoids OperationalError."""
    db_file = tmp_path / "rollback_test.db"
    state = State(db_file)
    state.register_bot("@test_bot")

    # Force a failure in _exec (FOREIGN KEY or invalid SQL)
    try:
        state._exec("INSERT INTO callbacks(bot, button_rowid) VALUES(?, ?)", ("@test_bot", 999999))
    except sqlite3.IntegrityError:
        pass

    # The next transaction MUST succeed without 'cannot start a transaction within a transaction'
    with state.transaction() as conn:
        conn.execute("INSERT INTO bots(username) VALUES(?)", ("@another_bot",))

    info = state.bot_info("@another_bot")
    assert info is not None
    state.close()


def test_navigation_executor_answer_only():
    """Ensures answer_only callback is treated as success without breaking graph step."""
    mock_nav = MagicMock()
    mock_outcome = PressOutcome(kind="answer_only", message=None, callback=CallbackResult(alert=True, message="Toast!"))
    mock_nav.press_button = AsyncMock(return_value=mock_outcome)
    executor = NavigationExecutor("@dummy", mock_nav, None, None)

    async def fake_observe(out):
        return None, None, None

    action = {"action_id": "act1", "label": "Click", "button_type": "callback", "row": 0, "col": 0}
    current_instances = [action]
    current_msg = MagicMock(id=100)

    result = asyncio.run(
        executor.execute_action_by_id(action, current_msg, current_instances, fake_observe)
    )
    assert result.success is True
    assert result.reason == "answer_only"
    assert result.outcome == mock_outcome


def test_parser_message_answer_vs_call_answer(tmp_path: Path):
    """Verifies that message.answer(...) extracts real screen text and is not degraded to toast."""
    code = """
@dp.message_handler(commands=['start'])
async def start_handler(message):
    await message.answer("Главное меню каталога", reply_markup=main_kb)
    await call.answer("Всплывающее уведомление", show_alert=True)
"""
    test_file = tmp_path / "bot_test.py"
    test_file.write_text(code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(test_file)
    assert len(parser.nodes) > 0
    assert any("Главное меню" in (n.text_template or n.title) for n in parser.nodes.values())
    node = parser.nodes["cmd:/start"]
    assert "Главное меню" in node.text_template
    assert node.is_alert is False


def test_screen_identity_match_button_with_sqlite_row():
    """Verifies that match_button_instance works properly when passed sqlite3.Row objects."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    cur = con.execute("SELECT 1 AS row, 0 AS col, 'Каталог' AS label, 'callback' AS button_type, '' AS style_icon_id")
    action_row = cur.fetchone()

    cur2 = con.execute("SELECT 1 AS row, 0 AS col, 'Каталог' AS label, 'callback' AS button_type, '' AS style_icon_id")
    inst_row = cur2.fetchone()

    matched, conf, reason = match_button_instance(action_row, [inst_row])
    assert matched is not None
    assert conf == 1.0
    assert reason == "exact_position_and_label"


def test_evaluator_subscript_dict_and_list():
    """Verifies that evaluate_ast_node evaluates dict and list subscripting."""
    tree = ast.parse("ROUTES['catalog']")
    local_vars = {"ROUTES": {"catalog": "screens.catalog", "help": "screens.help"}}
    result = evaluate_ast_node(tree.body[0].value, local_vars=local_vars)
    assert result == "screens.catalog"

    tree_list = ast.parse("BUTTONS[1]")
    local_vars_list = {"BUTTONS": ["back", "forward", "cancel"]}
    result_list = evaluate_ast_node(tree_list.body[0].value, local_vars=local_vars_list)
    assert result_list == "forward"


def test_llm_exporter_handles_none_buttons():
    """Ensures generate_llm_benchmark_prompt doesn't crash if buttons key is None or has dicts."""
    prompt = generate_llm_benchmark_prompt(
        bot_a_name="BotA",
        bot_a_metrics={"screens_count": 1, "buttons_count": 0},
        bot_b_name="BotB",
        bot_b_metrics={"screens_count": 1, "buttons_count": 1},
        bot_a_screens=[{"title": "Menu", "buttons": None}],
        bot_b_screens=[{"title": "Shop", "buttons": [{"label": "Buy", "row": 0}]}],
    )
    assert "BotA" in prompt
    assert "нет кнопок" in prompt
    assert "Buy" in prompt


def test_comparator_draw_status():
    """Verifies that equal metrics produce 'Ничья' instead of defaulting to BotA."""
    comparator = BotComparator(
        bot_a_name="BotA",
        bot_a_data={"screens_count": 5, "buttons_count": 10, "dead_ends": 0, "missing_back": 0},
        bot_b_name="BotB",
        bot_b_data={"screens_count": 5, "buttons_count": 10, "dead_ends": 0, "missing_back": 0},
    )
    md = comparator.build_comparison_markdown()
    assert "Ничья" in md


def test_safety_menu_with_colon_not_requires_input():
    """Verifies screen_requires_input doesn't flag menu ending with ':' as input when buttons exist."""
    cfg = Config()
    safety = SafetyFilter(cfg)

    # Menu with ':' but with navigation choices
    is_input = safety.screen_requires_input(
        text="Главное меню бота:",
        has_force_reply=False,
        pressable_labels=["Каталог", "Личный кабинет", "Помощь"],
    )
    assert is_input is False

    # Screen with ':' but only Cancel/Back buttons -> is waiting for input
    is_input_cancel = safety.screen_requires_input(
        text="Введите сумму пополнения:",
        has_force_reply=False,
        pressable_labels=["Отмена", "Назад"],
    )
    assert is_input_cancel is True


def test_resolve_target_matches_registered_command():
    """Verify _resolve_target resolves buttons with callback_data matching registered commands."""
    from tg_flowmap.core.models import MessageNode
    from tg_flowmap.sast.analyzer import GraphAnalyzer

    nodes = {
        "cmd:/start": MessageNode(id="cmd:/start", title="Start", text_template="Welcome"),
        "cmd:/help": MessageNode(id="cmd:/help", title="Help", text_template="Help text"),
    }
    analyzer = GraphAnalyzer(nodes=nodes, keyboards={})

    target_start, status_start = analyzer._resolve_target("start")
    assert target_start == "cmd:/start"
    assert status_start == "ok"

    target_slash_help, status_help = analyzer._resolve_target("/help")
    assert target_slash_help == "cmd:/help"
    assert status_help == "ok"


def test_consolidate_preserves_source_keyboard():
    """Verify screen consolidation preserves the keyboard when merging into a callback node lacking one."""
    from tg_flowmap.core.models import Button, Keyboard, MessageNode
    from tg_flowmap.sast.parser import AstParser

    parser = AstParser()
    kb = Keyboard(name="kb_settings", rows=[[Button(text="Opt", callback_data="opt")]])
    parser.nodes["cmd:/settings"] = MessageNode(id="cmd:/settings", title="Settings", text_template="Cfg", keyboard=kb)
    parser.nodes["cb:settings_menu"] = MessageNode(id="cb:settings_menu", title="Settings Menu", text_template="Menu", keyboard=None)

    parser._consolidate_duplicate_screens()

    assert "cb:settings_menu" in parser.nodes
    assert parser.nodes["cb:settings_menu"].keyboard is not None
    assert parser.nodes["cb:settings_menu"].keyboard.name == "kb_settings"
    assert "/settings" in parser.nodes["cb:settings_menu"].aliases
    assert "cmd:/settings" not in parser.nodes
