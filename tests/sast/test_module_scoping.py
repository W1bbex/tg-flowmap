import ast
import tempfile
from pathlib import Path
from tg_flowmap.sast.parser import AstParser


def test_constants_scoped_by_module_with_unambiguous_fallback():
    code_a = """
TITLE = "Module A Title"
SHARED_BRAND = "SuperBot"

def get_kb():
    return {
        "inline_keyboard": [
            [{"text": TITLE, "callback_data": "a_data"}]
        ]
    }
"""
    code_b = """
TITLE = "Module B Title"

def get_other_kb():
    return {
        "inline_keyboard": [
            [{"text": TITLE, "callback_data": "b_data"}, {"text": SHARED_BRAND, "callback_data": "brand"}]
        ]
    }
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        file_a = tmp_path / "mod_a.py"
        file_b = tmp_path / "mod_b.py"
        file_a.write_text(code_a, encoding="utf-8")
        file_b.write_text(code_b, encoding="utf-8")

        parser = AstParser()
        parser.parse_dir(tmp_path)

        kb_a = parser.get_keyboard("get_kb", file_a)
        assert kb_a is not None
        assert kb_a.rows[0][0].text == "Module A Title"

        kb_b = parser.get_keyboard("get_other_kb", file_b)
        assert kb_b is not None
        assert kb_b.rows[0][0].text == "Module B Title"
        assert kb_b.rows[0][1].text == "SuperBot"


def test_keyboards_scoped_by_module_and_unambiguous_resolution():
    code_admin = """
def menu_kb():
    return {
        "inline_keyboard": [
            [{"text": "Admin Button", "callback_data": "admin:manage"}]
        ]
    }

@router.callback_query(F.data == "admin_entry")
async def handle_admin(call):
    await call.message.answer("Admin Area", reply_markup=menu_kb())
"""
    code_user = """
def menu_kb():
    return {
        "inline_keyboard": [
            [{"text": "User Button", "callback_data": "user:view"}]
        ]
    }

def unique_user_kb():
    return {
        "inline_keyboard": [
            [{"text": "Help Button", "callback_data": "user:help"}]
        ]
    }

@router.callback_query(F.data == "user_entry")
async def handle_user(call):
    await call.message.answer("User Area", reply_markup=menu_kb())
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        file_admin = tmp_path / "admin.py"
        file_user = tmp_path / "user.py"
        file_admin.write_text(code_admin, encoding="utf-8")
        file_user.write_text(code_user, encoding="utf-8")

        parser = AstParser()
        parser.parse_dir(tmp_path)

        # Both keyboards exist under qualified names
        assert "admin.menu_kb" in parser.keyboards
        assert "user.menu_kb" in parser.keyboards

        # File-scoped resolution resolves correctly
        admin_kb = parser.get_keyboard("menu_kb", file_admin)
        assert admin_kb is not None
        assert admin_kb.rows[0][0].callback_data == "admin:manage"

        user_kb = parser.get_keyboard("menu_kb", file_user)
        assert user_kb is not None
        assert user_kb.rows[0][0].callback_data == "user:view"

        # Unambiguous keyboard can be looked up bare or from any file
        unique_kb = parser.get_keyboard("unique_user_kb")
        assert unique_kb is not None
        assert unique_kb.rows[0][0].callback_data == "user:help"

        # Message nodes got the correct keyboards attached
        admin_node = next(n for n in parser.nodes.values() if Path(n.source_file).name == "admin.py")
        user_node = next(n for n in parser.nodes.values() if Path(n.source_file).name == "user.py")

        assert admin_node.keyboard is not None
        assert admin_node.keyboard.rows[0][0].callback_data == "admin:manage"

        assert user_node.keyboard is not None
        assert user_node.keyboard.rows[0][0].callback_data == "user:view"


def test_failed_edge_preserves_zero_values_after_reload():
    from tg_flowmap.dast.navigation_graph import NavigationGraph
    from tg_flowmap.dast.state import State

    state = State(":memory:")
    try:
        graph = NavigationGraph("@assessment", state)
        edge = graph.record_transition("source", "action", "target", success=False)
        before = (edge.confidence, edge.success_count)
        reloaded = NavigationGraph("@assessment", state).edges[("source", "action", "target")]
        assert (reloaded.confidence, reloaded.success_count) == before
    finally:
        state.close()


def test_false_boolean_branch_does_not_create_admin_callback(tmp_path):
    path = tmp_path / "sample.py"
    path.write_text(
        '''
SHOW_ADMIN = False
def keyboard():
    return {"inline_keyboard": [[{
        "text": "Open",
        "callback_data": "admin" if SHOW_ADMIN and True else "user"
    }]]}
''',
        encoding="utf-8",
    )
    parser = AstParser()
    parser.parse_file(path)
    buttons = parser.keyboards["keyboard"].all_buttons()
    assert [button.callback_data for button in buttons] == ["user"]

