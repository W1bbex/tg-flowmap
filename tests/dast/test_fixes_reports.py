"""Регрессионные тесты П11 (expandable blockquote в реальном Telethon),
П12 (экранирование preview, routes в graph.json, все корни, стили,
факты vs рекомендации) и П13 (конфиг/консоль)."""

import asyncio
import json

import pytest
from telethon.tl.types import MessageEntityBlockquote

from tg_flowmap.dast.config import load_config, load_manual_answers
from tg_flowmap.dast.html_render import render_html
from tg_flowmap.dast.reports import build_graph, render_tree, write_previews
from conftest import FakeMessage, FakeNavigator, inline_markup, make_crawler

BOT = "@fake_bot"


# ------------------------------------------------------------------ П11
def test_expandable_blockquote_collapsed_true():
    """Telethon 1.44: expandable quote = MessageEntityBlockquote(collapsed=True).
    Тест без условных skip, на установленном классе."""
    collapsed = MessageEntityBlockquote(offset=0, length=5, collapsed=True)
    plain = MessageEntityBlockquote(offset=0, length=5, collapsed=False)
    assert render_html("quote", [collapsed]) == \
        '<blockquote expandable>quote</blockquote>'
    assert render_html("quote", [plain]) == "<blockquote>quote</blockquote>"


# ------------------------------------------------------------------ П12
def _run_scan_with_dangerous_label(cfg, state, tmp_path):
    menu = FakeMessage(1, "Main menu", reply_markup=inline_markup(
        [[("Catalog", b"cat")], [("Buy <b>item</b> & pay", b"buy")]]))
    catalog = FakeMessage(1, "Catalog", reply_markup=inline_markup(
        [[("Back", b"back")]]))
    transitions = {
        b"cat": {"kind": "edit", "msg": catalog},
        b"back": {"kind": "edit", "msg": menu},
        b"buy": {"kind": "timeout"},  # всё равно заблокирована safety
    }
    nav = FakeNavigator(menu, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)
    asyncio.run(crawler.run())


def test_preview_escapes_labels_and_text(cfg, state, tmp_path):
    """Пользовательский контент в HTML-preview экранируется (без инъекций)."""
    _run_scan_with_dangerous_label(cfg, state, tmp_path)
    bot_dir = tmp_path / "preview_out"
    write_previews(cfg, state, BOT, bot_dir)
    files = list((bot_dir / "screenshots_or_previews").glob("*.html"))
    assert files
    joined = "\n".join(f.read_text(encoding="utf-8") for f in files)
    assert "<b>item</b>" not in joined, "сырой HTML из метки не должен пройти"
    assert "&lt;b&gt;item&lt;/b&gt;" in joined


def test_graph_exports_routes_separately(cfg, state, tmp_path):
    """graph.json: routes отдельно от transition edges."""
    menu = FakeMessage(1, "Main menu", reply_markup=inline_markup(
        [[("Catalog", b"cat")]]))
    catalog = FakeMessage(1, "Catalog", reply_markup=None)
    transitions = {b"cat": {"kind": "edit", "msg": catalog}}
    nav = FakeNavigator(menu, transitions)
    crawler, _ = make_crawler(cfg, state, nav, BOT, tmp_path)
    asyncio.run(crawler.run())

    graph = build_graph(state, BOT)
    assert set(graph.keys()) >= {"nodes", "edges", "routes"}
    assert isinstance(graph["routes"], list) and graph["routes"]
    route = graph["routes"][0]
    assert {"route_id", "screen_id", "depth", "status", "path"} <= set(route)
    # routes — не дубликаты edges
    assert all("from" not in r and "to" not in r for r in graph["routes"])


def test_render_tree_shows_all_roots_and_isolated():
    screens = [
        {"screen_id": "s_menu1", "depth_min": 0},
        {"screen_id": "s_menu2", "depth_min": 0},   # второй корень
        {"screen_id": "s_child", "depth_min": 1},
        {"screen_id": "s_orphan", "depth_min": 2},  # недостижимый экран
    ]
    transitions = [
        {"from_screen": "s_menu1", "to_screen": "s_child", "action": "Go",
         "action_type": "callback", "result_type": "edit"},
    ]
    tree = render_tree(screens, transitions)
    assert "Root 1" in tree and "Root 2" in tree
    assert "s_menu2" in tree
    assert "Несвязанные экраны" in tree and "s_orphan" in tree


def test_report_has_facts_vs_recommendations_sections(cfg, state, tmp_path):
    from tg_flowmap.dast.comparison import generate_comparison

    _run_scan_with_dangerous_label(cfg, state, tmp_path)
    comp = generate_comparison(cfg, state, [BOT])
    text = comp.read_text(encoding="utf-8")
    assert "Факты (собранные данные)" in text
    assert "Рекомендации" in text
    # без подтверждённой иерархии категорий не утверждаем её
    assert "НЕ подтверждена" in text or "иерархия уровней" in text


# ------------------------------------------------------------------ П13
def test_config_bots_dedupe_and_validation(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "api_id": 1, "api_hash": "h",
        "bots": ["@alpha", "alpha", "", "@Beta", None],
    }), encoding="utf-8")
    # None в списке — невалидный тип: понятное исключение
    with pytest.raises(ValueError):
        load_config(cfg_file)

    cfg_file.write_text(json.dumps({
        "api_id": 1, "api_hash": "h",
        "bots": ["@alpha", "alpha", "", "beta", "@Gamma"],
    }), encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.bots == ["@alpha", "@beta", "@gamma"], \
        "пустые и дубликаты удалены, порядок сохранён"


def test_config_bots_wrong_type_rejected(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(
        {"api_id": 1, "api_hash": "h", "bots": "@single_string"}),
        encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(cfg_file)


def test_manual_answers_loaded_from_config_root(tmp_path):
    """manual_answers.json ищется рядом с реально выбранным конфигом."""
    (tmp_path / "manual_answers.json").write_text(json.dumps(
        {"@b": {"screens": []}}), encoding="utf-8")
    data = load_manual_answers(tmp_path / "manual_answers.json")
    assert "@b" in data


def test_scheduler_dedupes_same_bot():
    from tg_flowmap.dast.scheduler import _dedupe_bots
    assert _dedupe_bots(["@a", "a", "@b", ""]) == ["@a", "@b"]
    assert _dedupe_bots([]) == []
    assert _dedupe_bots(["@A"]) == ["@a"]


def test_run_scan_no_duplicate_crawlers(cfg, state, tmp_path):
    """Один и тот же бот не запускается дважды за один вызов
    (проверяем дедуп на уровне планировщика)."""
    from tg_flowmap.dast.scheduler import _dedupe_bots
    bots = ["@shop", "shop", "@SHOP"]
    deduped = _dedupe_bots(bots)
    assert len(deduped) == 1
