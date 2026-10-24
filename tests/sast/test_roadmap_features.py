import ast
from pathlib import Path
from tg_flowmap.core.models import Button, Keyboard, MessageNode
from tg_flowmap.sast.analyzer import GraphAnalyzer
from tg_flowmap.sast.evaluator import evaluate_ast_node
from tg_flowmap.sast.parser import AstParser


def test_fstring_wildcard_matching_roadmap_stage1():
    # Test that f-strings evaluate with wildcard * for dynamic parts
    tree = ast.parse('f"profile_switch:{user_id}"')
    evaluated = evaluate_ast_node(tree.body[0].value)
    assert evaluated == "profile_switch:*"

    # Test that GraphAnalyzer connects callback "profile_switch:*" to router "cb:profile_switch:*"
    btn = Button(text="Switch", callback_data="profile_switch:*")
    kb = Keyboard(rows=[[btn]], name="switch_kb")
    nodes = {
        "screen_root": MessageNode(id="screen_root", title="Root", keyboard=kb),
        "cb:profile_switch:*": MessageNode(id="cb:profile_switch:*", title="profile_switch:*"),
    }
    analyzer = GraphAnalyzer(nodes, {"switch_kb": kb})
    bot_map = analyzer.build_map()

    # Must resolve cleanly without dead_end
    dead_ends = [i for i in bot_map.issues if i.issue_type == "dead_end"]
    assert len(dead_ends) == 0

    # Must connect edge to cb:profile_switch:*
    edge = [e for e in bot_map.edges if e.from_node_id == "screen_root"][0]
    assert edge.to_node_id == "cb:profile_switch:*"


def test_root_hub_missing_back_suppression_roadmap_stage2():
    # Root menu keyboard (used by cmd:/start)
    btn_start = Button(text="Каталог", callback_data="catalog")
    main_kb = Keyboard(rows=[[btn_start]], name="main_menu_markup")

    # Command /exit that returns user to main menu
    nodes = {
        "cmd:/start": MessageNode(id="cmd:/start", title="/start", keyboard=main_kb),
        "cmd:/exit": MessageNode(id="cmd:/exit", title="/exit", keyboard=main_kb),
    }
    analyzer = GraphAnalyzer(nodes, {"main_menu_markup": main_kb})
    bot_map = analyzer.build_map()

    # /exit uses main_menu_markup, so it must NOT have MISSING_BACK warning!
    exit_missing_back = [
        i for i in bot_map.issues 
        if i.issue_type == "missing_back" and i.node_id == "cmd:/exit"
    ]
    assert len(exit_missing_back) == 0


def test_project_wide_keyboard_matching_resolves_modular_handlers():
    # Keyboard created in an unattached module or class (not directly bound to a handler)
    btn_action = Button(text="Запуск сценария", callback_data="wizard_start_setup")
    modular_kb = Keyboard(rows=[[btn_action]], name="wizard_card_markup")

    # Handler waiting in a router file
    nodes = {
        "cb:wizard_start_setup": MessageNode(
            id="cb:wizard_start_setup",
            title="wizard_start_setup",
        ),
    }

    # Pass keyboards containing modular_kb
    analyzer = GraphAnalyzer(nodes, {"wizard_card_markup": modular_kb})
    bot_map = analyzer.build_map()

    # The handler must NOT be marked as dangling because its button exists in project keyboards!
    dangling = [
        i for i in bot_map.issues
        if i.issue_type == "dangling_handler" and i.node_id == "cb:wizard_start_setup"
    ]
    assert len(dangling) == 0


def test_default_args_ternary_and_nested_row_mutations(tmp_path: Path):
    markups_py = tmp_path / "markups.py"
    markups_py.write_text(
        '''
class MarkupsMixin:
    def main_menu_markup(self):
        return {
            "inline_keyboard": [
                [{"text": "Flow", "callback_data": "open_flow"}],
                [{"text": "Direct", "callback_data": "open_direct"}],
                [{"text": "Builder", "callback_data": "builder_open"}],
            ]
        }

    def item_choice_markup(self, prefix="flow_item"):
        cancel_cb = "flow_cancel" if prefix == "flow_item" else "menu"
        return {
            "inline_keyboard": [
                [{"text": "Option A", "callback_data": f"{prefix}:a"}],
                [{"text": "Отмена", "callback_data": cancel_cb}],
            ]
        }

    def builder_markup(self, draft=None):
        keyboard = [[{"text": "+ Step", "callback_data": "builder_add:1"}]]
        action_row = []
        cancel_btn = {"text": "Отмена", "callback_data": "builder_cancel"}
        action_row.append(cancel_btn)
        keyboard.append(action_row)
        return {"inline_keyboard": keyboard}
''',
        encoding="utf-8",
    )

    router_py = tmp_path / "router.py"
    router_py.write_text(
        '''
def route_callback(app, data):
    if data == "open_flow":
        markup = app.ui.item_choice_markup("flow_item")
        app.ui.send_message(1, "Choose", reply_markup=markup)
    if data == "open_direct":
        markup = app.ui.item_choice_markup("direct_item")
        app.ui.send_message(1, "Choose direct", reply_markup=markup)
    if data.startswith("flow_item:"):
        app.ui.answer_callback("ok")
    if data.startswith("direct_item:"):
        app.ui.answer_callback("ok")
    if data == "flow_cancel":
        app.ui.answer_callback("cancelled")
    if data == "builder_open":
        markup = app.ui.builder_markup()
        app.ui.send_message(1, "Builder", reply_markup=markup)
    if data.startswith("builder_add:"):
        markup = app.ui.builder_markup()
        app.ui.send_message(1, "Builder updated", reply_markup=markup)
    if data == "builder_cancel":
        app.ui.answer_callback("cancelled")
''',
        encoding="utf-8",
    )

    parser = AstParser()
    parser.parse_dir(tmp_path)
    bot_map = GraphAnalyzer(
        parser.nodes,
        parser.keyboards,
        screen_aliases=parser.screen_aliases,
        hub_return_nodes=parser.hub_return_nodes,
    ).build_map()

    assert len(bot_map.issues) == 0


def test_issue_source_file_points_to_keyboard_file():
    broken_btn = Button(text="Broken", callback_data="non_existent_cb", line_number=412)
    kb = Keyboard(name="shared_markup", rows=[[broken_btn]], source_file="markups.py", line_number=400)
    node = MessageNode(
        id="cb:open_screen",
        title="open_screen",
        keyboard=kb,
        source_file="router.py",
        line_number=50,
    )
    bot_map = GraphAnalyzer({"cb:open_screen": node}, {"shared_markup": kb}).build_map()
    dead_ends = [i for i in bot_map.issues if i.issue_type == "dead_end"]
    assert len(dead_ends) == 1
    assert dead_ends[0].source_file == "markups.py"
    assert dead_ends[0].line_number == 412


