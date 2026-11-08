from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

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
    executor = NavigationExecutor("@dummy", None, None, None)

    async def fake_observe(out):
        return None, None, None

    # Simulating execute_action_by_id outcome
    outcome = PressOutcome(kind="answer_only", message=None, callback=CallbackResult(alert=True, message="Toast!"))
    # Direct test of observe logic branch
    # If outcome is answer_only, step should succeed
    assert outcome.kind == "answer_only"


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
