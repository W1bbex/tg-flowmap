from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_flowmap.core.comparator import BotComparator
from tg_flowmap.core.models import Issue
from tg_flowmap.core.llm_exporter import generate_llm_benchmark_prompt
from tg_flowmap.dast.auth import create_client
from tg_flowmap.dast.capture import extract_buttons
from tg_flowmap.dast.config import Config
from tg_flowmap.dast.crawler import BotCrawler, AbortScan
from tg_flowmap.dast.map_render import _render_map_mmd
from tg_flowmap.dast.models import ButtonRef, CallbackResult, PressOutcome
from tg_flowmap.dast.navigation_graph import NavigationGraph
from tg_flowmap.dast.ratelimit import GlobalLimiter
from tg_flowmap.dast.safety import SafetyFilter, WALLET_REGEXES
from tg_flowmap.dast.screen_identity import buttons_signature, match_button_instance
from tg_flowmap.dast.state import State
from tg_flowmap.dast.timeline_log import ActionLogger, TimelineWriter
from tg_flowmap.dast.tl_serial import clean
from tg_flowmap.dast.utf16 import utf16_length, utf16_offset_of_char
from tg_flowmap.sast.analyzer import GraphAnalyzer
from tg_flowmap.sast.emoji import fetch_custom_emojis, load_cached_emoji
from tg_flowmap.sast.keyboard_parser import _unwind_call_chain
from tg_flowmap.sast.parser import AstParser
import run


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_wizard_opens_requested_template_and_reads_edited_settings(tmp_path, monkeypatch, platform):
    """Run the template branch while replacing only console input and the editor."""
    cfg_path = tmp_path / "chosen-config.json"
    answers = iter(["2", ""])
    monkeypatch.setattr(run, "is_interactive", lambda: False)
    monkeypatch.setattr(run, "SCRIPT_DIR", tmp_path)
    monkeypatch.setattr(run.sys, "platform", platform)
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))

    def edit_config(path):
        assert Path(path) == cfg_path
        initial = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert initial["api_id"] == 0
        cfg_path.write_text(json.dumps({
            "api_id": 12345678, "api_hash": "0123456789abcdef0123456789abcdef",
        }), encoding="utf-8")

    if platform == "win32":
        editor = MagicMock(side_effect=edit_config)
        monkeypatch.setattr(run.os, "startfile", editor, raising=False)
        expected = cfg_path
    else:
        editor = MagicMock(side_effect=lambda command: edit_config(command[-1]))
        monkeypatch.setattr(run.subprocess, "Popen", editor)
        expected = ["open" if platform == "darwin" else "xdg-open", str(cfg_path)]

    assert run.run_telegram_config_wizard(cfg_path) is True
    editor.assert_called_once_with(expected)
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["api_id"] == 12345678


def test_screen_identity_buttons_signature_none_url_comparison() -> None:
    """Verifies that buttons with None URL do not crash sorted() when compared with string URLs."""
    btn1 = {"row": 0, "col": 0, "label": "Btn", "button_type": "url", "url": None}
    btn2 = {"row": 0, "col": 0, "label": "Btn", "button_type": "url", "url": "https://example.com"}
    sig = buttons_signature([btn1, btn2])
    assert len(sig) == 1
    assert len(sig[0]) == 2


def test_screen_identity_row_col_none_fallback() -> None:
    """Verifies that explicit None in row/col does not cause TypeError in int()."""
    btn = {"row": None, "col": None, "label": "Test", "button_type": "callback"}
    sig = buttons_signature([btn])
    assert len(sig) == 1

    matched, conf, _ = match_button_instance({"row": None, "col": None, "label": "Test", "button_type": "callback"}, [btn])
    assert matched is not None
    assert conf == 1.0


def test_dast_config_to_dict_json_serializable(tmp_path: Path) -> None:
    """Verifies that custom_output_dir Path does not break json serialization in to_dict() and save()."""
    cfg = Config(root=tmp_path, custom_output_dir=tmp_path / "custom")
    d = cfg.to_dict()
    assert isinstance(d["custom_output_dir"], str)
    dumped = json.dumps(d)
    assert "custom" in dumped

    save_file = tmp_path / "cfg.json"
    cfg.save(save_file)
    assert save_file.exists()


def test_capture_empty_callback_data_preserved() -> None:
    """Verifies that b'' callback_data is preserved and not replaced by None."""
    class DummyButton:
        text = "Separator"
        data = b""

    class DummyRow:
        buttons = [DummyButton()]

    class DummyReplyMarkup:
        rows = [DummyRow()]

    buttons = extract_buttons(DummyReplyMarkup(), message_id=1)
    assert len(buttons) == 1
    assert buttons[0].callback_data == b""


def test_emoji_load_cached_invalid_ntfs_chars(tmp_path: Path) -> None:
    """Verifies that invalid filename characters in emoji_id do not throw WinError 123."""
    res = load_cached_emoji("$ICONS[star]*:?", tmp_path)
    assert res is None


def test_emoji_fetch_custom_emojis_filters_non_digits(tmp_path: Path) -> None:
    """Verifies that non-digit emoji IDs are filtered out without making requests."""
    res = fetch_custom_emojis("test_token", ["$VAR_ICON", "star*"], cache_dir=tmp_path)
    assert res == {}


def test_comparator_extract_metrics_nodes_list() -> None:
    """Verifies that extract_metrics_from_bot_map supports bot_map with nodes as a list (DAST format)."""
    bot_map = {
        "nodes": [
            {
                "id": "screen_1",
                "keyboard": {
                    "rows": [[{"label": "Btn1"}], [{"label": "Btn2"}]]
                }
            }
        ],
        "issues": [{"issue_type": "dead_end"}],
    }
    metrics = BotComparator.extract_metrics_from_bot_map(bot_map)
    assert metrics["screens_count"] == 1
    assert metrics["buttons_count"] == 2
    assert metrics["dead_ends"] == 1


def test_safety_manual_answers_without_at_prefix() -> None:
    """Verifies manual_answer lookup works regardless of whether @ prefix is present."""
    manual = {
        "testbot": {
            "screens": [{"match": "Enter promo", "answer": "12345"}]
        }
    }
    ans = SafetyFilter.manual_answer(manual, "@testbot", "Enter promo")
    assert ans == "12345"

    ans2 = SafetyFilter.manual_answer(manual, "testbot", "Enter promo")
    assert ans2 == "12345"


def test_safety_tron_regex_case_sensitivity() -> None:
    """Verifies that TRON wallet regex requires capital T and is case-sensitive."""
    tron_pat = WALLET_REGEXES[1]
    valid_tron = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    lowercase_false_positive = "t1234567890abcdef1234567890abcdef1"

    assert tron_pat.search(valid_tron) is not None
    assert tron_pat.search(lowercase_false_positive) is None


def test_crawler_continue_on_stale_button(tmp_path: Path) -> None:
    async def _run():
        db_file = tmp_path / "state.db"
        state = State(db_file)
        cfg = Config()
        writer = TimelineWriter(tmp_path / "timeline.jsonl")
        logger = ActionLogger(state, writer)
        safety = SafetyFilter(cfg)
        nav = MagicMock()
        nav.press_button = AsyncMock(
            return_value=PressOutcome(kind="answer_only", callback=CallbackResult(message="Alert", alert=True))
        )
        crawler = BotCrawler(cfg, state, logger, safety, nav, {}, "test_bot", media_dir=tmp_path / "media")

        crawler._current_msg = MagicMock(id=123)
        crawler._current_msg_rowid = 1
        crawler._current_screen_id = "screen_1"

        state._exec(
            "INSERT INTO messages (id, bot, chat_id, message_id, event_type, captured_at) VALUES (?, ?, ?, ?, ?, ?)",
            (1, "test_bot", 12345, 123, "new", "2026-01-01T00:00:00Z"),
        )
        state._exec(
            "INSERT INTO buttons (id, bot, screen_id, row, col, label, button_type, callback_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "test_bot", "screen_1", 0, 0, "Stale Button", "callback", b"stale"),
        )
        state._exec(
            "INSERT INTO buttons (id, bot, screen_id, row, col, label, button_type, callback_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (2, "test_bot", "screen_1", 0, 1, "Valid Button", "callback", b"valid"),
        )
        state._exec(
            "INSERT INTO button_instances (bot, message_rowid, row, col, label, callback_data, action_id, button_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test_bot", 1, 0, 1, "Valid Button", "valid", "act_valid", "callback"),
        )

        item = {"screen_id": "screen_1", "path": [], "depth": 1}
        try:
            await crawler._explore(item)
            assert nav.press_button.call_count == 1
        finally:
            writer.close()
            state.close()

    asyncio.run(_run())


def test_navigation_graph_persists_unstable_edges_to_sqlite(tmp_path: Path) -> None:
    db_file = tmp_path / "state.db"
    state = State(db_file)
    try:
        graph = NavigationGraph(state=state, bot="test_bot")

        graph.record_transition("scr_a", "act_1", "scr_b", "edit", success=True)
        graph.record_transition("scr_a", "act_1", "scr_c", "edit", success=True)

        edges_in_db = state.graph_edges_all("test_bot")
        assert len(edges_in_db) == 2
        for e in edges_in_db:
            assert e["is_stable"] == 0
            assert e["confidence"] <= 0.5
    finally:
        state.close()


def test_comparator_dast_routing_and_screens_fallback(tmp_path: Path) -> None:
    dast_a = {
        "summary": {"screens": 5, "buttons": 12, "routes": 4, "dead_ends": 1, "max_depth": 3},
        "nodes": [{"id": "s1"}, {"id": "s2"}],
    }
    dast_b = {
        "summary": {"screens": 3, "buttons": 8, "routes": 2, "dead_ends": 0, "max_depth": 2},
        "nodes": [{"id": "s1"}],
    }
    comp = BotComparator("BotA", dast_a, "BotB", dast_b)
    metrics_a, metrics_b = comp._resolve_metrics()

    assert metrics_a["buttons_count"] == 12
    assert metrics_b["buttons_count"] == 8

    out = comp.export(tmp_path)
    prompt_content = out["llm_prompt"].read_text(encoding="utf-8")
    assert "BotA" in prompt_content
    assert "BotB" in prompt_content


def test_analyzer_dynamic_callback_placeholder() -> None:
    analyzer = GraphAnalyzer({}, {})
    target, kind = analyzer._resolve_target("$user_id")
    assert kind == "dynamic"
    assert target == "dynamic:$user_id"


def test_emoji_tgs_and_webm_support(tmp_path: Path) -> None:
    (tmp_path / "12345.tgs").write_bytes(b"tgs_data")
    (tmp_path / "67890.webm").write_bytes(b"webm_data")

    res_tgs = load_cached_emoji("12345", tmp_path)
    assert res_tgs is not None
    assert res_tgs.startswith("data:application/x-tgsticker;base64,")

    res_webm = load_cached_emoji("67890", tmp_path)
    assert res_webm is not None
    assert res_webm.startswith("data:video/webm;base64,")


def test_utf16_surrogatepass() -> None:
    lone_surrogate = "\ud800"
    length = utf16_length(lone_surrogate)
    assert length == 1


def test_auth_put_your_api_id() -> None:
    async def _run():
        cfg = Config()
        cfg.api_id = "PUT_YOUR_API_ID"
        cfg.api_hash = "valid_hash_123"

        with pytest.raises(RuntimeError, match="API credentials \u043d\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043d\u044b"):
            await create_client(cfg)

    asyncio.run(_run())


def test_llm_exporter_dict_and_list_screens():
    from tg_flowmap.core.llm_exporter import generate_llm_benchmark_prompt
    dict_screens = {
        "s1": {"screen_id": "s1", "title": "Screen 1", "buttons": [{"label": "Btn1"}]}
    }
    prompt = generate_llm_benchmark_prompt("BotA", {}, "BotB", {}, bot_a_screens=dict_screens, bot_b_screens=[{"screen_id": "s2"}])
    assert "Screen 1" in prompt
    assert "s2" in prompt


def test_evaluator_dict_unpacking():
    import ast
    from tg_flowmap.sast.evaluator import evaluate_ast_node
    tree = ast.parse("{'a': 1, **{'b': 2}}").body[0].value
    res = evaluate_ast_node(tree)
    assert res == {"a": 1, "b": 2}


def test_safety_filter_is_back_word_boundaries():
    from tg_flowmap.dast.config import Config
    from tg_flowmap.dast.safety import SafetyFilter
    cfg = Config(back_words=["back", "назад"])
    sf = SafetyFilter(cfg)
    assert sf.is_back("Back") is True
    assert sf.is_back("Назад") is True
    assert sf.is_back("Feedback") is False
    assert sf.is_back("Cashback") is False


def test_navigator_send_text_masks_secret_in_timeline(tmp_path: Path):
    from tg_flowmap.dast.navigator import EventRouter, Navigator
    from tg_flowmap.dast.ratelimit import FloodGate

    state = State(tmp_path / "state.db")
    cfg = Config(root=tmp_path)
    tl_file = tmp_path / "timeline.jsonl"
    writer = TimelineWriter(tl_file)
    logger = ActionLogger(state, writer)
    router = EventRouter()

    sent_raw = []

    class FakeClient:
        async def send_message(self, chat, text):
            sent_raw.append(text)
            return None

    class LimiterStub:
        async def wait(self):
            return None
        async def acquire(self):
            return None

    nav = Navigator(
        FakeClient(), "@bot", "chat", router, cfg, state, logger,
        LimiterStub(), LimiterStub(), FloodGate(),
    )

    secret_val = "TOP_SECRET_PASSWORD_999"

    async def _run():
        cfg.wait_response_timeout = 0.05
        cfg.wait_stabilization = 0.01
        await nav.send_text(secret_val, why="manual_answer")
        writer.close()

    try:
        asyncio.run(_run())
        assert sent_raw == [secret_val]
        raw_jsonl = tl_file.read_text(encoding="utf-8")
        assert secret_val not in raw_jsonl
        assert "[скрыто, длина" in raw_jsonl
    finally:
        state.close()


def test_global_limiter_ticket_leaky_bucket():
    """Verifies that GlobalLimiter calculates intervals without holding lock during sleep."""
    limiter = GlobalLimiter(min_interval=0.05)

    async def _worker():
        t0 = asyncio.get_event_loop().time()
        await limiter.acquire()
        t1 = asyncio.get_event_loop().time()
        return t1 - t0

    async def _main():
        results = await asyncio.gather(_worker(), _worker(), _worker())
        return results

    delays = asyncio.run(_main())
    assert len(delays) == 3
    assert delays[0] < 0.04
    assert delays[1] >= 0.04


def test_ast_parser_bot_command_list_variable(tmp_path: Path):
    """Verifies set_my_commands correctly extracts commands from variable lists."""
    bot_code = """
COMMANDS = [
    BotCommand("start", "Запуск бота"),
    BotCommand("help", "Помощь"),
]

async def on_startup(bot):
    await bot.set_my_commands(COMMANDS)
"""
    file_path = tmp_path / "bot_cmds.py"
    file_path.write_text(bot_code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(file_path)
    assert parser.has_set_my_commands is True
    assert "start" in parser.registered_menu_commands
    assert "help" in parser.registered_menu_commands


def test_keyboard_parser_chained_builder_call():
    """Verifies _unwind_call_chain extracts method calls from anonymous builder expressions."""
    import ast
    code = ast.parse("InlineKeyboardBuilder().button(text='OK', callback_data='ok').as_markup()")
    call_node = code.body[0].value
    root_id, chain = _unwind_call_chain(call_node.func.value)
    assert root_id is not None
    assert "InlineKeyboardBuilder" in root_id
    assert len(chain) == 1
    assert chain[0][0] == "button"


def test_keyboard_parser_falsy_zero_callback_data():
    """Verifies that integer/string '0' callback_data is preserved and not converted to None."""
    import ast
    parser = AstParser()
    dict_ast = ast.parse("{'text': '0', 'callback_data': 0}").body[0].value
    btn = parser._parse_button_element(dict_ast)
    assert btn is not None
    assert btn.callback_data == "0"
    assert btn.text == "0"


def test_crawler_circuit_breaker_resets_only_on_success(tmp_path: Path):
    """Verifies that _bump_action does not reset _consecutive_errors and circuit breaker fires."""
    cfg = Config()
    cfg.max_consecutive_errors = 3
    state = State(tmp_path / "cb_state.db")
    try:
        writer = TimelineWriter(tmp_path / "cb_timeline.jsonl")
        try:
            logger = ActionLogger(state, writer)
            safety = SafetyFilter(cfg)
            crawler = BotCrawler(cfg, state, logger, safety, MagicMock(), {}, "test_bot")

            crawler._bump_errors()
            crawler._bump_action()  # Must NOT reset _consecutive_errors
            assert crawler._consecutive_errors == 1

            crawler._bump_errors()
            crawler._bump_action()
            assert crawler._consecutive_errors == 2

            with pytest.raises(AbortScan, match="too many consecutive errors"):
                crawler._bump_errors()
        finally:
            writer.close()
    finally:
        state.close()


def test_comparator_metrics_with_issue_dataclass():
    """Verifies extract_metrics_from_bot_map works when issues list contains Issue dataclasses."""
    issue1 = Issue(issue_type="dead_end", severity="warning", message="dead end test")
    issue2 = Issue(issue_type="missing_back", severity="info", message="missing back test")
    bot_map = {
        "nodes": {"start": {"keyboard": {"rows": []}}},
        "issues": [issue1, issue2],
    }
    metrics = BotComparator.extract_metrics_from_bot_map(bot_map)
    assert metrics["dead_ends"] == 1
    assert metrics["missing_back"] == 1


def test_llm_exporter_extracts_buttons_from_keyboard_rows():
    """Verifies that screens with keyboard.rows extract button text in llm benchmark prompt."""
    screens = {
        "scr_1": {
            "title": "Main Menu",
            "keyboard": {
                "rows": [
                    [{"text": "Каталог", "callback_data": "cat"}, {"text": "Помощь", "callback_data": "help"}],
                ]
            },
        }
    }
    prompt = generate_llm_benchmark_prompt(
        bot_a_name="BotA",
        bot_a_metrics={"screens_count": 1, "buttons_count": 2},
        bot_b_name="BotB",
        bot_b_metrics={},
        bot_a_screens=screens,
    )
    assert "Каталог, Помощь" in prompt
    assert "нет кнопок" not in prompt


def test_map_render_escapes_brackets_in_node_title():
    """Verifies Mermaid map generation replaces brackets in node titles."""
    nodes = [{"id": "s1", "text_norm": "[1] Выберите опцию"}]
    edges = [{"source": "s1", "target": "s2", "label": "[Далее]"}]
    mmd = _render_map_mmd("test_bot", nodes, edges)
    assert 's1["s1<br/>(1) Выберите опцию"]' in mmd
    assert '|"(Далее)"|' in mmd


def test_safety_bitcoin_legacy_base58_strict():
    """Verifies Bitcoin legacy regex does not match strings containing 0, O, I, l."""
    btc_regex = WALLET_REGEXES[3]
    valid_btc = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    assert btc_regex.search(valid_btc) is not None

    invalid_with_l = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNl"
    assert btc_regex.search(invalid_with_l) is None

    invalid_with_o = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNO"
    assert btc_regex.search(invalid_with_o) is None


def test_state_messages_all_batch_queries(tmp_path: Path):
    """Verifies State.messages_all loads entities and media correctly using batch queries."""
    db_path = tmp_path / "batch_state.db"
    state = State(db_path)
    try:
        state._exec(
            "INSERT INTO messages (id, bot, chat_id, message_id, event_type, captured_at) VALUES (?, ?, ?, ?, ?, ?)",
            (1, "my_bot", 100, 1, "new", "2026-01-01T00:00:00Z"),
        )
        state._exec(
            "INSERT INTO messages (id, bot, chat_id, message_id, event_type, captured_at) VALUES (?, ?, ?, ?, ?, ?)",
            (2, "my_bot", 100, 2, "new", "2026-01-01T00:00:01Z"),
        )
        state._exec(
            "INSERT INTO entities (message_rowid, type, offset, length) VALUES (?, ?, ?, ?)",
            (1, "bold", 0, 5),
        )
        state._exec(
            "INSERT INTO media (bot, message_rowid, kind) VALUES (?, ?, ?)",
            ("my_bot", 2, "photo"),
        )

        msgs = state.messages_all("my_bot")
        assert len(msgs) == 2
        assert len(msgs[0]["entities"]) == 1
        assert msgs[0]["entities"][0]["type"] == "bold"
        assert len(msgs[0]["media"]) == 0
        assert len(msgs[1]["entities"]) == 0
        assert len(msgs[1]["media"]) == 1
        assert msgs[1]["media"][0]["kind"] == "photo"
    finally:
        state.close()


def test_utf16_offset_negative_index():
    """Verifies utf16_offset_of_char correctly handles negative index."""
    text = "Привет"
    offset_neg = utf16_offset_of_char(text, -1)
    offset_pos = utf16_offset_of_char(text, len(text) - 1)
    assert offset_neg == offset_pos
    assert offset_neg == 5


def test_tl_serial_clean_handles_cycles():
    """Verifies tl_serial.clean gracefully handles self-referencing data structures without recursion error."""
    cyclic_dict = {"a": 1}
    cyclic_dict["self"] = cyclic_dict
    cleaned = clean(cyclic_dict)
    assert cleaned["a"] == 1
    assert "$cycle" in cleaned["self"]


