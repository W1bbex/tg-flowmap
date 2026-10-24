"""Тесты append-only timeline.jsonl: несколько событий с одним action_id,
writer-lock (параллельные боты не перемешивают байты), оборванная строка."""

import asyncio
import json

from tg_flowmap.dast.timeline_log import ActionLogger, TimelineWriter, read_valid_lines

BOT = "@bot_a"
BOT2 = "@bot_b"


def test_pending_then_success_same_action_id(state, tmp_path):
    """pending и success — ДВЕ строки JSONL с одним action_id; SQLite-строка
    обновляется, а не дублируется."""
    async def scenario():
        writer = TimelineWriter(tmp_path / "t.jsonl")
        logger = ActionLogger(state, writer)
        aid = await logger.start_action(BOT, "press", {"label": "Catalog"})
        await logger.finish_action(aid, BOT, "success", duration_ms=123)
        writer.close()

    asyncio.run(scenario())
    events, skipped = read_valid_lines(tmp_path / "t.jsonl")
    assert skipped == 0
    assert len(events) == 2
    assert events[0]["action_id"] == events[1]["action_id"]
    assert events[0]["status"] == "pending"
    assert events[1]["status"] == "success"
    assert events[1]["duration_ms"] == 123
    rows = state.timeline_all(BOT)
    assert len(rows) == 1 and rows[0]["status"] == "success"


def test_two_writers_do_not_mix_bytes(state, tmp_path):
    """Один общий writer/lock: 2 задачи × 40 событий — все строки валидны."""
    async def scenario():
        writer = TimelineWriter(tmp_path / "t.jsonl")

        async def spam(bot: str):
            logger = ActionLogger(state, writer)
            for i in range(40):
                aid = await logger.start_action(bot, "press", {"i": i})
                await logger.finish_action(aid, bot, "success", duration_ms=i)

        await asyncio.gather(spam(BOT), spam(BOT2))
        writer.close()

    asyncio.run(scenario())
    events, skipped = read_valid_lines(tmp_path / "t.jsonl")
    assert skipped == 0
    assert len(events) == 160          # 80 действий × 2 строки (pending + финал)
    per_bot = {BOT: 0, BOT2: 0}
    for e in events:
        per_bot[e["bot"]] += 1
    assert per_bot == {BOT: 80, BOT2: 80}


def test_torn_last_line_ignored(tmp_path):
    """Аварийный обрыв записи: оборванная последняя строка не ломает журнал."""
    p = tmp_path / "t.jsonl"
    p.write_text(
        '{"action_id": "a1", "status": "pending"}\n'
        '{"action_id": "a1", "status": "succ',
        encoding="utf-8")
    events, skipped = read_valid_lines(p)
    assert len(events) == 1 and events[0]["status"] == "pending"
    assert skipped == 1


def test_various_final_statuses(state, tmp_path):
    async def scenario():
        writer = TimelineWriter(tmp_path / "t.jsonl")
        logger = ActionLogger(state, writer)
        for status in ("timeout", "blocked", "error", "interrupted"):
            aid = await logger.start_action(BOT, "press", {})
            await logger.finish_action(aid, BOT, status, error=f"e-{status}")
        writer.close()

    asyncio.run(scenario())
    events, _ = read_valid_lines(tmp_path / "t.jsonl")
    statuses = [e["status"] for e in events]
    # каждая пара pending → финальный статус
    assert statuses.count("pending") == 4
    for s in ("timeout", "blocked", "error", "interrupted"):
        assert s in statuses
