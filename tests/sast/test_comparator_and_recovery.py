from __future__ import annotations

import ast
from pathlib import Path

from tg_flowmap.core.comparator import BotComparator
from tg_flowmap.core.models import BotMap, Button, Keyboard, MessageNode
from tg_flowmap.dast.map_render import _render_map_mmd
from tg_flowmap.dast.models import CallbackResult
from tg_flowmap.dast.navigation_executor import NavigationExecutor
from tg_flowmap.dast.state import State
from tg_flowmap.sast.evaluator import evaluate_ast_node


def test_navigation_executor_does_not_corrupt_ascii_callbacks():
    """Ensures callback strings of 4 chars (like 'menu', 'user') are not decoded to garbage."""
    executor = NavigationExecutor("@dummy", None, None, None)
    inst = {"label": "Menu", "callback_data": "menu", "button_type": "callback"}
    btn_ref = executor._to_button_ref(inst, 123)
    assert btn_ref.callback_data == b"menu"

    inst_user = {"label": "User", "callback_data": "user", "button_type": "callback"}
    btn_user = executor._to_button_ref(inst_user, 123)
    assert btn_user.callback_data == b"user"


def test_comparator_handles_none_keyboards_and_botmap_object():
    """Tests that BotComparator handles both dicts with None keyboards and BotMap dataclasses."""
    bot_map = BotMap()
    node = MessageNode(id="test", title="Test", source_file="b.py", line_number=1)
    node.keyboard = None
    bot_map.nodes["test"] = node

    dict_with_none_kb = {
        "nodes": {
            "root": {"keyboard": None, "title": "Root"},
            "sub": {"keyboard": {"rows": [[{"text": "Btn"}]]}},
        },
        "issues": [],
    }

    comparator = BotComparator("BotA", bot_map, "BotB", dict_with_none_kb)
    metrics_a, metrics_b = comparator._resolve_metrics()
    assert metrics_a["screens_count"] == 1
    assert metrics_b["screens_count"] == 2
    assert metrics_b["buttons_count"] == 1

    md = comparator.build_comparison_markdown()
    assert "BotA" in md
    assert "BotB" in md


def test_evaluator_recursion_guard_and_tuples_sets_unary():
    """Tests max recursion depth protection and handling of UnaryOp, Tuple, Set."""
    # Recursive variable resolution
    tree = ast.parse("-42")
    assert evaluate_ast_node(tree.body[0].value) == -42

    tree_tuple = ast.parse("('/start', '/help')")
    assert evaluate_ast_node(tree_tuple.body[0].value) == ("/start", "/help")

    tree_set = ast.parse("{'a', 'b'}")
    assert evaluate_ast_node(tree_set.body[0].value) == {"a", "b"}

    # Cyclic variable
    local_vars = {"a": ast.Name(id="b"), "b": ast.Name(id="a")}
    res = evaluate_ast_node(ast.Name(id="a"), local_vars=local_vars, max_depth=5)
    # Should terminate gracefully without RecursionError
    assert res is None or isinstance(res, str)


def test_mermaid_syntax_recovery_edges():
    """Ensures Mermaid generation doesn't produce invalid double-pipe syntax."""
    nodes = [{"id": "s1", "text_norm": "Screen 1"}, {"id": "s2", "text_norm": "Screen 2"}]
    edges = [{"source": "s1", "target": "s2", "label": "back", "result_type": "recovery"}]
    mmd = _render_map_mmd("@test_bot", nodes, edges)
    assert "|recovery||" not in mmd
    assert '-.->|"recovery: back"|' in mmd


def test_state_json_clean_bytes(tmp_path: Path):
    """Ensures state.py handles bytes in timeline payloads and callbacks without TypeError."""
    db_file = tmp_path / "test.db"
    state = State(db_file)
    state.register_bot("@test_bot")

    # Timeline with bytes payload
    payload = {"data": b"\x01\x02raw", "text": "hello"}
    state.timeline_create("act_1", "@test_bot", "press", payload)

    # Callback with raw bytes
    res = CallbackResult(alert=False, raw={"raw_bytes": b"somedata"})
    with state.transaction() as conn:
        cur = conn.execute("INSERT INTO buttons(bot, label) VALUES(?, ?)", ("@test_bot", "Btn"))
        btn_id = cur.lastrowid
    cb_id = state.add_callback("@test_bot", btn_id, "act_1", res)
    assert cb_id > 0
    callbacks = state.callbacks_all("@test_bot")
    assert len(callbacks) == 1
    assert "$bytes" in callbacks[0]["raw_json"]
    assert "c29tZWRhdGE=" in callbacks[0]["raw_json"]


def test_gitignore_protects_telethon_sessions():
    """Verifies that .gitignore explicitly protects session files."""
    repo_root = Path(__file__).resolve().parents[2]
    gitignore_text = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert "*.session" in gitignore_text
    assert "*.session-journal" in gitignore_text
