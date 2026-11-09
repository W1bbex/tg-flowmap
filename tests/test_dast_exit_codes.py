import json
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_flowmap import cli
from tg_flowmap.dast import reports, scheduler, state


@pytest.fixture
def dast_run(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"api_id": 12345, "api_hash": "test-api-hash"}), encoding="utf-8")
    scan = AsyncMock(return_value={"@test_bot": "done"})
    store = MagicMock()
    open_store = MagicMock(return_value=store)
    report = tmp_path / "report.md"
    generate = MagicMock(return_value={"report": report})
    monkeypatch.setattr(scheduler, "run_scan", scan)
    monkeypatch.setattr(state, "State", open_store)
    monkeypatch.setattr(reports, "generate_reports", generate)
    return config, scan, open_store, store, generate, report


@pytest.mark.parametrize("status, expected_code", [
    ("done", 0), ("paused", 0), ("limit_reached", 0), ("skipped", 0),
    ("error", 1), ("ERROR: resolve failed", 1), (None, 1),
])
def test_dast_exit_code_matches_scan_result_and_preserves_reports(dast_run, capsys, status, expected_code):
    config, scan, open_store, store, generate, report = dast_run
    scan.return_value = {} if status is None else {"@test_bot": status}

    result = cli.run_dast_scan("@test_bot", config_path=config)

    assert result == expected_code
    scan.assert_awaited_once()
    generate.assert_called_once()
    assert generate.call_args.args[1] is store
    store.close.assert_called_once()
    output = capsys.readouterr()
    assert str(report) in output.out
    if expected_code:
        assert "[ERROR]" in output.err
        assert "✅ Обход завершён!" not in output.out
    else:
        assert "[ERROR]" not in output.err


def test_dast_keyboard_interrupt_returns_130_and_preserves_reports(dast_run, capsys):
    config, scan, _, store, generate, _ = dast_run
    scan.side_effect = KeyboardInterrupt

    assert cli.run_dast_scan("@test_bot", config_path=config) == 130

    generate.assert_called_once()
    store.close.assert_called_once()
    assert "✅ Обход завершён!" not in capsys.readouterr().out


def test_dast_raised_error_returns_failure_before_opening_report_state(dast_run):
    config, scan, open_store, _, generate, _ = dast_run
    scan.side_effect = RuntimeError("scan failed")

    assert cli.run_dast_scan("@test_bot", config_path=config) == 1

    open_store.assert_not_called()
    generate.assert_not_called()


def test_dast_cli_propagates_failed_scan_exit_code(dast_run, monkeypatch):
    config, scan, _, _, generate, _ = dast_run
    scan.return_value = {"@test_bot": "error"}
    monkeypatch.setattr(sys, "argv", ["tg-flowmap", "dast", "@test_bot", "--config", str(config)])

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
    generate.assert_called_once()
