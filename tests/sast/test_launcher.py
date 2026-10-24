import sys
from pathlib import Path
from unittest.mock import patch

from run import clean_input_path, execute_sast_scan, interactive_menu, main


def test_clean_input_path_quotes_and_resolution(tmp_path: Path):
    test_file = tmp_path / "test_bot.py"
    test_file.write_text("# bot", encoding="utf-8")

    # Raw quoted string
    quoted_input = f'"{test_file}"'
    resolved = clean_input_path(quoted_input)
    assert resolved is not None
    assert resolved == test_file.resolve()

    # Empty string
    assert clean_input_path("") is None
    assert clean_input_path("   ") is None

    # Non-existent path
    assert clean_input_path("non_existent_folder_abc_123") is None


def test_execute_sast_scan_generates_artifacts(tmp_path: Path):
    demo_path = Path(__file__).resolve().parent.parent.parent / "examples" / "sample_bot.py"
    assert demo_path.exists(), "examples/sample_bot.py must exist"

    with patch("webbrowser.open") as mock_open:
        exit_code = execute_sast_scan(demo_path)
        assert exit_code == 0
        mock_open.assert_called_once()

    output_dir = demo_path.parent.parent / "output"
    assert (output_dir / "sample_bot_map.html").exists()
    assert (output_dir / "sample_bot_report.md").exists()
    assert (output_dir / "sample_bot_data.json").exists()


def test_interactive_menu_exit():
    with patch("builtins.input", side_effect=["0"]):
        # Must exit cleanly without throwing exceptions
        interactive_menu()


def test_interactive_menu_demo():
    with patch("builtins.input", side_effect=["4"]), patch("webbrowser.open"):
        interactive_menu()


def test_main_with_drag_and_drop_argument():
    demo_path = Path(__file__).resolve().parent.parent.parent / "examples" / "sample_bot.py"
    with patch.object(sys, "argv", ["run.py", str(demo_path)]), patch("webbrowser.open"):
        main()
