from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from telethon.tl.types import MessageEntityTextUrl
from tg_flowmap.dast.config import Config
from tg_flowmap.dast.html_render import render_html
from tg_flowmap.dast.navigation_graph import EdgeInfo, NavigationGraph
from tg_flowmap.dast.safety import SafetyFilter
from tg_flowmap.dast.state import State
from tg_flowmap.sast.parser import AstParser


def test_dijkstra_tie_breaker_equal_costs():
    """Ensures Dijkstra doesn't crash with TypeError when alternative paths have equal cost."""
    graph = NavigationGraph("@test_bot")
    graph.add_node("start")
    graph.add_node("mid1")
    graph.add_node("mid2")
    graph.add_node("target")

    # Path 1: start -> mid1 -> target (cost 1.0 + 1.0 = 2.0)
    edge1 = EdgeInfo("start", "act_mid1", "mid1", confidence=1.0)
    edge2 = EdgeInfo("mid1", "act_target1", "target", confidence=1.0)
    # Path 2: start -> mid2 -> target (cost 1.0 + 1.0 = 2.0)
    edge3 = EdgeInfo("start", "act_mid2", "mid2", confidence=1.0)
    edge4 = EdgeInfo("mid2", "act_target2", "target", confidence=1.0)

    graph.outgoing["start"] = [edge1, edge3]
    graph.outgoing["mid1"] = [edge2]
    graph.outgoing["mid2"] = [edge4]

    # Must find path cleanly without TypeError on heap comparison
    path = graph.find_shortest_path("start", "target")
    assert path is not None
    assert len(path) == 2

    # Also test find_nearest_screen_with_targets
    nearest = graph.find_nearest_screen_with_targets("start", {"target"})
    assert nearest is not None
    assert nearest[0] == "target"


def test_sqlite_isolation_level_none(tmp_path: Path):
    """Verifies SQLite connection uses isolation_level=None to avoid transaction conflicts."""
    db_file = tmp_path / "autocommit.db"
    state = State(db_file)
    assert state._conn.isolation_level is None

    # DML followed by manual BEGIN IMMEDIATE
    state.register_bot("@test_bot")
    with state.transaction() as conn:
        conn.execute("INSERT INTO bots(username) VALUES(?)", ("@bot2",))

    assert state.bot_info("@bot2") is not None
    state.close()


def test_safety_callback_data_and_danger_words():
    """Verifies that callback_data containing destructive words is blocked."""
    cfg = Config()
    safety = SafetyFilter(cfg)

    # Inoffensive label, but destructive callback_data
    can_press, reason = safety.button_verdict(
        label="Да, продолжить",
        button_type="callback",
        screen_text="Вы уверены?",
        callback_data=b"admin:delete_database",
    )
    assert can_press is False
    assert "danger_callback_word" in reason

    can_wipe, reason_wipe = safety.button_verdict(
        label="Дальше",
        button_type="callback",
        screen_text="Продолжить",
        callback_data=b"profile:wipe_all",
    )
    assert can_wipe is False
    assert "danger_callback_word" in reason_wipe


def test_parser_distinct_commands_not_merged_by_shared_keyboard(tmp_path: Path):
    """Ensures /help and /start are not merged into one screen when sharing a footer keyboard."""
    code = """
@dp.message_handler(commands=['start'])
async def start_cmd(message):
    await message.answer("Добро пожаловать в бот!", reply_markup=nav_markup)

@dp.message_handler(commands=['help'])
async def help_cmd(message):
    await message.answer("Справка по командам", reply_markup=nav_markup)
"""
    test_file = tmp_path / "bot.py"
    test_file.write_text(code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(test_file)

    assert "cmd:/start" in parser.nodes
    assert "cmd:/help" in parser.nodes
    assert parser.nodes["cmd:/start"].title == "/start"
    assert parser.nodes["cmd:/help"].title == "/help"


def test_parser_match_or_pattern(tmp_path: Path):
    """Verifies Python 3.10+ case 'a' | 'b': generates both callback nodes."""
    code = """
async def callback_handler(call):
    match call.data:
        case "menu" | "catalog":
            await call.message.answer("Раздел каталога")
"""
    test_file = tmp_path / "bot_match.py"
    test_file.write_text(code, encoding="utf-8")

    parser = AstParser()
    parser.parse_file(test_file)

    assert "cb:menu" in parser.nodes
    assert "cb:catalog" in parser.nodes


def test_html_render_blocks_javascript_urls():
    """Ensures html_render replaces javascript: with safe fallback href."""
    ent = MessageEntityTextUrl(offset=0, length=4, url="javascript:alert(1)")
    html_out = render_html("link", [ent])
    assert 'href="javascript:' not in html_out
    assert 'href="#"' in html_out


def test_cli_version_flags():
    """Verifies tg-flowmap --version and -v run without target requirement errors."""
    res_long = subprocess.run([sys.executable, "-m", "tg_flowmap", "--version"], capture_output=True, text=True)
    assert res_long.returncode == 0
    assert "tg-flowmap 1.0.0" in res_long.stdout

    res_short = subprocess.run([sys.executable, "-m", "tg_flowmap", "-v"], capture_output=True, text=True)
    assert res_short.returncode == 0
    assert "tg-flowmap 1.0.0" in res_short.stdout
