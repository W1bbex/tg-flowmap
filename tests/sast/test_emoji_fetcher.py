from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tg_flowmap.cli import load_env_token
from tg_flowmap.emoji_fetcher import (
    fetch_custom_emojis,
    get_default_cache_dir,
    load_cached_emoji,
)
from tg_flowmap.parser import AstParser


EMOJI_TEST_CODE = '''
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def menu_with_emojis():
    # 1. Dict style with custom emoji
    btn1 = {"text": "Статус", "callback_data": "status", "icon_custom_emoji_id": "543210001"}
    # 2. Call style
    btn2 = InlineKeyboardButton(text="Настройки", callback_data="settings", icon_custom_emoji_id="543210002")
    return {"inline_keyboard": [[btn1], [btn2]]}

def handle(data):
    if data == "status":
        send_message('<tg-emoji emoji-id="543210003">⭐</tg-emoji> Ваш статус: VIP', reply_markup=menu_with_emojis())
    elif data == "builder":
        builder = InlineKeyboardBuilder()
        builder.button(text="Профиль", callback_data="profile", icon_custom_emoji_id="543210004")
        send_message("Профиль", reply_markup=builder.as_markup())
'''


def test_parser_extracts_custom_emoji_ids():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(EMOJI_TEST_CODE)
        temp_path = Path(f.name)

    try:
        parser = AstParser()
        parser.parse_file(temp_path)

        assert "543210001" in parser.custom_emoji_ids
        assert "543210002" in parser.custom_emoji_ids
        assert "543210003" in parser.custom_emoji_ids
        assert "543210004" in parser.custom_emoji_ids
        assert len(parser.custom_emoji_ids) == 4

        # Verify button models contain icon_custom_emoji_id
        kb = parser.keyboards["menu_with_emojis"]
        buttons = kb.all_buttons()
        assert buttons[0].icon_custom_emoji_id == "543210001"
        assert buttons[1].icon_custom_emoji_id == "543210002"
    finally:
        temp_path.unlink(missing_ok=True)


def test_load_cached_emoji():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        dummy_bytes = b"RIFF....WEBPVP8X"
        emoji_id = "543210001"
        webp_file = cache_dir / f"{emoji_id}.webp"
        webp_file.write_bytes(dummy_bytes)

        res = load_cached_emoji(emoji_id, cache_dir)
        assert res is not None
        assert res.startswith("data:image/webp;base64,")

        expected_b64 = base64.b64encode(dummy_bytes).decode("ascii")
        assert expected_b64 in res

        # Non-existent emoji returns None
        assert load_cached_emoji("999999999", cache_dir) is None


def test_fetch_custom_emojis_from_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        emoji_id = "543210001"
        (cache_dir / f"{emoji_id}.webp").write_bytes(b"WEBP_DATA")

        # When all emojis are in cache, no network calls should be made
        res = fetch_custom_emojis("fake_token:123", [emoji_id], cache_dir=cache_dir)
        assert emoji_id in res
        assert res[emoji_id].startswith("data:image/webp;base64,")


def test_fetch_custom_emojis_mock_network():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        emoji_id = "543210005"

        stickers_response = {
            "ok": True,
            "result": [
                {
                    "custom_emoji_id": emoji_id,
                    "file_id": "file_123",
                    "thumbnail": {"file_id": "thumb_123"},
                }
            ],
        }
        get_file_response = {
            "ok": True,
            "result": {
                "file_id": "thumb_123",
                "file_path": "thumbnails/thumb_123.webp",
            },
        }
        fake_webp_bytes = b"FAKE_WEBP_IMAGE_CONTENT"

        def fake_urlopen(req, context=None, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            mock_resp = MagicMock()
            if "getCustomEmojiStickers" in url:
                mock_resp.read.return_value = json.dumps(stickers_response).encode("utf-8")
            elif "getFile" in url:
                mock_resp.read.return_value = json.dumps(get_file_response).encode("utf-8")
            elif "thumbnails/thumb_123.webp" in url:
                mock_resp.read.return_value = fake_webp_bytes
            else:
                raise ValueError(f"Unexpected URL: {url}")
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.__exit__.return_value = None
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res = fetch_custom_emojis("test_token:ABC", [emoji_id], cache_dir=cache_dir)

        assert emoji_id in res
        assert res[emoji_id].startswith("data:image/webp;base64,")

        # Verify cached file was written
        cached_file = cache_dir / f"{emoji_id}.webp"
        assert cached_file.exists()
        assert cached_file.read_bytes() == fake_webp_bytes


def test_load_env_token():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        env_file = tmp_path / ".env"
        env_file.write_text("TELEGRAM_BOT_TOKEN=123456789:AAFakeTokenValue\n", encoding="utf-8")

        with patch.dict("os.environ", {}, clear=True):
            token = load_env_token(tmp_path)
            assert token == "123456789:AAFakeTokenValue"
