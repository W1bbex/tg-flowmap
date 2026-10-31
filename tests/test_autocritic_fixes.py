from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tg_flowmap.core.comparator import BotComparator
from tg_flowmap.dast.capture import extract_buttons
from tg_flowmap.dast.config import Config
from tg_flowmap.dast.safety import SafetyFilter, WALLET_REGEXES
from tg_flowmap.dast.screen_identity import buttons_signature, match_button_instance
from tg_flowmap.sast.emoji import load_cached_emoji, fetch_custom_emojis
import run


def test_run_wizard_no_name_error(tmp_path: Path) -> None:
    """Verifies that run.py functions use cfg_path and do not contain undefined cfg_file references."""
    source = inspect.getsource(run.run_telegram_config_wizard)
    assert "os.startfile(cfg_file)" not in source
    assert "os.startfile(cfg_path)" in source


def test_screen_identity_buttons_signature_none_url_comparison() -> None:
    """Verifies that buttons with None URL do not crash sorted() when compared with string URLs."""
    btn1 = {"row": 0, "col": 0, "label": "Btn", "button_type": "url", "url": None}
    btn2 = {"row": 0, "col": 0, "label": "Btn", "button_type": "url", "url": "https://example.com"}
    sig = buttons_signature([btn1, btn2])
    assert len(sig) == 1
    assert len(sig[0]) == 2


def test_screen_identity_row_col_none_fallback() -> None:
    """Verifies that explicit None in row/col does not cause TypeError in int()."""
    btn = {"row": None, "col": None, "label": "Test", "button_type": "callback"}
    sig = buttons_signature([btn])
    assert len(sig) == 1

    matched, conf, _ = match_button_instance({"row": None, "col": None, "label": "Test", "button_type": "callback"}, [btn])
    assert matched is not None
    assert conf == 1.0


def test_dast_config_to_dict_json_serializable(tmp_path: Path) -> None:
    """Verifies that custom_output_dir Path does not break json serialization in to_dict() and save()."""
    cfg = Config(root=tmp_path, custom_output_dir=tmp_path / "custom")
    d = cfg.to_dict()
    assert isinstance(d["custom_output_dir"], str)
    dumped = json.dumps(d)
    assert "custom" in dumped

    # Save to disk
    save_file = tmp_path / "cfg.json"
    cfg.save(save_file)
    assert save_file.exists()


def test_capture_empty_callback_data_preserved() -> None:
    """Verifies that b'' callback_data is preserved and not replaced by None."""
    class DummyButton:
        text = "Separator"
        data = b""

    class DummyRow:
        buttons = [DummyButton()]

    class DummyReplyMarkup:
        rows = [DummyRow()]

    buttons = extract_buttons(DummyReplyMarkup(), message_id=1)
    assert len(buttons) == 1
    assert buttons[0].callback_data == b""


def test_emoji_load_cached_invalid_ntfs_chars(tmp_path: Path) -> None:
    """Verifies that invalid filename characters in emoji_id do not throw WinError 123."""
    res = load_cached_emoji("$ICONS[star]*:?", tmp_path)
    assert res is None


def test_emoji_fetch_custom_emojis_filters_non_digits(tmp_path: Path) -> None:
    """Verifies that non-digit emoji IDs are filtered out without making requests."""
    res = fetch_custom_emojis("test_token", ["$VAR_ICON", "star*"], cache_dir=tmp_path)
    assert res == {}


def test_comparator_extract_metrics_nodes_list() -> None:
    """Verifies that extract_metrics_from_bot_map supports bot_map with nodes as a list (DAST format)."""
    bot_map = {
        "nodes": [
            {
                "id": "screen_1",
                "keyboard": {
                    "rows": [[{"label": "Btn1"}], [{"label": "Btn2"}]]
                }
            }
        ],
        "issues": [{"issue_type": "dead_end"}],
    }
    metrics = BotComparator.extract_metrics_from_bot_map(bot_map)
    assert metrics["screens_count"] == 1
    assert metrics["buttons_count"] == 2
    assert metrics["dead_ends"] == 1


def test_safety_manual_answers_without_at_prefix() -> None:
    """Verifies manual_answer lookup works regardless of whether @ prefix is present."""
    manual = {
        "testbot": {
            "screens": [{"match": "Enter promo", "answer": "12345"}]
        }
    }
    ans = SafetyFilter.manual_answer(manual, "@testbot", "Enter promo")
    assert ans == "12345"

    ans2 = SafetyFilter.manual_answer(manual, "testbot", "Enter promo")
    assert ans2 == "12345"


def test_safety_tron_regex_case_sensitivity() -> None:
    """Verifies that TRON wallet regex requires capital T and is case-sensitive."""
    tron_pat = WALLET_REGEXES[1]
    valid_tron = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    lowercase_false_positive = "t1234567890abcdef1234567890abcdef1"

    assert tron_pat.search(valid_tron) is not None
    assert tron_pat.search(lowercase_false_positive) is None
