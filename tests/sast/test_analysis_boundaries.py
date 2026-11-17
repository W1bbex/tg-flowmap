from pathlib import Path

from tg_flowmap.cli import run_analysis
from tg_flowmap.sast.parser import AstParser


def test_routes_use_their_own_module_constants(tmp_path):
    for name, route in (("a", "alpha"), ("b", "beta")):
        (tmp_path / (name + ".py")).write_text(
            f'ROUTE = "{route}"\nasync def handle(call):\n'
            '    if call.data == ROUTE:\n'
            f'        await call.message.answer("{route} screen")\n', encoding="utf-8"
        )
    parser = AstParser()
    parser.parse_dir(tmp_path)
    assert {key: Path(node.source_file).name for key, node in parser.nodes.items()} == {
        "cb:alpha": "a.py", "cb:beta": "b.py"
    }


def test_strict_rejects_unparseable_input(tmp_path, monkeypatch):
    path = tmp_path / "broken.py"
    path.write_text("async def broken(:", encoding="utf-8")
    monkeypatch.setattr("tg_flowmap.cli.load_env_token", lambda _: None)
    assert run_analysis(path, strict=True) == 1
