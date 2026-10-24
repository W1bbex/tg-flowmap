"""Регрессионные тесты исправлений (П1–П5, П8, П9): фильтрация событий,
маршруты к одному экрану, resume после аварии, лимит действий, multi-message
ответы, FloodGate-гонка, safety-guard навигатора, allowlist против жёстких
блоков, input-экраны с Cancel/Back, replay текстовых шагов, маскировка
manual answers."""

import asyncio
import time
from pathlib import Path

from tg_flowmap.dast.config import Config
from tg_flowmap.dast.crawler import BotCrawler, mask_secret
from tg_flowmap.dast.models import ButtonRef, PressOutcome
from tg_flowmap.dast.navigator import EventRouter, Navigator
from tg_flowmap.dast.ratelimit import FloodGate
from tg_flowmap.dast.safety import SafetyFilter
from tg_flowmap.dast.timeline_log import ActionLogger, TimelineWriter
from conftest import FakeMessage, FakeNavigator, inline_markup, make_crawler

BOT = "@fake_bot"


# ------------------------------------------------------------------ П1
def test_scheduler_feed_incoming_skips_outgoing():
    """Наши /start, manual answers и reply-нажатия (out=True) не попадают
    в EventRouter как ответы бота."""
    from tg_flowmap.dast.scheduler import _feed_incoming

    async def scenario():
        router = EventRouter()
        our_start = FakeMessage(1, "/start", out=True)
        our_reply = FakeMessage(2, "Мой ответ", out=True)
        bot_reply = FakeMessage(3, "Ответ бота", out=False)
        _feed_incoming(router, "new", our_start)
        _feed_incoming(router, "new", our_reply)
        _feed_incoming(router, "edit", our_reply)
        _feed_incoming(router, "new", bot_reply)
        primary, extras = await router.wait_result(timeout=1, stabilization=0.02)
        return primary, extras

    primary, extras = asyncio.run(scenario())
    assert primary is not None
    assert primary[1].id == 3 and primary[1].out is False
    assert extras == []


def test_scheduler_telethon_handler_is_async():
    """Telethon 1.44 awaits event handlers, поэтому callback обязан быть async."""
    import inspect
    from tg_flowmap.dast.scheduler import _make_event_handler

    async def scenario():
        router = EventRouter()
        handler = _make_event_handler(router, "edit")
        assert inspect.iscoroutinefunction(handler)
        msg = FakeMessage(4, "Edited", out=False)
        await handler(type("Event", (), {"message": msg})())
        return await router.wait_result(timeout=1, stabilization=0.02)

    primary, extras = asyncio.run(scenario())
    assert primary is not None and primary[0] == "edit"
    assert primary[1].id == 4
    assert extras == []


# ------------------------------------------------------------------ П2
def test_two_paths_one_screen_two_routes(cfg, state, tmp_path):
    """Два разных пути к одному экрану: 1 canonical screen + 2 routes."""
    menu = FakeMessage(1, "Main menu", reply_markup=inline_markup(
        [[("Way A", b"waya"), ("Way B", b"wayb")]]))
    # оба пути ведут к ОДНОМУ экрану (одинаковый текст и кнопки)
    same_target = FakeMessage(1, "Shared screen",
                              reply_markup=inline_markup([[("Back", b"back")]]))
    menu_back = menu
    transitions = {
        b"waya": {"kind": "edit", "msg": same_target},
        b"wayb": {"kind": "new", "msg": same_target},
        b"back": {"kind": "edit", "msg": menu_back},
    }
    nav = FakeNavigator(menu, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)
    status = asyncio.run(crawler.run())
    assert status == "done"

    screens = state.screens_all(BOT)
    shared = [s for s in screens if s["text_norm"].startswith("shared screen")]
    assert len(shared) == 1, "canonical screen должен остаться один"
    routes_to_shared = [r for r in state.routes_all(BOT)
                        if r["screen_id"] == shared[0]["screen_id"]]
    assert len(routes_to_shared) == 2, "два фактических пути = две записи routes"
    actions = {r["path"][-1]["action"] for r in routes_to_shared}
    assert actions == {"Way A", "Way B"}


def test_same_route_not_duplicated(cfg, state, tmp_path):
    """Повторное прохождение того же пути не дублирует route."""
    menu = FakeMessage(1, "Main menu", reply_markup=inline_markup(
        [[("Go", b"go")], [("Go2", b"go2")]]))
    target = FakeMessage(1, "Target", reply_markup=inline_markup(
        [[("Back", b"back")]]))
    transitions = {
        b"go": {"kind": "edit", "msg": target},
        b"go2": {"kind": "edit", "msg": target},
        b"back": {"kind": "edit", "msg": menu},
    }
    nav = FakeNavigator(menu, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)
    asyncio.run(crawler.run())
    # повторный заход тем же путём (resume с тем же состоянием)
    crawler2, _ = make_crawler(cfg, state, nav, BOT, tmp_path)
    asyncio.run(crawler2.run(resume=True))
    routes = [r for r in state.routes_all(BOT)
              if r["screen_id"].startswith("s_")]
    fps = [r["route_fingerprint"] for r in routes]
    assert len(fps) == len(set(fps)), "route_fingerprint не должен дублироваться"


# ------------------------------------------------------------------ П3
def test_crash_resume_requeues_running_frontier(cfg, state, tmp_path):
    """Авария между pop_frontier и finish_frontier: ветка не теряется —
    resume возвращает running → pending (идемпотентно)."""
    state.push_frontier(BOT, "r1", "s_menu", [], 0)
    state.push_frontier(BOT, "r2", "s_cat", [], 1)
    item = state.pop_frontier(BOT)          # s_cat: pending → running
    assert item["screen_id"] == "s_cat"

    state.close()                            # «аварийное завершение»
    state2 = type(state)(cfg.db_path)
    try:
        assert state2.frontier_active_count(BOT) == 2
        assert state2.frontier_pending_count(BOT) == 1
        # повторный вызов идемпотентен
        assert state2.requeue_running_frontier(BOT) == 1
        assert state2.requeue_running_frontier(BOT) == 0
        assert state2.frontier_pending_count(BOT) == 2
        first = state2.pop_frontier(BOT)
        second = state2.pop_frontier(BOT)
        assert {first["screen_id"], second["screen_id"]} == {"s_menu", "s_cat"}
    finally:
        state2.close()


def test_crawler_resume_marks_interrupted_and_requeues(cfg, state, tmp_path):
    """Полный цикл: зависшие pending-действия и running-ветки корректно
    подхватываются Resume'ом."""
    menu = FakeMessage(1, "Menu", reply_markup=inline_markup([[("Go", b"go")]]))
    target = FakeMessage(1, "Target", reply_markup=None)
    transitions = {b"go": {"kind": "edit", "msg": target}}
    nav = FakeNavigator(menu, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)
    asyncio.run(crawler.run())
    # имитируем обрыв: ветка в running и pending-действие в timeline
    state.push_frontier(BOT, "rx", "s_nonexistent", [], 2)
    item = state.pop_frontier(BOT)
    state.timeline_create("aid_fake", BOT, "press", {"label": "X"})
    crawler2, _ = make_crawler(cfg, state, nav, BOT, tmp_path)
    status = asyncio.run(crawler2.run(resume=True))
    assert status in ("done", "paused")
    tl = [t["status"] for t in state.timeline_all(BOT) if t["action_id"] == "aid_fake"]
    assert tl == ["interrupted"]
    # «несуществующий» экран корректно пропущен (skipped), не падает
    skipped = state._query_one(
        "SELECT status FROM frontier WHERE screen_id='s_nonexistent'")
    assert skipped["status"] == "skipped"


# ------------------------------------------------------------------ П5
def test_processing_then_menu_extras_fully_captured(cfg, state, tmp_path):
    """«Processing…» первым, реальное меню с кнопкой Deep — вторым:
    Deep должен быть исследован, оба экрана полноценно захвачены."""
    menu = FakeMessage(1, "Start", reply_markup=inline_markup(
        [[("Open", b"open")]]))
    processing = FakeMessage(50, "Processing…")
    real_menu = FakeMessage(51, "Actual menu",
                            reply_markup=inline_markup([[("Deep", b"deep")]]))
    deep_screen = FakeMessage(52, "Deep screen", reply_markup=None)
    transitions = {
        b"open": {"kind": "new", "msg": processing,
                  "extras": [("new", real_menu)]},
        b"deep": {"kind": "edit", "msg": deep_screen},
    }
    nav = FakeNavigator(menu, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)
    status = asyncio.run(crawler.run())
    assert status == "done"

    # кнопка Deep исследована
    assert b"deep" in nav.presses
    trs = state.transitions_all(BOT)
    deep_tr = [t for t in trs if t["action"] == "Deep"]
    assert deep_tr and deep_tr[0]["to_screen"], "Deep должен вести на экран"

    # оба extra-сообщения стали экранами с полным capture
    texts = [s["text_norm"] for s in state.screens_all(BOT)]
    assert any("processing" in t for t in texts)
    assert any(t.startswith("actual menu") for t in texts)
    # у экрана меню есть кнопка Deep с callback_data
    menu_screen = [s for s in state.screens_all(BOT)
                   if s["text_norm"].startswith("actual menu")][0]
    btns = state.buttons_for_screen(BOT, menu_screen["screen_id"])
    assert any(b.label == "Deep" and b.callback_data == b"deep" for b in btns)
    # с «Actual menu» продолжилась навигация (он — навигационный экран)
    assert deep_tr[0]["from_screen"] == menu_screen["screen_id"]


def test_extra_message_event_type_preserved(cfg, state, tmp_path):
    """event_type extra-сообщений сохраняется фактический (edit/new),
    а не принудительно new."""
    menu = FakeMessage(1, "Menu", reply_markup=inline_markup([[("Go", b"go")]]))
    m1 = FakeMessage(60, "First")
    m2 = FakeMessage(61, "Second edited")
    transitions = {b"go": {"kind": "new", "msg": m1,
                           "extras": [("edit", m2)]}}
    nav = FakeNavigator(menu, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)
    asyncio.run(crawler.run())
    ev1 = state._query_one("SELECT event_type FROM messages WHERE message_id=60")
    ev2 = state._query_one("SELECT event_type FROM messages WHERE message_id=61")
    assert ev1["event_type"] == "new"
    assert ev2["event_type"] == "edit"


# ------------------------------------------------------------------ П8
def test_floodgate_race_task_b_does_not_send_during_pause():
    """Гонка: задача B уже прошла per-bot delay и global limiter (первый
    «гейт»), затем задача A поймала FloodWait и поставила глобальную паузу —
    B не отправляет запрос до открытия FloodGate (проверка непосредственно
    перед запросом)."""

    async def scenario():
        gate = FloodGate()
        passed_global = asyncio.Event()
        go_to_gate = asyncio.Event()
        limiter_hits = []

        async def bot_b_request():
            # порядок как в Navigator._through_limiters:
            # per_bot (мгновенно) → global → FloodGate последним
            await asyncio.sleep(0)
            limiter_hits.append(time.monotonic())
            passed_global.set()          # B прошла первый гейт
            await go_to_gate.wait()      # ...и ещё не проверила FloodGate
            await gate.wait_open()
            return time.monotonic()

        t0 = time.monotonic()
        task_b = asyncio.create_task(bot_b_request())
        await passed_global.wait()       # B реально прошла global limiter
        await gate.pause(0.2)            # A поймала FloodWait ПОСЛЕ этого
        paused_at = time.monotonic()
        go_to_gate.set()                 # B идёт проверять гейт перед запросом
        sent_at = await task_b
        return sent_at, paused_at, limiter_hits

    sent_at, paused_at, limiter_hits = asyncio.run(scenario())
    assert limiter_hits, "B прошла глобальный лимитер до паузы"
    assert sent_at >= paused_at + 0.15, \
        "B не должна отправить запрос во время глобальной паузы"


def test_get_entity_goes_through_limiter_and_gate():
    """client.get_entity тоже через общий лимитер + FloodGate."""
    from tg_flowmap.dast import scheduler

    calls = []

    class FakeClient:
        async def get_entity(self, bot):
            calls.append(("get_entity", bot))
            return type("E", (), {"id": 123})()

    async def scenario():
        gate = FloodGate()
        await gate.pause(0.15)
        limiter_acquired = []

        class L:
            async def acquire(self):
                limiter_acquired.append(1)

        t0 = time.monotonic()
        ent = await scheduler._resolve_entity(FakeClient(), BOT, L(), gate)
        return ent, time.monotonic() - t0, limiter_acquired, calls

    ent, dt, limiter_acquired, calls = asyncio.run(scenario())
    assert ent.id == 123
    assert limiter_acquired, "get_entity должен идти через GlobalLimiter"
    assert dt >= 0.12, "get_entity должен ждать FloodGate"
    assert calls == [("get_entity", BOT)]


# ------------------------------------------------------------------ П9
def _make_navigator_with_blocked_button(cfg, state, tmp_path, blocked_button):
    """Реальный Navigator с заглушками клиента/лимитеров."""
    writer = TimelineWriter(tmp_path / "nav_guard.jsonl")
    logger = ActionLogger(state, writer)

    class PerBot:
        async def wait(self):
            return None

    class Glob:
        async def acquire(self):
            return None

    class Router(EventRouter):
        async def wait_result(self, timeout, stabilization):
            return None, []

    class Client:
        async def send_message(self, *a, **k):
            raise AssertionError("заблокированная кнопка не должна нажиматься")

    nav = Navigator(Client(), BOT, "chat", Router(), cfg, state, logger,
                    PerBot(), Glob(), FloodGate())
    return nav, writer


def test_navigator_refuses_blocked_button(cfg, state, tmp_path):
    """Navigator.press_button не нажимает кнопку с blocked_reason,
    даже если её вызвали напрямую."""
    blocked = ButtonRef(row=0, col=0, label="Buy", button_type="callback",
                        callback_data=b"buy", blocked_reason="danger_word:buy")

    async def scenario():
        nav, writer = _make_navigator_with_blocked_button(cfg, state, tmp_path,
                                                          blocked)
        outcome = await nav.press_button(blocked, 1)
        writer.close()
        return outcome

    outcome = asyncio.run(scenario())
    assert outcome.kind == "error"
    assert "blocked" in (outcome.error or "")


def test_navigator_refuses_requires_password_button(cfg, state, tmp_path):
    """Кнопка requires_password=True блокируется на уровне навигатора."""
    btn = ButtonRef(row=0, col=0, label="Confirm", button_type="callback",
                    callback_data=b"x", requires_password=True)

    async def scenario():
        nav, writer = _make_navigator_with_blocked_button(cfg, state, tmp_path, btn)
        outcome = await nav.press_button(btn, 1)
        writer.close()
        return outcome

    outcome = asyncio.run(scenario())
    assert outcome.kind == "error"
    assert "requires_password" in (outcome.error or "")


def test_allowlist_does_not_bypass_hard_blocks():
    """Ручной allowlist НЕ обходит checkout/payment/password ограничения."""
    s = SafetyFilter(Config(root=Path("."),
                            allowed_button_labels=[
                                "Continue", "Далее", "Войти",
                                "Купить 1 аккаунт"]))
    ok, reason = s.button_verdict("Continue", "callback",
                                  "Оплата заказа. К оплате: 100$")
    assert not ok and reason == "checkout_screen"
    ok, reason = s.button_verdict(
        "Далее", "callback",
        "Переведите USDT на TRC20 кошелёк TQn9Y2khDD95J42FQtQTdwVVRvBoo4Vb7x")
    assert not ok and reason == "payment_screen"
    ok, reason = s.button_verdict("Войти", "callback", "Введите пароль")
    assert not ok and reason == "password_required"
    ok, reason = s.button_verdict("Continue", "callback", requires_password=True,
                                  screen_text="Нейтральный экран")
    assert not ok and reason == "requires_password"
    # на нейтральном экране allowlist по-прежнему снимает мягкие блоки
    ok, _ = s.button_verdict("Купить 1 аккаунт", "callback", "Каталог")
    assert ok


def test_input_screen_with_only_cancel_back_button():
    """Manual answer с кнопкой Cancel/Back — тоже input-экран."""
    s = SafetyFilter(Config(root=Path(".")))
    assert s.screen_requires_input("Введите код подтверждения:", False, [])
    assert s.screen_requires_input(
        "Отправьте ваш email для продолжения", False, ["❌ Отмена", "⬅ Назад"])
    assert not s.screen_requires_input(
        "Отправьте ваш email", False, ["Каталог", "Профиль"])
    assert not s.screen_requires_input("Главное меню", False, ["Каталог"])


def test_manual_answer_not_repeated_and_replay_text_step(cfg, state, tmp_path):
    """Ответ отправляется один раз; replay маршрута через input-экран
    воспроизводит текстовый шаг (step_type=text), путь содержит текст."""
    menu = FakeMessage(1, "Main menu", reply_markup=inline_markup(
        [[("Ask code", b"ask")]]))
    input_screen = FakeMessage(1, "Введите код:", reply_markup=None)
    result_screen = FakeMessage(2, "Verified menu",
                                reply_markup=inline_markup(
                                    [[("Deep", b"deep"), ("More", b"more")]]))
    deep_screen = FakeMessage(3, "Deep screen", reply_markup=None)  # без Back!
    more_screen = FakeMessage(4, "More screen", reply_markup=None)
    transitions = {
        b"ask": {"kind": "edit", "msg": input_screen},
        b"deep": {"kind": "edit", "msg": deep_screen},
        b"more": {"kind": "edit", "msg": more_screen},
    }
    nav = FakeNavigator(menu, transitions,
                        start_sequence=[menu, menu, menu, menu])
    nav.text_msg = result_screen
    manual = {BOT: {"screens": [
        {"match": "Введите код:", "match_type": "exact", "answer": "12345"}]}}
    writer = TimelineWriter(tmp_path / "manual.jsonl")
    logger = ActionLogger(state, writer)
    crawler = BotCrawler(cfg, state, logger, SafetyFilter(cfg), nav,
                         manual, BOT, media_dir=tmp_path / "media")
    status = asyncio.run(crawler.run())
    assert status == "done"

    # Ответ отправлен конечное число раз: начальный + replay текстовых шагов
    # при возвратах (НЕ бесконечно — защита once-ключа по экрану-вопросу)
    sent = getattr(nav, "sent_texts", []).count("12345")
    assert 2 <= sent <= 4, f"ответов должно быть конечное число, получено {sent}"
    # replay текстового шага сработал: More нажат ПОСЛЕ возврата через текст
    assert b"more" in nav.presses and b"deep" in nav.presses
    # путь маршрута результата содержит текстовый шаг с реальным ответом
    verified = [s for s in state.screens_all(BOT)
                if s["text_norm"].startswith("verified menu")][0]
    route = [r for r in state.routes_all(BOT)
             if r["screen_id"] == verified["screen_id"]][0]
    text_steps = [st for st in route["path"] if st.get("step_type") == "text"]
    assert text_steps and text_steps[0]["text"] == "12345"


def test_manual_answer_masked_in_reports(cfg, state, tmp_path):
    """Секретный manual answer не попадает целиком в публичные отчёты."""
    from tg_flowmap.dast.reports import build_graph, build_report_md, generate_reports

    menu = FakeMessage(1, "Main menu", reply_markup=inline_markup(
        [[("Ask", b"ask")]]))
    input_screen = FakeMessage(1, "Введите код:", reply_markup=None)
    result_screen = FakeMessage(2, "Result",
                                reply_markup=inline_markup([[("Back", b"back")]]))
    transitions = {
        b"ask": {"kind": "edit", "msg": input_screen},
        b"back": {"kind": "edit", "msg": menu},
    }
    nav = FakeNavigator(menu, transitions)
    nav.text_msg = result_screen
    secret = "SUPER-SECRET-ANSWER-42"
    manual = {BOT: {"screens": [
        {"match": "Введите код:", "match_type": "exact", "answer": secret}]}}
    writer = TimelineWriter(tmp_path / "m2.jsonl")
    logger = ActionLogger(state, writer)
    crawler = BotCrawler(cfg, state, logger, SafetyFilter(cfg), nav,
                         manual, BOT, media_dir=tmp_path / "media")
    asyncio.run(crawler.run())

    report = build_report_md(cfg, state, BOT)
    assert secret not in report
    assert mask_secret(secret) in report or "скрыто" in report
    graph = build_graph(state, BOT)
    graph_str = str(graph)
    assert secret not in graph_str
    assert "[hidden]" in graph_str  # текстовые шаги маршрутов маскированы


# -------------------------------------------------- Регрессия EventRouter & /start
def test_event_router_wait_result_multiple_extras_contract():
    """EventRouter.wait_result() возвращает extras как список кортежей (kind, msg)."""
    async def scenario():
        router = EventRouter()
        m1 = FakeMessage(101, "Primary", out=False)
        m2 = FakeMessage(102, "Extra 1", out=False)
        m3 = FakeMessage(103, "Extra 2 edited", out=False)

        router.feed("new", m1)
        router.feed("new", m2)
        router.feed("edit", m3)

        primary, extras = await router.wait_result(timeout=1.0, stabilization=0.05)
        return primary, extras

    primary, extras = asyncio.run(scenario())
    assert primary is not None
    assert primary[0] == "new" and primary[1].id == 101
    assert len(extras) == 2
    assert extras[0][0] == "new" and extras[0][1].id == 102
    assert extras[1][0] == "edit" and extras[1][1].id == 103
    for item in extras:
        assert isinstance(item, tuple)
        assert len(item) == 2
        assert isinstance(item[0], str)
        assert hasattr(item[1], "id")


def test_start_multi_message_banner_then_menu_explored(cfg, state, tmp_path):
    """При /start бот присылает Processing… (без кнопок) + Actual menu с кнопкой Deep:
    - ровно один root route (parent_route=None), указывающий на Actual menu;
    - у Processing нет route и frontier;
    - кнопка Deep исследована;
    - status == 'done', frontier пуст."""
    processing = FakeMessage(1, "Processing…", reply_markup=None)
    menu = FakeMessage(2, "Actual menu",
                       reply_markup=inline_markup([[("Deep", b"deep")]]))
    deep_screen = FakeMessage(3, "Deep screen", reply_markup=None)

    class MultiStartNavigator(FakeNavigator):
        async def send_start(self):
            self.starts += 1
            return PressOutcome(
                kind="new", message=processing,
                extra_messages=[("new", menu)],
                action_id="fake_start"
            )

    transitions = {b"deep": {"kind": "edit", "msg": deep_screen}}
    nav = MultiStartNavigator(processing, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    status = asyncio.run(crawler.run())
    assert status == "done"
    assert state.frontier_active_count(BOT) == 0
    assert state.frontier_pending_count(BOT) == 0

    # Кнопка Deep исследована
    assert b"deep" in nav.presses

    # Все 3 экрана зафиксированы в БД
    screens = state.screens_all(BOT)
    assert len(screens) == 3
    texts = [s["text_norm"] for s in screens]
    assert any("processing" in t for t in texts)
    assert any("actual menu" in t for t in texts)
    assert any("deep screen" in t for t in texts)

    proc_screen = [s for s in screens if "processing" in s["text_norm"]][0]
    menu_screen = [s for s in screens if "actual menu" in s["text_norm"]][0]
    deep_screen_obj = [s for s in screens if "deep screen" in s["text_norm"]][0]

    # Ровно один root route с parent_route=None, указывающий на Actual menu
    routes = state.routes_all(BOT)
    root_routes = [r for r in routes if r["parent_route"] is None]
    assert len(root_routes) == 1
    assert root_routes[0]["screen_id"] == menu_screen["screen_id"]

    # У Processing нет route и frontier
    proc_routes = [r for r in routes if r["screen_id"] == proc_screen["screen_id"]]
    assert len(proc_routes) == 0
    proc_frontier = state._query(
        "SELECT * FROM frontier WHERE bot=? AND screen_id=?",
        (BOT, proc_screen["screen_id"]))
    assert len(proc_frontier) == 0

    # Переход Actual menu -> Deep screen зафиксирован
    trs = state.transitions_all(BOT)
    deep_tr = [t for t in trs if t["action"] == "Deep"]
    assert deep_tr
    assert deep_tr[0]["from_screen"] == menu_screen["screen_id"]
    assert deep_tr[0]["to_screen"] == deep_screen_obj["screen_id"]


def test_real_navigator_and_event_router_multi_message_start(cfg, state, tmp_path):
    """Связка реального Navigator + EventRouter с несколькими входящими сообщениями."""
    writer = TimelineWriter(tmp_path / "nav_router.jsonl")
    logger = ActionLogger(state, writer)
    router = EventRouter()

    banner = FakeMessage(201, "Приветственный баннер", out=False)
    menu = FakeMessage(202, "Клавиатура меню", out=False,
                       reply_markup=inline_markup([[("Раздел", b"sec")]]))

    class FakeTelethonClient:
        async def send_message(self, chat, text):
            # Имитация бота: после отправки /start бот шлёт 2 сообщения
            router.feed("new", banner)
            router.feed("new", menu)
            return None

    class LimiterStub:
        async def wait(self):
            return None
        async def acquire(self):
            return None

    nav = Navigator(
        FakeTelethonClient(), BOT, "chat", router, cfg, state, logger,
        LimiterStub(), LimiterStub(), FloodGate(),
    )

    async def scenario():
        outcome = await nav.send_start()
        writer.close()
        return outcome

    outcome = asyncio.run(scenario())
    assert outcome.kind == "new"
    assert outcome.message.id == 201
    assert len(outcome.extra_messages) == 1
    assert outcome.extra_messages[0] == ("new", menu)


def test_replay_root_with_multi_message_start(cfg, state, tmp_path):
    """Multi-message /start -> root route -> принудительный replay пустого пути:
    - replay возвращает True;
    - route не становится stale;
    - выбран Actual menu, а не Processing."""
    processing = FakeMessage(1, "Processing…", reply_markup=None)
    menu = FakeMessage(2, "Actual menu",
                       reply_markup=inline_markup([[("Deep", b"deep")]]))

    class MultiStartNav(FakeNavigator):
        async def send_start(self):
            self.starts += 1
            return PressOutcome(
                kind="new", message=processing,
                extra_messages=[("new", menu)],
                action_id="fake_start"
            )

    nav = MultiStartNav(processing, {})
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        started = await crawler._start_conversation()
        assert started is True
        root_routes = [r for r in state.routes_all(BOT) if r["parent_route"] is None]
        assert len(root_routes) == 1
        root_route = root_routes[0]
        menu_screen = [s for s in state.screens_all(BOT) if "actual menu" in s["text_norm"]][0]
        assert root_route["screen_id"] == menu_screen["screen_id"]

        # Принудительно вызываем _replay_path с пустым путем
        ok = await crawler._replay_path(root_route["screen_id"], [], root_route["route_id"])
        assert ok is True

        # Проверяем, что route не стал stale
        updated_routes = state.routes_all(BOT)
        assert updated_routes[0]["status"] == "active"

        # Текущая позиция — Actual menu, а не Processing
        assert crawler._current_screen_id == menu_screen["screen_id"]
        assert crawler._current_msg.id == menu.id

    asyncio.run(scenario())


def test_replay_non_empty_path_with_multi_message_start(cfg, state, tmp_path):
    """Multi-message /start -> Actual menu -> Section -> принудительный replay непустого пути:
    - после повторного /start выбирается Actual menu;
    - сохранённая кнопка нажимается;
    - целевой Section достигается;
    - route не становится stale."""
    processing = FakeMessage(1, "Processing…", reply_markup=None)
    menu = FakeMessage(2, "Actual menu",
                       reply_markup=inline_markup([[("Section", b"sec")]]))
    section_screen = FakeMessage(3, "Section screen",
                                 reply_markup=inline_markup([[("Item", b"item")]]))

    class MultiStartNav(FakeNavigator):
        async def send_start(self):
            self.starts += 1
            return PressOutcome(
                kind="new", message=processing,
                extra_messages=[("new", menu)],
                action_id="fake_start"
            )

    transitions = {b"sec": {"kind": "edit", "msg": section_screen}}
    nav = MultiStartNav(processing, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        started = await crawler._start_conversation()
        assert started is True

        menu_screen = [s for s in state.screens_all(BOT) if "actual menu" in s["text_norm"]][0]
        buttons = state.buttons_for_screen(BOT, menu_screen["screen_id"])
        sec_btn = [b for b in buttons if b.label == "Section"][0]

        # Исследуем кнопку Section
        item = state.pop_frontier(BOT)
        await crawler._explore(item)

        sec_screen_obj = [s for s in state.screens_all(BOT) if "section screen" in s["text_norm"]][0]
        routes = state.routes_all(BOT)
        sec_route = [r for r in routes if r["screen_id"] == sec_screen_obj["screen_id"]][0]

        # Меняем текущую позицию на фиктивную, чтобы вынудить полный replay
        crawler._current_screen_id = "s_other"
        crawler._current_msg = None

        # Выполняем replay пути до Section
        ok = await crawler._replay_path(sec_screen_obj["screen_id"], sec_route["path"], sec_route["route_id"])
        assert ok is True

        # Проверяем: Section достигнут, route не стал stale
        assert crawler._current_screen_id == sec_screen_obj["screen_id"]
        assert crawler._current_msg.id == section_screen.id
        updated_sec_route = [r for r in state.routes_all(BOT) if r["route_id"] == sec_route["route_id"]][0]
        assert updated_sec_route["status"] == "active"

    asyncio.run(scenario())


def test_resume_with_pending_frontier_and_multi_message_start_pipeline(cfg, state, tmp_path):
    """Resume после перезапуска с pending frontier:
    полная цепочка EventRouter + Navigator + BotCrawler.
    - маршрут восстанавливается;
    - обход продолжается;
    - статус не становится skipped из-за Processing-сообщения."""
    writer = TimelineWriter(tmp_path / "nav_router_resume.jsonl")
    logger = ActionLogger(state, writer)
    router = EventRouter()

    processing = FakeMessage(301, "Processing…", out=False)
    menu = FakeMessage(302, "Actual menu", out=False,
                       reply_markup=inline_markup([[("Catalog", b"cat")]]))
    catalog_screen = FakeMessage(303, "Catalog items", out=False,
                                 reply_markup=inline_markup([[("Back", b"back")]]))

    class FullFakeClient:
        async def send_message(self, chat, text):
            # Ответ на /start: 2 сообщения
            router.feed("new", processing)
            router.feed("new", menu)
            return None

        async def get_messages(self, chat, ids=None):
            return None

    class LimiterStub:
        async def wait(self):
            return None
        async def acquire(self):
            return None

    class Step1Nav(FakeNavigator):
        async def send_start(self):
            self.starts += 1
            return PressOutcome(
                kind="new", message=processing,
                extra_messages=[("new", menu)],
                action_id="fake_start"
            )

    nav1 = Step1Nav(processing, {})
    crawler1, _ = make_crawler(cfg, state, nav1, BOT, tmp_path)

    async def init_state():
        await crawler1._start_conversation()

    asyncio.run(init_state())

    # Проверяем, что в frontier осталась задача для меню
    assert state.frontier_active_count(BOT) == 1

    # Симулируем перезапуск процесса: создаём crawler2 с resume=True и реальным Navigator + EventRouter
    nav2 = Navigator(
        FullFakeClient(), BOT, "chat", router, cfg, state, logger,
        LimiterStub(), LimiterStub(), FloodGate(),
    )

    async def fake_press_button(btn, msg_id):
        return PressOutcome(kind="edit", message=catalog_screen, action_id="press_cat")

    nav2.press_button = fake_press_button

    crawler2, _ = make_crawler(cfg, state, nav2, BOT, tmp_path)

    status = asyncio.run(crawler2.run(resume=True))
    assert status == "done"

    # Проверяем, что frontier не был пропущен (skipped), а успешно выполнен (done)
    frontier_rows = state._query("SELECT status FROM frontier WHERE bot=?", (BOT,))
    assert all(r["status"] == "done" for r in frontier_rows)
    assert not any(r["status"] == "skipped" for r in frontier_rows)

    # Проверяем, что переходы зафиксированы
    trs = state.transitions_all(BOT)
    cat_tr = [t for t in trs if t["action"] == "Catalog"]
    assert len(cat_tr) == 1
    assert cat_tr[0]["result_type"] == "edit"
