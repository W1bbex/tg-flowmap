"""Интеграционные тесты обходчика (офлайн, скриптованный FakeNavigator):

- цикл Menu→Catalog→Back→Menu не создаёт бесконечные screens;
- replay прекращается при несовпадении маршрута (route → stale);
- успешный replay восстанавливает позицию;
- callback без нового сообщения сохраняет answer/alert;
- бинарный callback_data байт-в-байт;
- глобальный FloodWait останавливает обе задачи;
- EventRouter изолирует события двух ботов;
- requires_input + manual_answers.
"""

import asyncio
import time

from tg_flowmap.dast.fingerprint import screen_id_of, screen_fingerprint
from tg_flowmap.dast.models import CallbackResult, PressOutcome
from tg_flowmap.dast.navigator import EventRouter
from tg_flowmap.dast.ratelimit import FloodGate
from tg_flowmap.dast.safety import SafetyFilter
from tg_flowmap.dast.timeline_log import ActionLogger, TimelineWriter
from tg_flowmap.dast.crawler import BotCrawler
from conftest import FakeMessage, FakeNavigator, inline_markup

BOT = "@fake_bot"


# --------------------------------------------------------------- сценарии
def menu_msg():
    return FakeMessage(1, "Main menu",
                       reply_markup=inline_markup([[("Catalog", b"cat"),
                                                    ("Profile", b"prof")]]))


def catalog_msg():
    return FakeMessage(1, "Catalog",
                       reply_markup=inline_markup([
                           [("Back", b"back")],
                           [("Item $100", b"item100"), ("Item $300", b"item300")]]))


def profile_msg():
    return FakeMessage(1, "Profile", reply_markup=inline_markup([[("Back", b"back2")]]))


def card_msg():
    # цена вырезается volatile → item100/item300 дают ОДИН canonical экран
    return FakeMessage(1, "Card $100\nBest item",
                       reply_markup=inline_markup([[("Back", b"cardback")]]))


def happy_transitions():
    return {
        b"cat": {"kind": "edit", "msg": catalog_msg()},
        b"prof": {"kind": "edit", "msg": profile_msg()},
        b"back": {"kind": "edit", "msg": menu_msg()},
        b"back2": {"kind": "edit", "msg": menu_msg()},
        b"item100": {"kind": "edit", "msg": card_msg()},
        b"item300": {"kind": "edit", "msg": card_msg()},
        b"cardback": {"kind": "edit", "msg": catalog_msg()},
    }


def make_crawler_manual(cfg, state, nav, manual=None, tmp_path=None):
    writer = TimelineWriter(tmp_path / "manual.jsonl")
    logger = ActionLogger(state, writer)
    return BotCrawler(cfg, state, logger, SafetyFilter(cfg), nav,
                      manual or {}, BOT, media_dir=tmp_path / "media")


# ------------------------------------------------------------------ тесты
def test_menu_catalog_back_cycle_no_infinite_screens(cfg, state, tmp_path):
    """Цикл Menu→Catalog→Back→Menu: canonical экраны не размножаются."""
    nav = FakeNavigator(menu_msg(), happy_transitions())
    crawler, _writer = None, None
    from conftest import make_crawler as mk
    crawler, _writer = mk(cfg, state, nav, BOT, tmp_path)

    status = asyncio.run(crawler.run())
    assert status == "done"

    screens = state.screens_all(BOT)
    # menu, catalog, profile, card (карточки $100/$300 схлопнулись — цена volatile)
    assert len(screens) == 4
    roots = [s for s in screens if s["depth_min"] == 0]
    assert len(roots) == 1, "экран меню не должен дублироваться"

    menu_sid = roots[0]["screen_id"]
    cat_row = state.get_screen_by_fp(
        BOT, screen_fingerprint("Catalog", [], [
            {"row": 0, "col": 0, "label": "Back", "button_type": "callback",
             "callback_data": b"back", "url": None},
            {"row": 1, "col": 0, "label": "Item $100", "button_type": "callback",
             "callback_data": b"item100", "url": None},
            {"row": 1, "col": 1, "label": "Item $300", "button_type": "callback",
             "callback_data": b"item300", "url": None},
        ], [], cfg.compiled_volatile()))
    assert cat_row is not None
    back_edges = [t for t in state.transitions_all(BOT)
                  if t["from_screen"] == cat_row["screen_id"]
                  and t["to_screen"] == menu_sid]
    assert back_edges, "кнопка Back должна давать edge каталог→меню, а не новый экран"


def test_replay_mismatch_marks_stale_and_stops(cfg, state, tmp_path):
    """Replay при несовпадении маршрута: слепо не идём, route → stale."""
    menu_v1 = menu_msg()
    # после возвратов replay потребует /start — вернём ДРУГОЕ меню (без Catalog)
    menu_v2 = FakeMessage(1, "Main menu v2",
                          reply_markup=inline_markup([[("Other", b"other")]]))
    cat = FakeMessage(1, "Catalog", reply_markup=inline_markup([
        [("Item $100", b"item100"), ("Item $300", b"item300")]]))  # без Back
    card_no_back = FakeMessage(1, "Card $100",
                               reply_markup=inline_markup([[("Info", b"info")]]))
    transitions = {
        b"cat": {"kind": "edit", "msg": cat},
        b"item100": {"kind": "edit", "msg": card_no_back},
    }
    nav = FakeNavigator(menu_v1, transitions, start_sequence=[menu_v1, menu_v2])
    from conftest import make_crawler as mk
    crawler, _ = mk(cfg, state, nav, BOT, tmp_path)

    status = asyncio.run(crawler.run())
    assert status in ("done", "error")

    # исследование меню прервано: Profile не нажат (replay остановился на menu_v2)
    assert b"prof" not in nav.presses
    # маршрут помечен stale, ошибка зафиксирована
    stale = [r for r in state.routes_all(BOT) if r["status"] == "stale"]
    assert stale, "маршрут должен быть помечен stale"
    kinds = [e["kind"] for e in state.errors_list(BOT, limit=100)]
    assert "replay_mismatch" in kinds


def test_replay_success_restores_position(cfg, state, tmp_path):
    """Back ведёт не туда → replay через /start возвращает на нужный экран."""
    menu_v1 = menu_msg()
    catalog = FakeMessage(1, "Catalog", reply_markup=inline_markup([
        [("Item $100", b"item100"), ("Item $300", b"item300")]]))
    card = FakeMessage(1, "Card $100", reply_markup=inline_markup(
        [[("Back", b"cardback")]]))
    catalog_v2 = FakeMessage(1, "Catalog v2", reply_markup=inline_markup(
        [[("Whatever", b"whatever")]]))
    transitions = {
        b"cat": {"kind": "edit", "msg": catalog},
        b"item100": {"kind": "edit", "msg": card},
        b"item300": {"kind": "edit", "msg": card},
        b"cardback": {"kind": "edit", "msg": catalog_v2},  # «сбился» экран
    }
    nav = FakeNavigator(menu_v1, transitions,
                        start_sequence=[menu_v1, menu_v1])
    from conftest import make_crawler as mk
    crawler, _ = mk(cfg, state, nav, BOT, tmp_path)

    status = asyncio.run(crawler.run())
    assert status == "done"
    assert b"item300" in nav.presses, "после успешного replay item300 должен быть нажат"
    assert nav.starts >= 2, "replay должен использовать повторный /start"


def test_callback_answer_only_saved(cfg, state, tmp_path):
    """Callback answer без edit/new — полноценный результат (answer/alert)."""
    menu = FakeMessage(1, "Menu", reply_markup=inline_markup([[("Info", b"info")]]))
    transitions = {
        b"info": {"kind": "answer_only", "msg": None,
                  "callback": CallbackResult(message="Here is info", alert=True,
                                             url=None, cache_time=30)},
    }
    nav = FakeNavigator(menu, transitions)
    from conftest import make_crawler as mk
    crawler, _ = mk(cfg, state, nav, BOT, tmp_path)
    asyncio.run(crawler.run())

    trs = state.transitions_all(BOT)
    assert len(trs) == 1
    assert trs[0]["result_type"] == "answer_only"
    assert trs[0]["to_screen"] is None
    cb = state.callbacks_all(BOT)
    assert len(cb) == 1
    assert cb[0]["answer_message"] == "Here is info"
    assert cb[0]["is_alert"] == 1


def test_binary_callback_preserved_byte_for_byte(cfg, state, tmp_path):
    data = b"\x00\xff\x10\x7f\xca\xfe"
    menu = FakeMessage(1, "Menu", reply_markup=inline_markup([[("Go", data)]]))
    done = FakeMessage(1, "Done", reply_markup=None)
    transitions = {data: {"kind": "edit", "msg": done}}
    nav = FakeNavigator(menu, transitions)
    from conftest import make_crawler as mk
    crawler, _ = mk(cfg, state, nav, BOT, tmp_path)
    asyncio.run(crawler.run())

    assert data in nav.presses                       # нажата с точными байтами
    btn = state.buttons_all(BOT)[0]
    assert bytes(btn["callback_data"]) == data       # в БД байт-в-байт
    assert btn["callback_hex"] == data.hex()
    import base64
    assert btn["callback_b64"] == base64.b64encode(data).decode()
    # и в graph.json экспорте
    from tg_flowmap.dast.reports import build_graph
    g = build_graph(state, BOT)
    exported = g["nodes"][0]["buttons"][0]
    assert exported["callback_hex"] == data.hex()


def test_flood_gate_pauses_all_tasks():
    """Глобальный FloodWait останавливает ОБЕ задачи (аккаунтовый лимит)."""
    async def scenario():
        gate = FloodGate()
        await gate.pause(0.2)
        results = []

        async def worker(i):
            t0 = time.monotonic()
            await gate.wait_open()
            results.append((i, time.monotonic() - t0))

        await asyncio.gather(worker(1), worker(2))
        return results

    results = asyncio.run(scenario())
    assert len(results) == 2
    assert all(d >= 0.15 for _, d in results)


def test_event_router_isolates_two_bots():
    """События двух чатов не перепутываются: каждый router — свой chat_id."""
    async def scenario():
        r1, r2 = EventRouter(), EventRouter()
        r1.feed("new", FakeMessage(11, "for bot1", chat_id=111))
        r2.feed("new", FakeMessage(22, "for bot2", chat_id=222))
        p1, _ = await r1.wait_result(timeout=1, stabilization=0.02)
        p2, _ = await r2.wait_result(timeout=1, stabilization=0.02)
        return p1, p2

    p1, p2 = asyncio.run(scenario())
    assert p1[1].chat_id == 111 and p1[1].id == 11
    assert p2[1].chat_id == 222 and p2[1].id == 22


def test_requires_input_and_manual_answer(cfg, state, tmp_path):
    menu = FakeMessage(1, "Menu", reply_markup=inline_markup([[("Ask", b"ask")]]))
    ask = FakeMessage(1, "Введите email:", reply_markup=None)  # ввод, кнопок нет
    after = FakeMessage(1, "Thanks! Your email saved",
                        reply_markup=inline_markup([[("Menu", b"tomenu")]]))
    transitions = {
        b"ask": {"kind": "edit", "msg": ask},
        b"tomenu": {"kind": "edit", "msg": menu},
    }
    nav = FakeNavigator(menu, transitions)
    nav.text_msg = after
    manual = {BOT: {"screens": [
        {"match": "Введите email:", "match_type": "exact",
         "answer": "research@example.com"}]}}
    crawler = make_crawler_manual(cfg, state, nav, manual, tmp_path)
    asyncio.run(crawler.run())

    # Ответ отправлен при первом визите (graph-first избегает повторного replay ввода)
    assert getattr(nav, "sent_texts", []).count("research@example.com") >= 1
    # экран ввода помечен requires_input
    screens = state.screens_all(BOT)
    ask_screens = [s for s in screens if s["requires_input"]]
    assert ask_screens
    # ответ бота зафиксирован переходом manual_answer
    trs = state.transitions_all(BOT)
    assert any(t["action_type"] == "manual_answer" for t in trs)


def test_action_limit_resumable_and_finishes_after_resume(cfg, state, tmp_path):
    """Лимит достигнут при непустом frontier → limit_reached (не done!);
    после Resume с поднятым лимитом обход завершается как done."""
    cfg.max_actions_per_bot = 2
    menu = FakeMessage(1, "Menu", reply_markup=inline_markup(
        [[("A", b"a")], [("B", b"b")], [("C", b"c")]]))
    other = FakeMessage(1, "Other", reply_markup=None)
    transitions = {d: {"kind": "edit", "msg": other}
                   for d in (b"a", b"b", b"c")}
    nav = FakeNavigator(menu, transitions)
    from conftest import make_crawler as mk
    crawler, _ = mk(cfg, state, nav, BOT, tmp_path)
    status1 = asyncio.run(crawler.run())
    assert status1 == "limit_reached"
    assert state.frontier_active_count(BOT) > 0, "очередь должна остаться"
    assert nav.presses == [b"a"], "после лимита новые нажатия не выполняются"

    # Resume: подняли лимит — обход должен завершиться
    cfg.max_actions_per_bot = 50
    crawler2, _ = mk(cfg, state, nav, BOT, tmp_path)
    status2 = asyncio.run(crawler2.run(resume=True))
    assert status2 == "done"
    assert state.frontier_active_count(BOT) == 0
    assert set(nav.presses) == {b"a", b"b", b"c"}
