"""Тесты построения графа/дерева и генерации отчётов."""

import asyncio

from tg_flowmap.dast.reports import (
    build_callbacks_json,
    build_graph,
    generate_reports,
    render_tree,
)
from tg_flowmap.dast.models import CallbackResult
from conftest import FakeMessage, FakeNavigator, inline_markup

BOT = "@fake_bot"


def _screens_rows():
    return [
        {"screen_id": "s_menu", "depth_min": 0},
        {"screen_id": "s_cat", "depth_min": 1},
        {"screen_id": "s_item", "depth_min": 2},
    ]


def _transitions_rows():
    return [
        {"from_screen": "s_menu", "to_screen": "s_cat", "action": "Catalog",
         "action_type": "callback", "result_type": "edit"},
        {"from_screen": "s_cat", "to_screen": "s_item", "action": "Xbox",
         "action_type": "callback", "result_type": "edit"},
        # цикл назад: не должен размножать дерево
        {"from_screen": "s_item", "to_screen": "s_menu", "action": "Back",
         "action_type": "callback", "result_type": "edit"},
    ]


def test_render_tree_shape():
    tree = render_tree(_screens_rows(), _transitions_rows())
    lines = tree.splitlines()
    assert lines[0].startswith("Root 1")
    assert any("── Catalog" in l for l in lines)
    assert any("└── Back" in l and "(повтор)" in l for l in lines)
    assert any("└── Xbox" in l for l in lines) or any("├── Xbox" in l for l in lines)


def test_render_tree_empty():
    assert render_tree([], []) == "(экранов нет)"


def _run_happy_scan(cfg, state, tmp_path):
    from conftest import make_crawler as mk

    def menu_msg():
        return FakeMessage(1, "Main menu",
                           reply_markup=inline_markup([[("Catalog", b"cat"),
                                                        ("Profile", b"prof")]]))

    def catalog_msg():
        return FakeMessage(1, "Catalog",
                           reply_markup=inline_markup([
                               [("Back", b"back")],
                               [("Info", b"info"), ("Item $100", b"item100")]]))

    def profile_msg():
        return FakeMessage(1, "Profile", reply_markup=inline_markup(
            [[("Back", b"back2")]]))

    def card_msg():
        return FakeMessage(1, "Card $100", reply_markup=inline_markup(
            [[("Back", b"cardback")]]))

    transitions = {
        b"cat": {"kind": "edit", "msg": catalog_msg()},
        b"prof": {"kind": "edit", "msg": profile_msg()},
        b"back": {"kind": "edit", "msg": menu_msg()},
        b"back2": {"kind": "edit", "msg": menu_msg()},
        b"info": {"kind": "answer_only", "msg": None,
                  "callback": CallbackResult(message="FYI", alert=False)},
        b"item100": {"kind": "edit", "msg": card_msg()},
        b"cardback": {"kind": "edit", "msg": catalog_msg()},
    }
    nav = FakeNavigator(menu_msg(), transitions)
    crawler, _ = mk(cfg, state, nav, BOT, tmp_path)
    asyncio.run(crawler.run())
    return nav


def test_build_graph_nodes_and_edges(cfg, state, tmp_path):
    _run_happy_scan(cfg, state, tmp_path)
    g = build_graph(state, BOT)
    assert len(g["nodes"]) == len(state.screens_all(BOT))
    ids = {n["id"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["from"] in ids
        assert e["action"] and e["action_type"] and e["result_type"]
    # у узлов есть кнопки с callback_data/hex и текст
    node_with_buttons = [n for n in g["nodes"] if n["buttons"]]
    assert node_with_buttons
    b = node_with_buttons[0]["buttons"][0]
    assert {"row", "col", "label", "button_type", "callback_hex"} <= set(b)


def test_callbacks_json_links_answer(cfg, state, tmp_path):
    _run_happy_scan(cfg, state, tmp_path)
    rows = build_callbacks_json(state, BOT)
    info = [r for r in rows if r["button"] == "Info"]
    assert info, "callback Info должен быть в callbacks.json"
    assert info[0]["answer"] == "FYI"
    assert info[0]["result"] == "answer_only"
    assert info[0]["next_screen"] is None
    assert info[0]["callback_data_hex"] == b"info".hex()


def test_generate_reports_files(cfg, state, tmp_path):
    _run_happy_scan(cfg, state, tmp_path)
    paths = generate_reports(cfg, state, BOT)
    bot_dir = paths["report"].parent
    for name in ("graph.json", "report.md", "messages.json", "callbacks.json",
                 "premium_emojis.json", "timeline.json", "errors.log"):
        assert (bot_dir / name).exists(), f"{name} не создан"
    preview_dir = bot_dir / "screenshots_or_previews"
    assert preview_dir.exists() and list(preview_dir.glob("*.html"))
    report = (bot_dir / "report.md").read_text(encoding="utf-8")
    assert "Карта экранов" in report
    assert "├──" in report or "└──" in report
    assert "Полный путь" in report
    # comparison.md по всем ботам
    from tg_flowmap.dast.comparison import generate_comparison
    comp = generate_comparison(cfg, state, [BOT])
    assert comp.exists()
    assert "Сравнение" in comp.read_text(encoding="utf-8")
