from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_flowmap.core.comparator import BotComparator
from tg_flowmap.dast.auth import create_client
from tg_flowmap.dast.capture import extract_buttons
from tg_flowmap.dast.config import Config
from tg_flowmap.dast.crawler import BotCrawler
from tg_flowmap.dast.models import ButtonRef, CallbackResult, PressOutcome
from tg_flowmap.dast.navigation_graph import NavigationGraph
from tg_flowmap.dast.safety import SafetyFilter, WALLET_REGEXES
from tg_flowmap.dast.screen_identity import buttons_signature, match_button_instance
from tg_flowmap.dast.state import State
from tg_flowmap.dast.timeline_log import ActionLogger, TimelineWriter
from tg_flowmap.dast.utf16 import utf16_length
from tg_flowmap.sast.analyzer import GraphAnalyzer
from tg_flowmap.sast.emoji import fetch_custom_emojis, load_cached_emoji
import run


def test_run_wizard_no_name_error(tmp_path: Path) -> None:
    """Verifies that run.py functions use cfg_path and do not contain undefined cfg_file references."""
    source = inspect.getsource(run.run_telegram_config_wizard)
    assert "os.startfile(cfg_file)" not in source
    assert "os.startfile(cfg_path)" in source


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
        await crawler._explore(item)

        assert nav.press_button.call_count == 1

    asyncio.run(_run())


def test_navigation_graph_persists_unstable_edges_to_sqlite(tmp_path: Path) -> None:
    db_file = tmp_path / "state.db"
    state = State(db_file)
    graph = NavigationGraph(state=state, bot="test_bot")

    graph.record_transition("scr_a", "act_1", "scr_b", "edit", success=True)
    graph.record_transition("scr_a", "act_1", "scr_c", "edit", success=True)

    edges_in_db = state.graph_edges_all("test_bot")
    assert len(edges_in_db) == 2
    for e in edges_in_db:
        assert e["is_stable"] == 0
        assert e["confidence"] <= 0.5


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
