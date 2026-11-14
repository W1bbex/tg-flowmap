import sys
from pathlib import Path
from unittest.mock import patch

from run import (
    clean_input_path,
    execute_sast_scan,
    interactive_menu,
    is_telethon_configured,
    main,
    run_telegram_config_wizard,
)


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
    with patch("builtins.input", side_effect=["0"]) as mock_input:
        interactive_menu()
        assert mock_input.call_count == 1


def test_interactive_menu_demo():
    with patch("builtins.input", side_effect=["4", "0"]), patch("run.handle_demo_action") as mock_demo:
        interactive_menu()
        mock_demo.assert_called_once()


def test_main_with_drag_and_drop_argument():
    demo_path = Path(__file__).resolve().parent.parent.parent / "examples" / "sample_bot.py"
    with patch.object(sys, "argv", ["run.py", str(demo_path)]), patch("run.execute_sast_scan") as mock_sast, patch("run.wait_for_exit"):
        main()
        mock_sast.assert_called_once_with(demo_path.resolve())


def test_main_with_reserved_cli_command_delegates_to_cli(tmp_path: Path, monkeypatch):
    """Verify reserved CLI subcommands are not hijacked by drag-and-drop even if folder exists."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sast").mkdir()  # Directory named 'sast' exists in CWD

    with patch.object(sys, "argv", ["run.py", "sast", "bot.py"]), patch("tg_flowmap.cli.main") as mock_cli:
        main()
        mock_cli.assert_called_once()


def test_is_telethon_configured(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    assert not is_telethon_configured(cfg_file)

    # Incomplete or placeholder
    cfg_file.write_text('{"api_id": 0, "api_hash": "YOUR_TELEGRAM_API_HASH"}', encoding="utf-8")
    assert not is_telethon_configured(cfg_file)

    # Valid config
    cfg_file.write_text('{"api_id": 12345678, "api_hash": "0123456789abcdef0123456789abcdef"}', encoding="utf-8")
    assert is_telethon_configured(cfg_file)


def test_run_telegram_config_wizard_quick(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    with patch("builtins.input", side_effect=["1", "98765432", "abcdef0123456789abcdef0123456789"]):
        success = run_telegram_config_wizard(cfg_file)
        assert success is True
        assert cfg_file.exists()
        assert is_telethon_configured(cfg_file)

