import ast
from tg_flowmap.core.models import Button, Keyboard, MessageNode
from tg_flowmap.sast.analyzer import GraphAnalyzer
from tg_flowmap.sast.evaluator import evaluate_ast_node


def test_fstring_wildcard_matching_roadmap_stage1():
    # Test that f-strings evaluate with wildcard * for dynamic parts
    tree = ast.parse('f"ag_switch:{acc_id}"')
    evaluated = evaluate_ast_node(tree.body[0].value)
    assert evaluated == "ag_switch:*"

    # Test that GraphAnalyzer connects callback "ag_switch:*" to router "cb:ag_switch:*"
    btn = Button(text="Switch", callback_data="ag_switch:*")
    kb = Keyboard(rows=[[btn]], name="switch_kb")
    nodes = {
        "screen_root": MessageNode(id="screen_root", title="Root", keyboard=kb),
        "cb:ag_switch:*": MessageNode(id="cb:ag_switch:*", title="ag_switch:*"),
    }
    analyzer = GraphAnalyzer(nodes, {"switch_kb": kb})
    bot_map = analyzer.build_map()

    # Must resolve cleanly without dead_end
    dead_ends = [i for i in bot_map.issues if i.issue_type == "dead_end"]
    assert len(dead_ends) == 0

    # Must connect edge to cb:ag_switch:*
    edge = [e for e in bot_map.edges if e.from_node_id == "screen_root"][0]
    assert edge.to_node_id == "cb:ag_switch:*"


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
