from pathlib import Path
from tg_flowmap.sast.parser import AstParser
from tg_flowmap.sast.analyzer import GraphAnalyzer


def test_parser_captures_syntax_error_file(tmp_path: Path):
    valid_file = tmp_path / "valid.py"
    valid_file.write_text("print('hello world')", encoding="utf-8")

    broken_file = tmp_path / "broken.py"
    broken_file.write_text("def broken_syntax(:\n    pass", encoding="utf-8")

    parser = AstParser()
    parser.parse_dir(tmp_path)

    # Broken file must be tracked in skipped_files
    assert len(parser.skipped_files) == 1
    skipped_path, err_msg = parser.skipped_files[0]
    assert skipped_path == broken_file
    assert "SyntaxError" in err_msg

    # GraphAnalyzer must convert skipped files into Issues
    analyzer = GraphAnalyzer(
        parser.nodes,
        parser.keyboards,
        skipped_files=parser.skipped_files,
    )
    bot_map = analyzer.build_map()
    assert len(bot_map.issues) >= 1
    syntax_issues = [i for i in bot_map.issues if i.issue_type == "syntax_error"]
    assert len(syntax_issues) == 1
    assert "broken.py" in syntax_issues[0].source_file


def test_parse_file_captures_syntax_error(tmp_path: Path):
    broken_file = tmp_path / "single_broken.py"
    broken_file.write_text("class 123Broken:\n    pass", encoding="utf-8")

    parser = AstParser()
    parser.parse_file(broken_file)

    assert len(parser.skipped_files) == 1
    assert "SyntaxError" in parser.skipped_files[0][1]
