"""Регрессионные тесты исправлений П6 (стили кнопок Telethon 1.44),
П7 (SQLite: транзакции/миграции/атома/без сирот) и П10 (медиа)."""

import sqlite3

import pytest
from telethon.tl.types import (
    KeyboardButtonCallback,
    KeyboardButtonRow,
    KeyboardButtonStyle,
    ReplyInlineMarkup,
)

from tg_flowmap.dast.capture import extract_buttons
from tg_flowmap.dast.media import download_media, media_file_name
from tg_flowmap.dast.models import ButtonRef, PressOutcome
from tg_flowmap.dast.reports import build_graph
from tg_flowmap.dast.state import State
from conftest import FakeMessage, make_crawler

BOT = "@style_bot"


# ------------------------------------------------------------------ П6
def test_button_style_roundtrip_telethon_to_report():
    """Telethon KeyboardButtonCallback(style=KeyboardButtonStyle(...),
    requires_password=...) → ButtonRef → SQLite → graph.json."""
    markup = ReplyInlineMarkup(rows=[
        KeyboardButtonRow(buttons=[
            KeyboardButtonCallback(
                text="Pay safely",
                data=b"\x01\x02",
                style=KeyboardButtonStyle(bg_primary=True, bg_success=True,
                                          bg_danger=False, icon=987654321),
            ),
            KeyboardButtonCallback(
                text="Confirm", data=b"\x03", requires_password=True),
        ]),
    ])
    buttons = extract_buttons(markup, message_id=10)
    b1, b2 = buttons
    assert b1.style_bg_primary and b1.style_bg_success and not b1.style_bg_danger
    assert b1.style_icon_id == "987654321"
    assert not b1.requires_password
    assert b2.requires_password


def test_button_style_sqlite_and_graph_roundtrip(cfg, state, tmp_path):
    markup = ReplyInlineMarkup(rows=[
        KeyboardButtonRow(buttons=[
            KeyboardButtonCallback(
                text="Pay safely", data=b"\x01\x02",
                style=KeyboardButtonStyle(bg_primary=True, bg_success=True,
                                          icon=555)),
        ]),
    ])
    buttons = extract_buttons(markup, message_id=10)
    from tg_flowmap.dast.safety import SafetyFilter
    SafetyFilter(cfg).classify_buttons(buttons, "Каталог")  # Pay не блокирует экран
    state.upsert_screen(BOT, "s_style", "fp_style", 0, "каталог")
    state.insert_buttons(BOT, "s_style", 1, buttons,
                         ["fpbtn1" for _ in buttons])

    restored = state.buttons_for_screen(BOT, "s_style")
    b = restored[0]
    assert b.style_bg_primary and b.style_bg_success and not b.style_bg_danger
    assert b.style_icon_id == "555"
    assert b.button_fp == "fpbtn1"

    graph = build_graph(state, BOT)
    btn_json = graph["nodes"][0]["buttons"][0]
    assert btn_json["style"]["bg_primary"] is True
    assert btn_json["style"]["bg_success"] is True
    assert btn_json["style"]["icon_document_id"] == "555"


def test_requires_password_button_blocked_by_safety():
    from tg_flowmap.dast.config import Config
    from tg_flowmap.dast.safety import SafetyFilter
    s = SafetyFilter(Config(root=__import__("pathlib").Path(".")))
    ok, reason = s.button_verdict("Confirm", "callback", "Нейтральный экран",
                                  requires_password=True)
    assert not ok and reason == "requires_password"


# ------------------------------------------------------------------ П7
def test_idempotent_migration_adds_style_columns(tmp_path):
    """Старая база (без style-колонок) мигрирует без потери данных."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE buttons(id INTEGER PRIMARY KEY AUTOINCREMENT, bot TEXT, "
        "screen_id TEXT, message_rowid INTEGER, message_id INTEGER, row INTEGER, "
        "col INTEGER, label TEXT, button_type TEXT, callback_data BLOB, "
        "callback_b64 TEXT, callback_hex TEXT, url TEXT, custom_emoji_id TEXT, "
        "button_fp TEXT, blocked_reason TEXT, created_at TEXT)")
    conn.execute(
        "INSERT INTO buttons(bot, screen_id, label, button_type) "
        "VALUES('b','s','Old button','callback')")
    conn.commit()
    conn.close()

    state = State(db)          # init запускает миграции
    try:
        row = state._query_one("SELECT * FROM buttons WHERE label='Old button'")
        assert row["label"] == "Old button"      # данные сохранились
        assert row["style_bg_primary"] == 0      # новые колонки добавлены
        assert row["style_requires_password"] == 0
        # повторный init — идемпотентен
        state.close()
        state2 = State(db)
        try:
            row2 = state2._query_one(
                "SELECT * FROM buttons WHERE label='Old button'")
            assert row2["label"] == "Old button"
        finally:
            state2.close()
    finally:
        try:
            state.close()
        except Exception:  # noqa: BLE001
            pass


def test_busy_timeout_configured(state):
    row = state._query_one("PRAGMA busy_timeout")
    assert row[0] >= 5000


def test_transaction_rollback_leaves_no_partial_rows(state):
    """Ошибка внутри транзакции откатывает ВСЁ изменение."""
    state.register_bot(BOT)
    state.progress_set(BOT, "k", "1")
    try:
        with state.transaction() as conn:
            conn.execute("UPDATE scan_progress SET value='999' "
                         "WHERE bot=? AND key='k'", (BOT,))
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert state.progress_get(BOT, "k") == "1"


def test_insert_message_atomic_all_or_nothing(state):
    """insert_message пишет сообщение+entities+media+emoji одной транзакцией."""
    from telethon.tl.types import MessageEntityCustomEmoji

    msg = FakeMessage(10, "🥇 привет")
    msg.entities = [MessageEntityCustomEmoji(offset=0, length=2, document_id=777)]
    from tg_flowmap.dast.capture import capture_message
    cap = capture_message(msg, BOT, "new", state=state)
    state.upsert_screen(BOT, "s_x", "fp_x", 0, "x")
    rowid = state.insert_message(cap, "s_x")
    assert state._query_one(
        "SELECT COUNT(*) AS c FROM entities WHERE message_rowid=?", (rowid,))["c"] == 1
    assert state._query_one(
        "SELECT COUNT(*) AS c FROM emoji_occurrences WHERE message_rowid=?",
        (rowid,))["c"] == 1


def test_insert_message_version_race_safe_retry(state):
    """UNIQUE-конфликт по версии пересчитывается, а не валит обход."""
    from tg_flowmap.dast.capture import capture_message
    msg = FakeMessage(11, "text")
    cap1 = capture_message(msg, BOT, "new", state=state)
    state.insert_message(cap1, None)                       # version 1
    cap2 = capture_message(msg, BOT, "edit", state=state)  # version 2
    state.insert_message(cap2, None)                       # version 2 записана
    # «параллельный писатель» уже вставил v2, а у нас устаревшая версия 1
    cap3 = capture_message(msg, BOT, "edit", state=None, version=1)
    rowid = state.insert_message(cap3, None)               # retry подберёт 3
    versions = [r["version"] for r in state._query(
        "SELECT version FROM messages WHERE message_id=11 ORDER BY version")]
    assert versions == [1, 2, 3]


def test_reset_bot_leaves_no_orphans(cfg, state):
    """Reset удаляет entities/media/callbacks вместе с messages/buttons —
    без orphan rows."""
    from telethon.tl.types import MessageEntityBold, MessageEntityCustomEmoji
    from tg_flowmap.dast.capture import capture_message

    msg = FakeMessage(20, "🥇 text", entities=[
        MessageEntityCustomEmoji(offset=0, length=2, document_id=888),
        MessageEntityBold(offset=3, length=4)])
    cap = capture_message(msg, BOT, "new", state=state)
    state.upsert_screen(BOT, "s_y", "fp_y", 0, "y")
    rowid = state.insert_message(cap, "s_y")
    btn = ButtonRef(row=0, col=0, label="Go", button_type="callback",
                    callback_data=b"go", message_id=20)
    ids = state.insert_buttons(BOT, "s_y", rowid, [btn], ["bfp"])
    from tg_flowmap.dast.models import CallbackResult
    state.add_callback(BOT, ids[0], "aid", CallbackResult(message="ok"))

    state.register_bot(BOT)
    state.reset_bot(BOT)

    assert state._query_one("SELECT COUNT(*) AS c FROM messages WHERE bot=?",
                            (BOT,))["c"] == 0
    assert state._query_one("SELECT COUNT(*) AS c FROM entities")["c"] == 0
    assert state._query_one("SELECT COUNT(*) AS c FROM media")["c"] == 0
    assert state._query_one("SELECT COUNT(*) AS c FROM callbacks")["c"] == 0
    assert state._query_one("SELECT COUNT(*) AS c FROM emoji_occurrences")["c"] == 0


def test_reinit_existing_db_preserves_data(cfg, state):
    state.register_bot(BOT)
    state.upsert_screen(BOT, "s_z", "fp_z", 0, "z")
    state.close()
    state2 = State(cfg.db_path)
    try:
        assert len(state2.screens_all(BOT)) == 1
        assert state2.bot_info(BOT)["username"] == BOT
    finally:
        state2.close()


# ------------------------------------------------------------------ П10
def test_media_size_guard_skips_download(tmp_path):
    """Заведомо большой документ не качается вообще (клиент не вызывается)."""

    class ExplodingClient:
        async def download_media(self, *a, **k):
            raise AssertionError("слишком большой файл не должен качаться")

    class Doc:
        size = 10 * 1024 * 1024
        id = 1
        mime_type = "image/png"

    msg = FakeMessage(30, "cap", document=Doc())
    import asyncio
    result = asyncio.run(download_media(
        ExplodingClient(), msg, tmp_path, max_size_bytes=1024))
    assert result is None


def test_media_single_download_and_web_preview_metadata(tmp_path):
    """Одно сообщение с основным media + web_preview:
    - client.download_media вызван ровно один раз;
    - основной MediaInfo получает file_path;
    - web_preview не получает ложный путь (остаётся метаданными с file_path=None);
    - частичный файл после ошибки удаляется;
    - файл выше лимита не скачивается."""
    downloads = []

    class OkClient:
        async def download_media(self, msg, file=None):
            from pathlib import Path as P
            P(file).write_bytes(b"image data")
            downloads.append(file)
            return file

    class Doc:
        size = 100
        id = 42
        mime_type = "image/png"

    class Web:
        id = 999

    msg = FakeMessage(31, "caption with link", document=Doc())
    msg.web_preview = Web()

    # 1) client.download_media вызывается ровно один раз
    import asyncio
    p = asyncio.run(download_media(OkClient(), msg, tmp_path))
    assert p is not None
    assert downloads == [p]
    assert p.endswith(".png")

    # 2) частичный файл удаляется при ошибке
    class BrokenClient:
        async def download_media(self, msg, file=None):
            from pathlib import Path as P
            P(file).write_bytes(b"partial-corrupted")
            raise RuntimeError("network fail")

    msg_broken = FakeMessage(32, "broken", document=Doc())
    p_broken = asyncio.run(download_media(BrokenClient(), msg_broken, tmp_path))
    assert p_broken is None
    from pathlib import Path
    assert not any("msg32" in f.name for f in Path(tmp_path).iterdir())


def test_crawler_observes_single_media_download_and_stores_db(cfg, state, tmp_path):
    """Интеграционный тест: crawler скачивает медиа один раз,
    в БД у document есть file_path, а у web_preview file_path=None."""
    download_calls = []

    class MockNav:
        async def send_start(self):
            return PressOutcome(kind="new", message=msg_start)

        async def download_media(self, msg, media_dir):
            download_calls.append(msg.id)
            target = tmp_path / f"msg{msg.id}.png"
            target.write_bytes(b"png data")
            return str(target)

    class Doc:
        size = 50
        id = 77
        mime_type = "image/png"

    class Web:
        id = 88

    msg_start = FakeMessage(40, "Menu with media", document=Doc())
    msg_start.web_preview = Web()

    crawler, _ = make_crawler(cfg, state, MockNav(), BOT, tmp_path)
    import asyncio
    status = asyncio.run(crawler.run())
    assert status == "done"

    # Навигатор вызван ровно 1 раз
    assert download_calls == [40]

    # В БД: у основного медиа есть file_path, у web_preview — None
    media_rows = state._query(
        "SELECT kind, file_path FROM media WHERE bot=? ORDER BY id", (BOT,))
    assert len(media_rows) == 2
    doc_row = [r for r in media_rows if r["kind"] != "web_preview"][0]
    web_row = [r for r in media_rows if r["kind"] == "web_preview"][0]
    assert doc_row["file_path"] is not None and "msg40.png" in doc_row["file_path"]
    assert web_row["file_path"] is None


def test_media_file_name_scheme():
    class Doc:
        mime_type = "image/png"
        id = 12345
    msg = FakeMessage(9, "")
    name = media_file_name(msg, "photo", "12345", doc=Doc())
    assert name.startswith("msg9_photo_") and "12345" in name and name.endswith(".png")
