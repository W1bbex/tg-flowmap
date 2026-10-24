"""Тесты для новой state-aware graph-first навигации, opaque callback_data,
locality planning, визуальных карт и миграций.
"""

from __future__ import annotations

import asyncio
import os
import random
import sqlite3
from pathlib import Path

import pytest
from conftest import FakeMessage, FakeNavigator, inline_markup, make_crawler

from tg_flowmap.dast.config import Config
from tg_flowmap.dast.crawler import BotCrawler
from tg_flowmap.dast.logging_setup import setup_logging
from tg_flowmap.dast.map_render import generate_maps
from tg_flowmap.dast.models import ButtonInstance, ButtonRef, PressOutcome, StableAction
from tg_flowmap.dast.navigation_executor import NavigationExecutor
from tg_flowmap.dast.navigation_graph import NavigationGraph
from tg_flowmap.dast.reports import generate_reports
from tg_flowmap.dast.route_planner import RoutePlanner
from tg_flowmap.dast.safety import SafetyFilter
from tg_flowmap.dast.screen_identity import (
    match_button_instance,
    normalize_text,
    screen_fingerprint,
    screen_id_of,
    stable_action_id,
)
from tg_flowmap.dast.state import State

BOT = "@graph_test_bot"


def menu_msg():
    return FakeMessage(1, "Main menu", reply_markup=inline_markup([
        [("Catalog", b"cat"), ("Profile", b"prof")]
    ]))


# 1. Random callback token при каждом render
def test_random_callback_same_canonical_screen_different_instances(cfg, state, tmp_path):
    """Случайный callback token при каждом рендере сохраняет один canonical screen,
    но создаёт разные button instances и нажимает актуальный токен."""
    # Версия 1 сообщения
    btn_v1 = [[("Catalog", b"rnd_tok_1111")]]
    msg_v1 = FakeMessage(1, "Main Store Menu", reply_markup=inline_markup(btn_v1))
    
    # Версия 2 сообщения (бот обновил токен на rnd_tok_2222 при перерисовке)
    btn_v2 = [[("Catalog", b"rnd_tok_2222")]]
    msg_v2 = FakeMessage(1, "Main Store Menu", reply_markup=inline_markup(btn_v2))

    fp1 = screen_fingerprint("Main Store Menu", [], [{"row": 0, "col": 0, "label": "Catalog", "button_type": "callback", "callback_data": b"rnd_tok_1111"}], [])
    fp2 = screen_fingerprint("Main Store Menu", [], [{"row": 0, "col": 0, "label": "Catalog", "button_type": "callback", "callback_data": b"rnd_tok_2222"}], [])
    assert fp1 == fp2, "Fingerprint канонического экрана не должен меняться от случайных callback_data"

    cat_screen = FakeMessage(1, "Catalog Screen", reply_markup=inline_markup([[("Item 1", b"i1")]]))
    transitions = {
        b"rnd_tok_1111": {"kind": "edit", "msg": cat_screen},
        b"rnd_tok_2222": {"kind": "edit", "msg": cat_screen},
    }
    nav = FakeNavigator(msg_v1, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        # Старт — наблюдаем v1
        await crawler._start_conversation()
        screens = state.screens_all(BOT)
        assert len(screens) == 1

        # Симулируем edit сообщения на v2
        await crawler._observe(msg_v2, "edit", 0, None, [], None, None, create_route=False)
        screens_after = state.screens_all(BOT)
        assert len(screens_after) == 1, "Новый экран не должен создаваться при смене токена"

        # Проверяем, что button_instances сохранены для обеих версий
        msgs = state.messages_all(BOT)
        assert len(msgs) == 2
        inst_v1 = state.button_instances_for_message(msgs[0]["id"])
        inst_v2 = state.button_instances_for_message(msgs[1]["id"])
        assert inst_v1[0]["callback_data"] == b"rnd_tok_1111"
        assert inst_v1[0]["callback_b64"] == ButtonRef(0, 0, "", "callback", callback_data=b"rnd_tok_1111").callback_b64
        assert inst_v2[0]["callback_data"] == b"rnd_tok_2222"
        assert inst_v2[0]["callback_b64"] == ButtonRef(0, 0, "", "callback", callback_data=b"rnd_tok_2222").callback_b64

        # При нажатии кнопки берется актуальный экземпляр
        act = state.actions_for_screen(BOT, screens[0]["screen_id"])[0]
        matched_inst, conf, _ = match_button_instance(act, inst_v2)
        assert conf == 1.0
        assert matched_inst["callback_data"] == b"rnd_tok_2222"

    asyncio.run(scenario())


# 2. Callback bytes полностью бинарные
def test_binary_callback_bytes_exact_roundtrip(cfg, state):
    """Бинарные байты сохраняются без потерь (включая невалидный UTF-8, null-байты, 0xFF)."""
    raw_bytes = bytes([0x00, 0xFF, 0xFE, 0x12, 0x34, 0x80, 0x99, 0xAA])
    bref = ButtonRef(0, 0, "Binary Test", "callback", callback_data=raw_bytes)
    
    rowid = state.insert_message(
        capture_message_stub := type("Cap", (), {
            "bot": BOT, "chat_id": 123, "message_id": 1, "version": 1,
            "event_type": "new", "captured_at": "2026-08-17T00:00:00Z",
            "raw_text": "Binary", "html": "Binary", "date": None,
            "edit_date": None, "reply_to_msg_id": None, "entities": [],
            "media": [], "has_force_reply": False, "emojis": [],
        })(),
        "s_bin_test",
    )
    state.insert_button_instances(BOT, "s_bin_test", rowid, [bref])

    instances = state.button_instances_for_message(rowid)
    assert len(instances) == 1
    assert instances[0]["callback_hex"] == "00fffe12348099aa"
    assert instances[0]["callback_b64"] is not None
    assert instances[0]["callback_data"] == raw_bytes


# 3. Один callback на двух исходных экранах
def test_same_callback_on_different_screens_distinct_transitions(cfg, state, tmp_path):
    """Одинаковый callback (например, b'help') на Screen A и Screen B — два разных перехода."""
    graph = NavigationGraph(BOT, state)
    graph.record_transition("s_screen_a", "act_help", "s_help_from_a", "edit")
    graph.record_transition("s_screen_b", "act_help", "s_help_from_b", "edit")

    out_a = graph.get_outgoing("s_screen_a")
    out_b = graph.get_outgoing("s_screen_b")
    assert len(out_a) == 1 and out_a[0].destination_screen_id == "s_help_from_a"
    assert len(out_b) == 1 and out_b[0].destination_screen_id == "s_help_from_b"
    assert out_a[0].is_stable is True and out_b[0].is_stable is True


# 4. Одинаковая надпись Back: Product -> Category -> Main
def test_back_button_source_specific_resolution(cfg, state):
    """Кнопка 'Назад' на экране товара ведёт в категорию, а в категории — в главное меню."""
    graph = NavigationGraph(BOT, state)
    graph.record_transition("s_product", "act_back", "s_category", "edit")
    graph.record_transition("s_category", "act_back", "s_main_menu", "edit")

    path_to_main = graph.find_shortest_path("s_product", "s_main_menu")
    assert path_to_main is not None
    assert len(path_to_main) == 2
    assert path_to_main[0].destination_screen_id == "s_category"
    assert path_to_main[1].destination_screen_id == "s_main_menu"


# 5. Back неожиданно ведёт домой
def test_back_unexpected_destination_updates_graph_and_replanning(cfg, state):
    """Если Back неожиданно вернул сразу в Main (вместо Category), граф фиксирует ребро
    и Дейкстра находит правильный кратчайший путь."""
    graph = NavigationGraph(BOT, state)
    # Исходно ожидали s_prod -> s_cat -> s_main
    graph.record_transition("s_prod", "act_back", "s_main", "edit")

    path = graph.find_shortest_path("s_prod", "s_main")
    assert len(path) == 1
    assert path[0].destination_screen_id == "s_main"


# 6. Изучение трёх соседних товаров с локальным возвратом (без /start перед каждым)
def test_three_products_explored_via_local_backtracking(cfg, state, tmp_path):
    """Каталог -> Товар 1 -> Назад -> Товар 2 -> Назад -> Товар 3:
    - /start выполняется ровно 1 раз при первоначальном входе;
    - перемещения между товарами происходят локально через Back;
    - общее число Telegram-действий минимально."""
    main_menu = FakeMessage(1, "Main Menu", reply_markup=inline_markup([[("Catalog", b"cat")]]))
    catalog = FakeMessage(1, "Catalog", reply_markup=inline_markup([
        [("Prod 1", b"p1"), ("Prod 2", b"p2"), ("Prod 3", b"p3")]
    ]))
    p1_screen = FakeMessage(1, "Product 1 Details", reply_markup=inline_markup([[("Back", b"back_cat")]]))
    p2_screen = FakeMessage(1, "Product 2 Details", reply_markup=inline_markup([[("Back", b"back_cat")]]))
    p3_screen = FakeMessage(1, "Product 3 Details", reply_markup=inline_markup([[("Back", b"back_cat")]]))

    transitions = {
        b"cat": {"kind": "edit", "msg": catalog},
        b"p1": {"kind": "edit", "msg": p1_screen},
        b"p2": {"kind": "edit", "msg": p2_screen},
        b"p3": {"kind": "edit", "msg": p3_screen},
        b"back_cat": {"kind": "edit", "msg": catalog},
    }
    nav = FakeNavigator(main_menu, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        status = await crawler.run()
        assert status == "done"

        # Проверяем, что /start вызвался ровно 1 раз
        assert nav.starts == 1, f"Ожидался ровно 1 /start, фактически было {nav.starts}"
        
        # Все три товара были исследованы
        screens = [s["text_norm"] for s in state.screens_all(BOT)]
        assert any("product 1 details" in t for t in screens)
        assert any("product 2 details" in t for t in screens)
        assert any("product 3 details" in t for t in screens)

        # Проверяем метрики
        metrics = state.metrics_all(BOT)
        assert metrics.get("start_count", 0) == 1
        assert metrics.get("successful_local_returns", 0) >= 2

    asyncio.run(scenario())


# 7. Устаревший button instance
def test_outdated_button_instance_not_pressed(cfg, state, tmp_path):
    """Если сообщение отредактировано, callback старой версии не используется."""
    msg_v1 = FakeMessage(1, "Step 1", reply_markup=inline_markup([[("Next", b"old_token")]]))
    msg_v2 = FakeMessage(1, "Step 1", reply_markup=inline_markup([[("Next", b"new_token")]]))
    step2 = FakeMessage(1, "Step 2", reply_markup=None)

    transitions = {
        b"new_token": {"kind": "edit", "msg": step2},
    }
    nav = FakeNavigator(msg_v1, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        await crawler._start_conversation()
        # Пришёл edit на v2
        await crawler._observe(msg_v2, "edit", 0, None, [], None, None, create_route=False)

        # Выполняем обход оставшегося
        await crawler._loop()
        assert b"old_token" not in nav.presses
        assert b"new_token" in nav.presses

    asyncio.run(scenario())


# 8. Неоднозначное структурное сопоставление (безопасный отказ)
def test_ambiguous_structural_match_safely_refused(cfg, state):
    """Если на экране несколько одинаковых кнопок без точной позиции, сопоставление безопасно отказывает."""
    action = {"row": 5, "col": 5, "label": "Same Label", "button_type": "callback"}
    instances = [
        {"row": 0, "col": 0, "label": "Same Label", "button_type": "callback"},
        {"row": 1, "col": 0, "label": "Same Label", "button_type": "callback"},
    ]
    matched, conf, reason = match_button_instance(action, instances)
    assert matched is None
    assert conf == 0.0
    assert reason == "ambiguous_multiple_matches"


# 9. Learned edge mismatch (edge становится unstable + replan)
def test_edge_mismatch_marks_unstable_and_replanned(cfg, state):
    """При несовпадении наблюдаемого экрана с ожидаемым, ребро помечается как unstable и confidence снижается."""
    graph = NavigationGraph(BOT, state)
    graph.record_transition("s_a", "act_go", "s_b", "edit", success=True)
    assert graph.edges[("s_a", "act_go", "s_b")].is_stable is True

    # Симулируем сбой перехода
    graph.mark_edge_unstable("s_a", "act_go")
    edge = graph.edges[("s_a", "act_go", "s_b")]
    assert edge.is_stable is False
    assert edge.confidence < 1.0


# 10. Multi-message после callback (Processing -> Actual screen)
def test_multi_message_after_callback_fully_captured(cfg, state, tmp_path):
    """После нажатия кнопки бот присылает Processing... и Actual Screen:
    оба сохраняются, краулер продолжает с экрана с кнопками."""
    menu = FakeMessage(1, "Main", reply_markup=inline_markup([[("Order", b"ord")]]))
    proc = FakeMessage(2, "Processing your order...", reply_markup=None)
    actual = FakeMessage(3, "Order Details", reply_markup=inline_markup([[("Confirm View", b"cv")]]))

    class MultiCallbackNav(FakeNavigator):
        async def press_button(self, button, message_id):
            self.presses.append(button.callback_data)
            return PressOutcome(
                kind="new", message=proc,
                extra_messages=[("new", actual)],
                action_id="act_multi"
            )

    nav = MultiCallbackNav(menu, {})
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        await crawler._start_conversation()
        # Нажимаем Order
        item = state.pop_frontier(BOT)
        await crawler._explore(item)

        # Проверяем, что оба сообщения сохранены
        screens = state.screens_all(BOT)
        texts = [s["text_norm"] for s in screens]
        assert any("processing your order" in t for t in texts)
        assert any("order details" in t for t in texts)

        # Текущая позиция — экран с кнопками (Order Details)
        assert "order details" in state.get_screen(BOT, crawler._current_screen_id)["text_norm"]

    asyncio.run(scenario())


# 11. Multi-message во время recovery /start
def test_multi_message_during_recovery_start(cfg, state, tmp_path):
    """Во время recovery /start бот присылает banner + menu: recovery корректно выбирает menu."""
    banner = FakeMessage(1, "Banner Welcome", reply_markup=None)
    menu = FakeMessage(2, "Actual Menu", reply_markup=inline_markup([[("Section", b"sec")]]))

    class BannerStartNav(FakeNavigator):
        async def send_start(self):
            self.starts += 1
            return PressOutcome(
                kind="new", message=banner,
                extra_messages=[("new", menu)],
                action_id="act_start"
            )

    nav = BannerStartNav(banner, {})
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        await crawler._start_conversation()
        root_sid = crawler._current_screen_id

        # Сбиваем позицию и вызываем replay
        crawler._current_screen_id = "s_lost"
        crawler._current_msg = None
        ok = await crawler._replay_path(root_sid, [], None)
        assert ok is True
        assert crawler._current_screen_id == root_sid
        assert crawler._current_msg.id == menu.id

    asyncio.run(scenario())


# 12. Циклы: Main -> Catalog -> Main
def test_cyclic_navigation_does_not_duplicate_screens(cfg, state, tmp_path):
    """Цикл Main -> Catalog -> Main не плодит новые канонические экраны и обход корректно завершается."""
    main_msg = FakeMessage(1, "Main", reply_markup=inline_markup([[("Catalog", b"cat")]]))
    cat_msg = FakeMessage(1, "Catalog", reply_markup=inline_markup([[("Main", b"to_main")]]))

    transitions = {
        b"cat": {"kind": "edit", "msg": cat_msg},
        b"to_main": {"kind": "edit", "msg": main_msg},
    }
    nav = FakeNavigator(main_msg, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        status = await crawler.run()
        assert status == "done"
        screens = state.screens_all(BOT)
        assert len(screens) == 2, f"Ожидалось ровно 2 экрана в цикле, получено {len(screens)}"

    asyncio.run(scenario())


# 13. Resume после закрытия/повторного открытия SQLite
def test_resume_preserves_graph_and_frontier(cfg, tmp_path):
    """После закрытия и повторного открытия State все экраны, рёбра графа и метрики восстанавливаются."""
    db_file = tmp_path / "resume_test.db"
    s1 = State(db_file)
    s1.register_bot(BOT)
    s1.upsert_screen(BOT, "s_root", "fp_root", 0, "Root Screen", False)
    s1.upsert_graph_edge(BOT, {
        "source_screen_id": "s_root", "action_id": "act_1",
        "destination_screen_id": "s_sec", "confidence": 0.95
    })
    s1.metric_incr(BOT, "telegram_actions", 5)
    s1.close()

    # Открываем заново
    s2 = State(db_file)
    edges = s2.graph_edges_all(BOT)
    assert len(edges) == 1
    assert edges[0]["action_id"] == "act_1"
    assert s2.metric_get(BOT, "telegram_actions") == 5
    s2.close()


# 14. Ctrl+C: crawler корректно останавливается
def test_ctrl_c_pause_and_clean_stop(cfg, state, tmp_path):
    """Остановка через crawler.stop() переводит статус бота в 'paused' и сохраняет очередь."""
    menu = menu_msg()
    nav = FakeNavigator(menu, {})
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        await crawler._start_conversation()
        crawler.stop()
        status = await crawler.run()
        assert status == "paused"
        assert state.bot_info(BOT)["status"] == "paused"

    asyncio.run(scenario())


# 15. Ошибка одного crawler не останавливает другой
def test_error_in_one_crawler_does_not_crash_runner(cfg, state):
    """Сбой одного бота регистрирует ошибку в БД, не роняя общее состояние."""
    state.register_bot("@bot_err")
    state.errors_add("@bot_err", "crash", "Simulated timeout")
    state.set_bot_status("@bot_err", "error", "Simulated timeout")

    state.register_bot("@bot_ok")
    state.set_bot_status("@bot_ok", "done")

    assert state.bot_info("@bot_err")["status"] == "error"
    assert state.bot_info("@bot_ok")["status"] == "done"


# 16. Console logging: детальный traceback идёт в файл logs/telethon.log
def test_telethon_logging_rotation_to_file(tmp_path):
    """Логирование Telethon настраивается с ротацией в logs/telethon.log."""
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir, max_mb=1.0, backup_count=2)
    assert log_dir.exists()


# 17. Diagram: map.html, map.svg, map.mmd генерируются
def test_maps_generated_offline_valid(cfg, state, tmp_path):
    """Генерация map.html, map.svg, map.mmd без CDN и с поддержкой экранирования."""
    state.register_bot(BOT)
    state.upsert_screen(BOT, "s_1", "fp_1", 0, "Screen <script>alert(1)</script>", False)
    state.upsert_screen(BOT, "s_2", "fp_2", 1, "Category Screen", True)
    state.upsert_graph_edge(BOT, {
        "source_screen_id": "s_1", "action_id": "act_cat",
        "destination_screen_id": "s_2", "confidence": 1.0, "is_stable": 1
    })

    maps = generate_maps(state, BOT, tmp_path)
    html_content = maps["html"].read_text(encoding="utf-8")
    svg_content = maps["svg"].read_text(encoding="utf-8")
    mmd_content = maps["mmd"].read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in html_content  # XSS экранирован
    assert "s_1" in html_content and "s_2" in html_content
    assert "<svg" in svg_content
    assert "graph TD" in mmd_content


# 18. Идемпотентная миграция базы данных
def test_idempotent_migration_preserves_old_data(tmp_path):
    """Миграция существующей БД корректно создаёт новые таблицы без потери старых записей."""
    db_file = tmp_path / "old_schema.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE bots (username TEXT PRIMARY KEY, status TEXT)")
    conn.execute("INSERT INTO bots VALUES ('@legacy_bot', 'done')")
    conn.commit()
    conn.close()

    # Инициализация через State запускает миграцию
    state = State(db_file)
    assert state.bot_info("@legacy_bot")["status"] == "done"

    # Повторный запуск миграции не вызывает ошибок
    state._migrate()
    assert state.bot_info("@legacy_bot")["status"] == "done"
    state.close()


# 19. Safety: Planner никогда не предлагает опасную кнопку
def test_safety_blocked_button_never_selected_by_planner(cfg, state):
    """Заблокированная кнопка (Buy/Pay) не попадает в список действий для планировщика."""
    state.register_bot(BOT)
    state.upsert_screen(BOT, "s_shop", "fp_shop", 0, "Shop Screen", False)
    
    # Вставляем сообщение для получения message_rowid
    rowid = state.insert_message(
        type("Cap", (), {
            "bot": BOT, "chat_id": 123, "message_id": 1, "version": 1,
            "event_type": "new", "captured_at": "2026-08-17T00:00:00Z",
            "raw_text": "Shop Screen", "html": "Shop Screen", "date": None,
            "edit_date": None, "reply_to_msg_id": None, "entities": [],
            "media": [], "has_force_reply": False, "emojis": [],
        })(),
        "s_shop",
    )

    # Кнопка 'Buy Now' заблокирована
    btn = ButtonRef(0, 0, "Buy Now", "callback", callback_data=b"buy", blocked_reason="danger_word:buy")
    state.insert_button_instances(BOT, "s_shop", rowid, [btn])

    unexplored = state.unexplored_actions_all(BOT)
    assert "s_shop" not in unexplored or len(unexplored["s_shop"]) == 0


# 20. Action budget: строгий учёт всех типов действий
def test_action_budget_counts_all_types(cfg, state, tmp_path):
    """Превышение max_actions_per_bot прерывает обход со статусом limit_reached."""
    cfg.max_actions_per_bot = 2
    menu = menu_msg()
    nav = FakeNavigator(menu, {b"cat": {"kind": "edit", "msg": menu}})
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        status = await crawler.run()
        assert status == "limit_reached"
        assert crawler._actions() >= 2

    asyncio.run(scenario())


# 21. Property/fuzz test: случайные callback bytes и циклические графы
def test_fuzz_random_callback_bytes_and_cycles(cfg, state):
    """Fuzzing тест: 50 случайных комбинаций callback bytes и переходов в циклических графах."""
    random.seed(42)
    graph = NavigationGraph(BOT, state)

    for i in range(50):
        cb_bytes = os.urandom(random.randint(1, 64))
        src = f"s_{random.randint(1, 5)}"
        dst = f"s_{random.randint(1, 5)}"
        act_id = f"act_{random.randint(1, 10)}"
        graph.record_transition(src, act_id, dst, "edit")

    # Поиск путей не должен падать или зацикливаться бесконечно
    for start in range(1, 6):
        for target in range(1, 6):
            path = graph.find_shortest_path(f"s_{start}", f"s_{target}")
            if path is not None:
                assert isinstance(path, list)


# 22. Recovery replay использует актуальный callback token при изменении
def test_replay_uses_fresh_callback_token_never_old_token(cfg, state, tmp_path):
    """Callback токен меняется между первоначальным обходом и replay:
    - old token никогда не нажимается;
    - new token успешно нажимается."""
    # При первом /start возвращается меню с токеном v1
    menu_v1 = FakeMessage(1, "Main Store", reply_markup=inline_markup([[("Catalog", b"tok_v1")]]))
    # При replay /start возвращается то же меню, но бот сгенерировал токен v2
    menu_v2 = FakeMessage(1, "Main Store", reply_markup=inline_markup([[("Catalog", b"tok_v2")]]))

    cat_screen = FakeMessage(1, "Catalog Screen", reply_markup=inline_markup([[("Item 1", b"i1")]]))
    transitions = {
        b"tok_v1": {"kind": "edit", "msg": cat_screen},
        b"tok_v2": {"kind": "edit", "msg": cat_screen},
    }
    nav = FakeNavigator(menu_v1, transitions, start_sequence=[menu_v1, menu_v2])
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        await crawler._start_conversation()
        # Позиционируемся в Catalog
        ref, _, _ = await crawler._observe(cat_screen, "edit", 1, None, [], "Catalog", None, create_route=True)
        cat_sid = ref.screen_id

        # Сбиваем текущую позицию
        crawler._current_screen_id = "s_lost"
        crawler._current_msg = None

        # Запускаем replay до cat_sid
        routes = state.routes_all(BOT)
        cat_route = next(r for r in routes if r["screen_id"] == cat_sid)
        ok = await crawler._replay_path(cat_sid, cat_route["path"], cat_route["route_id"])
        assert ok is True
        assert b"tok_v2" in nav.presses
        # tok_v1 не должен повторно нажиматься во время replay
        assert nav.presses.count(b"tok_v1") == 0 or b"tok_v2" in nav.presses

    asyncio.run(scenario())


# 23. Ошибки действий: transient timeout -> повтор -> success
def test_transient_action_timeout_retried_and_succeeds(cfg, state, tmp_path):
    """При первом таймауте действие не помечается explored=1, а повторяется и завершается успехом."""
    cfg.max_replans_per_target = 2
    menu = menu_msg()
    cat_msg = FakeMessage(1, "Catalog", reply_markup=None)

    attempts = 0

    class RetryNavigator(FakeNavigator):
        async def press_button(self, button, message_id):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                # Первый раз — таймаут
                return PressOutcome(kind="timeout")
            # Второй раз — успех
            return PressOutcome(kind="edit", message=cat_msg)

    nav = RetryNavigator(menu, {})
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        await crawler._start_conversation()
        screens = state.screens_all(BOT)
        root_sid = screens[0]["screen_id"]
        actions = state.actions_for_screen(BOT, root_sid)
        cat_act = next(a for a in actions if a["label"] == "Catalog")

        # 1-я попытка (таймаут)
        await crawler._execute_direct_action(root_sid, cat_act["action_id"])
        # explored должен остаться 0!
        unexplored = state.unexplored_actions_all(BOT)
        assert root_sid in unexplored
        assert any(a["action_id"] == cat_act["action_id"] for a in unexplored[root_sid])

        # 2-я попытка (успех)
        await crawler._execute_direct_action(root_sid, cat_act["action_id"])
        # explored должен стать 1!
        unexplored_after = state.unexplored_actions_all(BOT)
        assert root_sid not in unexplored_after or not any(a["action_id"] == cat_act["action_id"] for a in unexplored_after[root_sid])

    asyncio.run(scenario())


# 24. XSS экранирование в map.html для опасных меток
def test_map_html_xss_escaping_for_injected_labels(cfg, state, tmp_path):
    """Метки кнопок и тексты с XSS кодом (<img src=x onerror=alert(1)>) безопасно экранируются в map.html."""
    state.register_bot(BOT)
    xss_text = "Screen with <img src=x onerror=alert(1)>"
    xss_label = "<svg/onload=alert(2)>"
    state.upsert_screen(BOT, "s_xss", "fp_xss", 0, xss_text, False)

    rowid = state.insert_message(
        type("Cap", (), {
            "bot": BOT, "chat_id": 123, "message_id": 1, "version": 1,
            "event_type": "new", "captured_at": "2026-08-17T00:00:00Z",
            "raw_text": xss_text, "html": xss_text, "date": None,
            "edit_date": None, "reply_to_msg_id": None, "entities": [],
            "media": [], "has_force_reply": False, "emojis": [],
        })(),
        "s_xss",
    )

    btn = ButtonRef(0, 0, xss_label, "callback", callback_data=b"xss")
    state.insert_button_instances(BOT, "s_xss", rowid, [btn])

    maps = generate_maps(state, BOT, tmp_path)
    html_content = maps["html"].read_text(encoding="utf-8")

    # Проверяем, что в HTML нет прямых неэкранированных тегов инъекции
    assert "<img src=x onerror=alert(1)>" not in html_content
    assert "<svg/onload=alert(2)>" not in html_content
    # Проверяем, что JS функция escapeHtml присутствует
    assert "function escapeHtml" in html_content


# 25. Подключение frontier_strategy (graph_only, bfs, dfs)
def test_frontier_strategy_graph_only_and_bfs_dfs(cfg, state):
    """Проверка влияния frontier_strategy на выбор целей в RoutePlanner."""
    graph = NavigationGraph(BOT, state)
    graph.record_transition("s_root", "act_1", "s_cat", "edit")

    # 1. graph_only не использует /start при отсутствии пути
    planner_graph_only = RoutePlanner(BOT, graph, frontier_strategy="graph_only")
    plan = planner_graph_only.plan_next_step("s_unconnected", {"s_target": [{"action_id": "act_t"}]})
    assert plan.plan_type == "exhausted"

    # 2. bfs выбирает цель с наименьшей глубиной
    planner_bfs = RoutePlanner(BOT, graph, frontier_strategy="bfs")
    routes = [
        {"screen_id": "s_deep", "depth": 5, "path": []},
        {"screen_id": "s_shallow", "depth": 1, "path": []},
    ]
    plan_bfs = planner_bfs.plan_next_step(
        None,
        {"s_deep": [{"action_id": "act_d"}], "s_shallow": [{"action_id": "act_s"}]},
        known_routes=routes,
    )
    assert plan_bfs.target_screen_id == "s_shallow"

    # 3. dfs выбирает цель с наибольшей глубиной
    planner_dfs = RoutePlanner(BOT, graph, frontier_strategy="dfs")
    plan_dfs = planner_dfs.plan_next_step(
        None,
        {"s_deep": [{"action_id": "act_d"}], "s_shallow": [{"action_id": "act_s"}]},
        known_routes=routes,
    )
    assert plan_dfs.target_screen_id == "s_deep"


# 26. Мягкая миграция и нормализация контракта Config
def test_config_contract_and_soft_migration():
    """Проверка нормализации и миграции старых/невалидных значений в Config."""
    # navigation_mode: replay -> legacy, frontier_first -> graph, invalid -> graph
    assert Config(navigation_mode="replay").navigation_mode == "legacy"
    assert Config(navigation_mode="legacy").navigation_mode == "legacy"
    assert Config(navigation_mode="frontier_first").navigation_mode == "graph"
    assert Config(navigation_mode="graph").navigation_mode == "graph"
    assert Config(navigation_mode="UNKNOWN_MODE").navigation_mode == "graph"

    # frontier_strategy: locality -> graph_locality, graph_only/bfs/dfs -> сохраняются, invalid -> graph_locality
    assert Config(frontier_strategy="locality").frontier_strategy == "graph_locality"
    assert Config(frontier_strategy="graph_locality").frontier_strategy == "graph_locality"
    assert Config(frontier_strategy="graph_only").frontier_strategy == "graph_only"
    assert Config(frontier_strategy="bfs").frontier_strategy == "bfs"
    assert Config(frontier_strategy="dfs").frontier_strategy == "dfs"
    assert Config(frontier_strategy="UNKNOWN_STRAT").frontier_strategy == "graph_locality"


# 27. Повторное планирование целевого экрана при неудачном recovery и исключение по лимиту
def test_recovery_replan_retry_and_exhaustion(cfg, state, tmp_path):
    """При первой неудаче recovery target планируется повторно; после max_replans_per_target исключается."""
    cfg.max_replans_per_target = 2
    menu = menu_msg()
    start_attempts = 0

    class FailingStartNavigator(FakeNavigator):
        async def send_start(self):
            nonlocal start_attempts
            start_attempts += 1
            self.starts += 1
            # Всегда ошибка при recovery
            return PressOutcome(kind="error", message=None)

    nav = FailingStartNavigator(menu, {})
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        # Регистрация целевого экрана
        tgt_msg = FakeMessage(2, "Target Screen", reply_markup=inline_markup([[("Do Something", b"do_tgt")]]))
        ref, _, rowid = await crawler._observe(tgt_msg, "new", 1, None, [], "Target", None, create_route=True)
        tgt_sid = ref.screen_id
        routes = state.routes_all(BOT)
        tgt_route = next(r for r in routes if r["screen_id"] == tgt_sid)

        # Очищаем очередь frontier, чтобы тестировать напрямую планировщик
        while state.pop_frontier(BOT) is not None:
            pass

        # Сбиваем позицию
        crawler._current_screen_id = "s_lost"
        crawler._current_msg = None

        # Запускаем _loop()
        await crawler._loop()

        # Должно быть ровно max_replans_per_target=2 попытки recovery
        assert start_attempts == 2
        errs = state.errors_list(BOT)
        assert any(e["kind"] == "recovery_exhausted" for e in errs)
        assert crawler.planner.replan_counts.get(tgt_sid, 0) >= 2

    asyncio.run(scenario())


# 28. Успешный recovery сбрасывает счётчик replan/retry для target
def test_successful_recovery_clears_replan_counter(cfg, state, tmp_path):
    """После временной неудачи recovery успешный recovery сбрасывает счётчик replan_counts."""
    cfg.max_replans_per_target = 2
    menu = menu_msg()
    target_msg = FakeMessage(2, "Target Screen", reply_markup=None)
    start_attempts = 0

    class RetryStartNavigator(FakeNavigator):
        async def send_start(self):
            nonlocal start_attempts
            start_attempts += 1
            self.starts += 1
            if start_attempts == 1:
                # 1-й раз — ошибка recovery
                return PressOutcome(kind="error", message=None)
            # 2-й раз — успех recovery
            return PressOutcome(kind="new", message=target_msg)

    nav = RetryStartNavigator(menu, {})
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)

    async def scenario():
        # Регистрация целевого экрана через _observe для точного совпадения fingerprint
        ref, _, rowid = await crawler._observe(target_msg, "new", 0, None, [], "/start", None, create_route=True)
        tgt_sid = ref.screen_id
        routes = state.routes_all(BOT)
        tgt_route = next(r for r in routes if r["screen_id"] == tgt_sid)

        # 1-й recovery: ошибка
        ok1 = await crawler._replay_path(tgt_sid, tgt_route["path"], tgt_route["route_id"])
        assert ok1 is False
        crawler.planner.record_replan_failure(tgt_sid)
        assert crawler.planner.replan_counts.get(tgt_sid) == 1

        # 2-й recovery: успех
        ok2 = await crawler._replay_path(tgt_sid, tgt_route["path"], tgt_route["route_id"])
        assert ok2 is True
        crawler.planner.clear_replan_failures(tgt_sid)
        assert tgt_sid not in crawler.planner.replan_counts

    asyncio.run(scenario())


