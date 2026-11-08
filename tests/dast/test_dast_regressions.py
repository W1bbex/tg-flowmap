import ast
import asyncio
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import pytest
from tg_flowmap.sast.evaluator import evaluate_ast_node
from tg_flowmap.dast.crawler import BotCrawler
from tg_flowmap.dast.config import Config
from tg_flowmap.dast.state import State
from tg_flowmap.dast.models import ButtonRef
from tg_flowmap.dast.safety import SafetyFilter
from tg_flowmap.dast.timeline_log import ActionLogger, TimelineWriter


def test_evaluator_if_exp_condition_handling():
    # True condition -> body
    node_true = ast.parse('"admin" if True else "user"').body[0].value
    assert evaluate_ast_node(node_true, {}, {}) == "admin"

    # False condition -> orelse
    node_false = ast.parse('"admin" if False else "user"').body[0].value
    assert evaluate_ast_node(node_false, {}, {}) == "user"

    # Unresolvable variable condition -> None (does not blindly return body)
    node_unresolved = ast.parse('"admin" if is_admin else "user"').body[0].value
    assert evaluate_ast_node(node_unresolved, {}, {}) is None

    # Both branches identical -> resolves safely
    node_same = ast.parse('"same" if is_admin else "same"').body[0].value
    assert evaluate_ast_node(node_same, {}, {}) == "same"


def test_crawler_cancellation_sets_paused(tmp_path: Path):
    async def _run():
        db_file = tmp_path / "state.db"
        state = State(db_file)
        cfg = Config()
        writer = TimelineWriter(tmp_path / "timeline.jsonl")
        logger = ActionLogger(state, writer)
        safety = SafetyFilter(cfg)
        nav = MagicMock()
        crawler = BotCrawler(cfg, state, logger, safety, nav, {}, "test_bot", media_dir=tmp_path / "media")

        async def mock_loop():
            await asyncio.sleep(0.01)
            raise asyncio.CancelledError()

        crawler._loop = mock_loop
        crawler._start_conversation = AsyncMock(return_value=True)

        with pytest.raises(asyncio.CancelledError):
            await crawler.run()

        info = state.bot_info("test_bot")
        assert info is not None
        assert info["status"] == "paused"

    asyncio.run(_run())


def test_crawler_fail_closed_on_low_confidence_button(tmp_path: Path):
    async def _run():
        db_file = tmp_path / "state.db"
        state = State(db_file)
        cfg = Config()
        writer = TimelineWriter(tmp_path / "timeline.jsonl")
        logger = ActionLogger(state, writer)
        safety = SafetyFilter(cfg)
        nav = MagicMock()
        nav.press_button = AsyncMock()
        crawler = BotCrawler(cfg, state, logger, safety, nav, {}, "test_bot", media_dir=tmp_path / "media")

        crawler._current_msg = MagicMock(id=123)
        crawler._current_msg_rowid = 1
        crawler._current_screen_id = "screen_1"

        b = ButtonRef(row=0, col=0, label="Old Button", button_type="callback", callback_data=b"old_data")

        state._exec(
            "INSERT INTO messages (id, bot, chat_id, message_id, event_type, captured_at) VALUES (?, ?, ?, ?, ?, ?)",
            (1, "test_bot", 12345, 123, "new", "2026-01-01T00:00:00Z"),
        )
        state._exec(
            "INSERT INTO buttons (id, bot, screen_id, row, col, label, button_type, callback_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "test_bot", "screen_1", 0, 0, "Old Button", "callback", b"old_data"),
        )
        state._exec(
            "INSERT INTO button_instances (bot, message_rowid, row, col, label, callback_data, action_id, button_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test_bot", 1, 0, 0, "Different New Button", "new_data", "act_new", "callback"),
        )

        item = {"button": b, "screen_id": "screen_1", "path": [], "depth": 1}
        await crawler._explore(item)

        nav.press_button.assert_not_called()

    asyncio.run(_run())
