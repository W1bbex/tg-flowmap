"""Тесты SQLite-состояния: visited-экраны, routes (1 экран — N маршрутов),
версионность сообщений, emoji documents/occurrences, frontier/persistence,
изоляция ботов, mark_stale_pending, reset."""

from telethon.tl.types import MessageEntityCustomEmoji

from tg_flowmap.dast.capture import capture_message
from tg_flowmap.dast.fingerprint import route_fingerprint, screen_fingerprint, screen_id_of
from conftest import FakeMessage

BOT = "@bot_a"
BOT2 = "@bot_b"


def _fp(text="Main menu"):
    return screen_fingerprint(text, [], [], [])


def test_screen_upsert_dedup_visited(state):
    """Один canonical экран не создаётся дважды (visited)."""
    fp = _fp()
    id1, created1 = state.upsert_screen(BOT, screen_id_of(fp), fp, 0, "main menu")
    id2, created2 = state.upsert_screen(BOT, screen_id_of(fp), fp, 0, "main menu")
    assert created1 is True
    assert created2 is False
    assert id1 == id2
    assert len(state.screens_all(BOT)) == 1


def test_one_screen_two_routes(state):
    """Один экран из двух путей = 1 screen + 2 routes (поправка ТЗ №2)."""
    fp = _fp()
    sid = screen_id_of(fp)
    state.upsert_screen(BOT, sid, fp, 1, "main menu")
    rfp1 = route_fingerprint(fp, None, "root")
    rfp2 = route_fingerprint(fp, "r_parent", "Back")
    rid1, c1 = state.upsert_route(BOT, "r1", rfp1, None, sid, [], 0)
    rid2, c2 = state.upsert_route(BOT, "r2", rfp2, "r_parent", sid,
                                  [{"screen_id": sid, "action": "Back"}], 1)
    assert c1 and c2 and rid1 != rid2
    assert len(state.screens_all(BOT)) == 1
    assert len(state.routes_all(BOT)) == 2
    # повторная регистрация того же маршрута не дублирует
    _, c3 = state.upsert_route(BOT, "r1", rfp1, None, sid, [], 0)
    assert c3 is False and len(state.routes_all(BOT)) == 2


def test_message_versions_increment_and_unique(state):
    """Каждое редактирование = новая версия; ничего не перезаписывается."""
    msg = FakeMessage(10, "v1 text")
    cap1 = capture_message(msg, BOT, "new", state=state)
    row1 = state.insert_message(cap1, "s_x")
    cap2 = capture_message(msg, BOT, "edit", state=state)
    row2 = state.insert_message(cap2, "s_x")
    assert cap1.version == 1 and cap2.version == 2
    assert row1 != row2
    rows = state._query(
        "SELECT version, event_type FROM messages WHERE bot=? AND message_id=10 "
        "ORDER BY version", (BOT,))
    assert [r["version"] for r in rows] == [1, 2]
    assert [r["event_type"] for r in rows] == ["new", "edit"]
    assert state.next_message_version(BOT, msg.chat_id, 10) == 3


def test_emoji_documents_dedupe_occurrences_grow(state):
    """Один Premium emoji в сотнях сообщений: documents уникальны,
    occurrences — на каждое использование."""
    doc_id = 53123456789
    for i, offset in enumerate([0, 4, 8]):
        msg = FakeMessage(100 + i, "🥇x" * 1)
        msg.entities = [MessageEntityCustomEmoji(offset=0, length=2, document_id=doc_id)]
        cap = capture_message(msg, BOT, "new", state=state)
        state.insert_message(cap, "s_e")
    docs = state._query("SELECT * FROM emoji_documents WHERE document_id=?",
                        (str(doc_id),))
    occ = state._query(
        "SELECT * FROM emoji_occurrences WHERE bot=? AND document_id=?", (BOT, str(doc_id)))
    assert len(docs) == 1
    assert len(occ) == 3


def test_frontier_dfs_order_and_persistence(cfg, state):
    """DFS: сначала глубокие; состояние переживает закрытие/открытие БД."""
    state.push_frontier(BOT, "r1", "s1", [], 1)
    state.push_frontier(BOT, "r2", "s2", [], 2)
    state.push_frontier(BOT, "r3", "s3", [], 1)
    item = state.pop_frontier(BOT)
    assert item["screen_id"] == "s2"          # depth DESC
    state.requeue_frontier(item["id"])
    state.finish_frontier(state.pop_frontier(BOT)["id"])  # s2 снова и done
    assert state.pop_frontier(BOT)["screen_id"] in ("s1", "s3")

    state.close()
    state2 = type(state)(cfg.db_path)         # «перезапуск» приложения
    try:
        rest = [state2.pop_frontier(BOT), state2.pop_frontier(BOT)]
        assert len(rest) == 2
        assert state2.pop_frontier(BOT) is None
    finally:
        state2.close()


def test_bot_isolation(state):
    """Два бота не смешивают экраны и message_id."""
    fp = _fp()
    sid = screen_id_of(fp)
    state.upsert_screen(BOT, sid, fp, 0, "main menu")
    state.upsert_screen(BOT2, sid, fp, 0, "main menu")
    m1 = capture_message(FakeMessage(10, "hi"), BOT, "new", state=state)
    m2 = capture_message(FakeMessage(10, "hi"), BOT2, "new", state=state)
    state.insert_message(m1, sid)
    state.insert_message(m2, sid)
    assert len(state.screens_all(BOT)) == 1
    assert len(state.screens_all(BOT2)) == 1
    assert len(state.messages_all(BOT)) == 1
    assert len(state.messages_all(BOT2)) == 1
    # переходы одного бота не видны другому
    state.add_transition(BOT, sid, None, "X", "callback", "edit", 1, None, None, None)
    assert state.transitions_all(BOT2) == []


def test_mark_stale_pending(state):
    import uuid
    a1, a2 = uuid.uuid4().hex, uuid.uuid4().hex
    state.timeline_create(a1, BOT, "press", {"label": "A"})
    state.timeline_create(a2, BOT, "press", {"label": "B"})
    state.timeline_update(a2, "success")
    n = state.mark_stale_pending(BOT)      # после «аварии»: только висящий pending
    assert n == 1
    rows = {r["action_id"]: r["status"] for r in state.timeline_all(BOT)}
    assert rows[a1] == "interrupted"
    assert rows[a2] == "success"


def test_button_explored_flag(state):
    fp = _fp()
    sid = screen_id_of(fp)
    state.upsert_screen(BOT, sid, fp, 0, "main menu")
    from tg_flowmap.dast.models import ButtonRef
    b = ButtonRef(row=0, col=0, label="Go", button_type="callback",
                  callback_data=b"go", message_id=1, button_fp="bf1")
    ids = state.insert_buttons(BOT, sid, 1, [b], ["bf1"])
    assert not state.button_explored(BOT, ids[0])
    state.add_transition(BOT, sid, "s_y", "Go", "callback", "edit", ids[0],
                         None, 1, 2)
    assert state.button_explored(BOT, ids[0])
    # кнопки читаются обратно с button_fp
    back = state.buttons_for_screen(BOT, sid)[0]
    assert back.button_fp == "bf1" and back.callback_data == b"go"


def test_reset_bot_clears(state):
    fp = _fp()
    sid = screen_id_of(fp)
    state.upsert_screen(BOT, sid, fp, 0, "main menu")
    state.upsert_route(BOT, "r1", "rfp", None, sid, [], 0)
    state.push_frontier(BOT, "r1", sid, [], 0)
    state.register_bot(BOT)
    state.reset_bot(BOT)
    assert state.screens_all(BOT) == []
    assert state.routes_all(BOT) == []
    assert state.frontier_pending_count(BOT) == 0
    assert state.bot_info(BOT)["status"] == "new"
