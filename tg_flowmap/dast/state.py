"""SQLite-хранилище обхода: 15 таблиц, всё namespaced по боту.

Атомарность и целостность:
- каждое составное изменение (insert сообщения с entities/media/emoji,
  upsert экрана/маршрута, pop_frontier, progress_incr, reset_bot)
  выполняется в одной транзакции BEGIN IMMEDIATE;
- busy_timeout=5000 против SQLITE_BUSY;
- идемпотентные миграции (ALTER TABLE только для отсутствующих колонок,
  старые данные не трогаются);
- на свежих базах — настоящие FOREIGN KEY с каскадом; на старых базах
  каскад выполняется вручную в reset_bot (удаление детей до родителей).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import ButtonRef, CallbackResult, MessageCapture
from .tl_serial import clean

SCHEMA = """
CREATE TABLE IF NOT EXISTS bots(
  username TEXT PRIMARY KEY,
  chat_id INTEGER,
  status TEXT DEFAULT 'new',
  actions_count INTEGER DEFAULT 0,
  restarts INTEGER DEFAULT 0,
  started_at TEXT, finished_at TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS screens(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT NOT NULL,
  screen_id TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  depth_min INTEGER NOT NULL DEFAULT 0,
  text_norm TEXT NOT NULL DEFAULT '',
  requires_input INTEGER NOT NULL DEFAULT 0,
  created_at TEXT,
  UNIQUE(bot, fingerprint)
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT NOT NULL,
  chat_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  event_type TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  screen_id TEXT,
  raw_text TEXT, html TEXT,
  date TEXT, edit_date TEXT,
  reply_to_msg_id INTEGER,
  media_ref INTEGER,
  has_force_reply INTEGER DEFAULT 0,
  emojis_json TEXT,
  UNIQUE(bot, chat_id, message_id, version)
);
CREATE TABLE IF NOT EXISTS entities(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_rowid INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  type TEXT, offset INTEGER, length INTEGER,
  url TEXT, language TEXT,
  document_id TEXT, is_premium INTEGER DEFAULT 0,
  utf16_offset INTEGER, order_index INTEGER, symbol TEXT,
  collapsed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS media(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT, message_rowid INTEGER REFERENCES messages(id) ON DELETE CASCADE,
  kind TEXT, tg_id TEXT, size INTEGER, file_path TEXT,
  caption TEXT, has_caption_entities INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS buttons(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT, screen_id TEXT, message_rowid INTEGER, message_id INTEGER,
  row INTEGER, col INTEGER, label TEXT, button_type TEXT,
  callback_data BLOB, callback_b64 TEXT, callback_hex TEXT,
  url TEXT, custom_emoji_id TEXT,
  button_fp TEXT, blocked_reason TEXT,
  created_at TEXT,
  style_bg_primary INTEGER DEFAULT 0,
  style_bg_success INTEGER DEFAULT 0,
  style_bg_danger INTEGER DEFAULT 0,
  style_icon_id TEXT,
  style_requires_password INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS callbacks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT, button_rowid INTEGER REFERENCES buttons(id) ON DELETE CASCADE,
  action_id TEXT,
  answer_message TEXT, is_alert INTEGER, url TEXT, cache_time INTEGER,
  duration_ms INTEGER, exception TEXT, raw_json TEXT
);
CREATE TABLE IF NOT EXISTS transitions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT,
  from_screen TEXT, to_screen TEXT,
  action TEXT, action_type TEXT, result_type TEXT,
  button_rowid INTEGER, route_id TEXT,
  from_message_rowid INTEGER, to_message_rowid INTEGER,
  created_at TEXT,
  UNIQUE(bot, from_screen, button_rowid)
);
CREATE TABLE IF NOT EXISTS routes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT NOT NULL,
  route_id TEXT NOT NULL,
  route_fingerprint TEXT NOT NULL,
  parent_route TEXT,
  screen_id TEXT NOT NULL,
  path_json TEXT NOT NULL,
  depth INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT,
  UNIQUE(bot, route_fingerprint)
);
CREATE TABLE IF NOT EXISTS frontier(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT NOT NULL,
  route_id TEXT NOT NULL,
  screen_id TEXT NOT NULL,
  path_json TEXT NOT NULL,
  depth INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT, taken_at TEXT
);
CREATE TABLE IF NOT EXISTS scan_progress(
  bot TEXT NOT NULL, key TEXT NOT NULL, value TEXT,
  PRIMARY KEY(bot, key)
);
CREATE TABLE IF NOT EXISTS timeline(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action_id TEXT NOT NULL,
  bot TEXT NOT NULL,
  ts TEXT NOT NULL,
  action TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT,
  duration_ms INTEGER,
  error TEXT
);
CREATE TABLE IF NOT EXISTS errors(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT, ts TEXT, kind TEXT, message TEXT, context TEXT
);
CREATE TABLE IF NOT EXISTS emoji_documents(
  document_id TEXT PRIMARY KEY,
  first_seen_at TEXT, example_symbol TEXT, purpose TEXT
);
CREATE TABLE IF NOT EXISTS emoji_occurrences(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT, document_id TEXT, message_rowid INTEGER, message_id INTEGER,
  utf16_offset INTEGER, order_index INTEGER, symbol TEXT,
  context TEXT
);
CREATE TABLE IF NOT EXISTS stable_actions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT NOT NULL,
  action_id TEXT NOT NULL,
  source_screen_id TEXT NOT NULL,
  row INTEGER NOT NULL,
  col INTEGER NOT NULL,
  label TEXT NOT NULL,
  label_norm TEXT NOT NULL,
  button_type TEXT NOT NULL,
  style_bg_primary INTEGER DEFAULT 0,
  style_bg_success INTEGER DEFAULT 0,
  style_bg_danger INTEGER DEFAULT 0,
  style_icon_id TEXT,
  style_requires_password INTEGER DEFAULT 0,
  url TEXT,
  blocked_reason TEXT,
  explored INTEGER DEFAULT 0,
  created_at TEXT,
  UNIQUE(bot, source_screen_id, row, col, label_norm, button_type)
);
CREATE TABLE IF NOT EXISTS button_instances(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT NOT NULL,
  message_rowid INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  action_id TEXT NOT NULL,
  row INTEGER NOT NULL,
  col INTEGER NOT NULL,
  label TEXT NOT NULL,
  button_type TEXT NOT NULL,
  callback_data BLOB,
  callback_b64 TEXT,
  callback_hex TEXT,
  url TEXT,
  custom_emoji_id TEXT,
  blocked_reason TEXT,
  style_bg_primary INTEGER DEFAULT 0,
  style_bg_success INTEGER DEFAULT 0,
  style_bg_danger INTEGER DEFAULT 0,
  style_icon_id TEXT,
  style_requires_password INTEGER DEFAULT 0,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS graph_edges(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT NOT NULL,
  source_screen_id TEXT NOT NULL,
  action_id TEXT NOT NULL,
  destination_screen_id TEXT NOT NULL,
  result_type TEXT NOT NULL,
  observations_count INTEGER DEFAULT 1,
  success_count INTEGER DEFAULT 1,
  failure_count INTEGER DEFAULT 0,
  confidence REAL DEFAULT 1.0,
  is_stable INTEGER DEFAULT 1,
  first_observed_at TEXT,
  last_observed_at TEXT,
  last_success_at TEXT,
  UNIQUE(bot, source_screen_id, action_id, destination_screen_id)
);
CREATE TABLE IF NOT EXISTS navigation_plans(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT NOT NULL,
  target_screen_id TEXT NOT NULL,
  strategy TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  created_at TEXT,
  completed_at TEXT,
  error TEXT
);
CREATE TABLE IF NOT EXISTS metrics(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot TEXT NOT NULL,
  key TEXT NOT NULL,
  value INTEGER DEFAULT 0,
  updated_at TEXT,
  UNIQUE(bot, key)
);
CREATE INDEX IF NOT EXISTS idx_screens_bot ON screens(bot);
CREATE INDEX IF NOT EXISTS idx_buttons_screen ON buttons(bot, screen_id);
CREATE INDEX IF NOT EXISTS idx_trans_from ON transitions(bot, from_screen);
CREATE INDEX IF NOT EXISTS idx_frontier_status ON frontier(bot, status);
CREATE INDEX IF NOT EXISTS idx_timeline_bot ON timeline(bot, ts);
CREATE INDEX IF NOT EXISTS idx_entities_msg ON entities(message_rowid);
CREATE INDEX IF NOT EXISTS idx_media_msg ON media(message_rowid);
CREATE INDEX IF NOT EXISTS idx_routes_screen ON routes(bot, screen_id);
CREATE INDEX IF NOT EXISTS idx_actions_screen ON stable_actions(bot, source_screen_id);
CREATE INDEX IF NOT EXISTS idx_btn_instances_msg ON button_instances(message_rowid);
CREATE INDEX IF NOT EXISTS idx_graph_edges_src ON graph_edges(bot, source_screen_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_dst ON graph_edges(bot, destination_screen_id);
CREATE INDEX IF NOT EXISTS idx_metrics_bot ON metrics(bot);
"""

# Идемпотентные миграции: колонка -> DDL (добавляется только если отсутствует)
_MIGRATION_COLUMNS: dict[str, dict[str, str]] = {
    "buttons": {
        "style_bg_primary": "INTEGER DEFAULT 0",
        "style_bg_success": "INTEGER DEFAULT 0",
        "style_bg_danger": "INTEGER DEFAULT 0",
        "style_icon_id": "TEXT",
        "style_requires_password": "INTEGER DEFAULT 0",
    },
    "entities": {
        "collapsed": "INTEGER DEFAULT 0",
    },
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class State:
    """Обёртка над sqlite3: короткие транзакции под threading.RLock,
    вызовы из async-кода безопасны (GIL + WAL + busy_timeout)."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False,
                                     timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    # ------------------------------------------------------------- миграции
    def _migrate(self) -> None:
        """Идемпотентно: только добавляет отсутствующие колонки.
        Существующие данные никогда не удаляются и не перезаписываются."""
        for table, cols in _MIGRATION_COLUMNS.items():
            existing = {r["name"] for r in
                        self._conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols.items():
                if name not in existing:
                    self._conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------ примитивы
    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            try:
                cur = self._conn.execute(sql, params)
                self._conn.commit()
                return cur
            except BaseException:
                self._conn.rollback()
                raise

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    @contextmanager
    def transaction(self):
        """BEGIN IMMEDIATE … COMMIT / ROLLBACK. Внутри использовать
        conn.execute напрямую (без _exec, чтобы не коммитить середину)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    # ------------------------------------------------------------------ боты
    def register_bot(self, username: str, chat_id: int | None = None) -> None:
        self._exec(
            "INSERT INTO bots(username, chat_id) VALUES(?,?) "
            "ON CONFLICT(username) DO UPDATE SET chat_id=COALESCE(excluded.chat_id, chat_id)",
            (username, chat_id),
        )

    def set_bot_status(self, username: str, status: str, error: str | None = None) -> None:
        ts = utcnow()
        started = ts if status == "running" else None
        finished = ts if status in ("done", "error", "paused", "limit_reached") else None
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO bots(username, status, started_at, finished_at, error) "
                "VALUES(?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET "
                "status=excluded.status, error=excluded.error, "
                "started_at=COALESCE(excluded.started_at, bots.started_at), "
                "finished_at=COALESCE(excluded.finished_at, bots.finished_at)",
                (username, status, started, finished, error),
            )

    def bot_info(self, username: str) -> dict | None:
        row = self._query_one("SELECT * FROM bots WHERE username=?", (username,))
        return dict(row) if row else None

    def list_bots(self) -> list[dict]:
        return [dict(r) for r in self._query("SELECT * FROM bots ORDER BY username")]

    def reset_bot(self, username: str) -> None:
        """Полный сброс обхода бота: ОДНА транзакция; дочерние строки
        (entities/media/callbacks) удаляются ДО родителей — не остаётся
        сирот ни на старой базе (без FK), ни на новой (с FK+каскадом)."""
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM entities WHERE message_rowid IN "
                "(SELECT id FROM messages WHERE bot=?)", (username,))
            conn.execute(
                "DELETE FROM media WHERE message_rowid IN "
                "(SELECT id FROM messages WHERE bot=?)", (username,))
            conn.execute(
                "DELETE FROM callbacks WHERE button_rowid IN "
                "(SELECT id FROM buttons WHERE bot=?)", (username,))
            for table in ("emoji_occurrences", "transitions", "buttons", "routes",
                          "frontier", "scan_progress", "timeline", "errors",
                          "messages", "screens", "stable_actions", "button_instances",
                          "graph_edges", "navigation_plans", "metrics"):
                conn.execute(f"DELETE FROM {table} WHERE bot=?", (username,))
            conn.execute(
                "UPDATE bots SET status='new', actions_count=0, restarts=0, "
                "started_at=NULL, finished_at=NULL, error=NULL WHERE username=?",
                (username,))

    # --------------------------------------------------------------- экраны
    def upsert_screen(
        self, bot: str, screen_id: str, fingerprint: str,
        depth: int, text_norm: str, requires_input: bool = False,
    ) -> tuple[int, bool]:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM screens WHERE bot=? AND fingerprint=?",
                (bot, fingerprint)).fetchone()
            if row:
                return row["id"], False
            cur = conn.execute(
                "INSERT INTO screens(bot, screen_id, fingerprint, depth_min, "
                "text_norm, requires_input, created_at) VALUES(?,?,?,?,?,?,?)",
                (bot, screen_id, fingerprint, depth, text_norm,
                 int(requires_input), utcnow()))
            return cur.lastrowid, True

    def get_screen_by_fp(self, bot: str, fingerprint: str) -> sqlite3.Row | None:
        return self._query_one(
            "SELECT * FROM screens WHERE bot=? AND fingerprint=?", (bot, fingerprint))

    def get_screen(self, bot: str, screen_id: str) -> sqlite3.Row | None:
        return self._query_one(
            "SELECT * FROM screens WHERE bot=? AND screen_id=?", (bot, screen_id))

    def set_screen_requires_input(self, bot: str, screen_id: str,
                                  value: bool = True) -> None:
        self._exec("UPDATE screens SET requires_input=? WHERE bot=? AND screen_id=?",
                   (int(value), bot, screen_id))

    def screens_all(self, bot: str) -> list[dict]:
        return [dict(r) for r in self._query(
            "SELECT * FROM screens WHERE bot=? ORDER BY depth_min, id", (bot,))]

    # ------------------------------------------------------------- сообщения
    def next_message_version(self, bot: str, chat_id: int, message_id: int) -> int:
        row = self._query_one(
            "SELECT MAX(version) AS v FROM messages WHERE bot=? AND chat_id=? AND message_id=?",
            (bot, chat_id, message_id),
        )
        return (row["v"] or 0) + 1

    def insert_message(self, cap: MessageCapture, screen_id: str | None) -> int:
        """Вставляет НОВУЮ версию сообщения + entities + media + premium emoji
        ОДНОЙ транзакцией. Версия вычисляется внутри транзакции, если не задана;
        при UNIQUE-конфликте (гонка) безопасно повторяется со свежей версией."""
        for attempt in (1, 2):
            try:
                with self.transaction() as conn:
                    if cap.version is None or attempt == 2:
                        row = conn.execute(
                            "SELECT COALESCE(MAX(version),0)+1 AS v FROM messages "
                            "WHERE bot=? AND chat_id=? AND message_id=?",
                            (cap.bot, cap.chat_id, cap.message_id)).fetchone()
                        cap.version = row["v"]
                    cur = conn.execute(
                        "INSERT INTO messages(bot, chat_id, message_id, version, "
                        "event_type, captured_at, screen_id, raw_text, html, date, "
                        "edit_date, reply_to_msg_id, has_force_reply, emojis_json) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (cap.bot, cap.chat_id, cap.message_id, cap.version,
                         cap.event_type, cap.captured_at, screen_id, cap.raw_text,
                         cap.html, cap.date, cap.edit_date, cap.reply_to_msg_id,
                         int(cap.has_force_reply),
                         json.dumps(cap.emojis, ensure_ascii=False)))
                    rowid = cur.lastrowid
                    for e in cap.entities:
                        conn.execute(
                            "INSERT INTO entities(message_rowid, type, offset, length, "
                            "url, language, document_id, is_premium, utf16_offset, "
                            "order_index, symbol, collapsed) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (rowid, e.type, e.offset, e.length, e.url, e.language,
                             str(e.document_id) if e.document_id is not None else None,
                             int(e.is_premium), e.offset, e.order_index, e.symbol,
                             int(getattr(e, "collapsed", False))))
                    media_ref = None
                    for m in cap.media:
                        mcur = conn.execute(
                            "INSERT INTO media(bot, message_rowid, kind, tg_id, size, "
                            "file_path, caption, has_caption_entities) "
                            "VALUES(?,?,?,?,?,?,?,?)",
                            (cap.bot, rowid, m.kind, m.tg_id, m.size, m.file_path,
                             m.caption, int(m.has_caption_entities)))
                        media_ref = media_ref or mcur.lastrowid
                    if media_ref is not None:
                        conn.execute("UPDATE messages SET media_ref=? WHERE id=?",
                                     (media_ref, rowid))
                    emoji_context = "caption" if cap.media else "text"
                    for e in cap.entities:
                        if not e.is_premium or e.document_id is None:
                            continue
                        conn.execute(
                            "INSERT INTO emoji_documents(document_id, first_seen_at, "
                            "example_symbol) VALUES(?,?,?) "
                            "ON CONFLICT(document_id) DO NOTHING",
                            (str(e.document_id), utcnow(), e.symbol))
                        conn.execute(
                            "INSERT INTO emoji_occurrences(bot, document_id, "
                            "message_rowid, message_id, utf16_offset, order_index, "
                            "symbol, context) VALUES(?,?,?,?,?,?,?,?)",
                            (cap.bot, str(e.document_id), rowid, cap.message_id,
                             e.offset, e.order_index, e.symbol, emoji_context))
                return rowid
            except sqlite3.IntegrityError:
                if attempt == 2:
                    raise
                continue  # UNIQUE-гонка по версии: пересчитаем и повторим
        raise RuntimeError("unreachable")

    def upsert_emoji_document(self, document_id: str, symbol: str | None) -> None:
        self._exec(
            "INSERT INTO emoji_documents(document_id, first_seen_at, example_symbol) "
            "VALUES(?,?,?) ON CONFLICT(document_id) DO NOTHING",
            (document_id, utcnow(), symbol),
        )

    def add_emoji_occurrence_button(
        self, bot: str, document_id: str, message_id: int | None, symbol: str | None,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO emoji_documents(document_id, first_seen_at, example_symbol) "
                "VALUES(?,?,?) ON CONFLICT(document_id) DO NOTHING",
                (document_id, utcnow(), symbol))
            conn.execute(
                "INSERT INTO emoji_occurrences(bot, document_id, message_rowid, "
                "message_id, utf16_offset, order_index, symbol, context) "
                "VALUES(?,?,NULL,?,NULL,NULL,?,'button')",
                (bot, document_id, message_id, symbol))

    def messages_all(self, bot: str) -> list[dict]:
        rows = [dict(r) for r in self._query(
            "SELECT * FROM messages WHERE bot=? ORDER BY chat_id, message_id, version",
            (bot,))]
        for r in rows:
            r["entities"] = [dict(e) for e in self._query(
                "SELECT * FROM entities WHERE message_rowid=?", (r["id"],))]
            r["media"] = [dict(m) for m in self._query(
                "SELECT * FROM media WHERE message_rowid=?", (r["id"],))]
        return rows

    # ---------------------------------------------------------------- кнопки
    def insert_buttons(
        self, bot: str, screen_id: str, message_rowid: int,
        buttons: list[ButtonRef], button_fps: list[str],
    ) -> list[int]:
        ids = []
        ts = utcnow()
        with self.transaction() as conn:
            for b, fp in zip(buttons, button_fps):
                cur = conn.execute(
                    "INSERT INTO buttons(bot, screen_id, message_rowid, message_id, row, "
                    "col, label, button_type, callback_data, callback_b64, callback_hex, "
                    "url, custom_emoji_id, button_fp, blocked_reason, created_at, "
                    "style_bg_primary, style_bg_success, style_bg_danger, style_icon_id, "
                    "style_requires_password) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (bot, screen_id, message_rowid, b.message_id, b.row, b.col,
                     b.label, b.button_type, b.callback_data, b.callback_b64,
                     b.callback_hex, b.url, b.custom_emoji_id, fp, b.blocked_reason,
                     ts, int(b.style_bg_primary), int(b.style_bg_success),
                     int(b.style_bg_danger), b.style_icon_id,
                     int(b.requires_password)))
                b.db_id = cur.lastrowid
                ids.append(b.db_id)
                if b.custom_emoji_id:
                    self._add_button_emoji_in_tx(
                        conn, bot, b.custom_emoji_id, b.message_id, b.label)
        return ids

    @staticmethod
    def _add_button_emoji_in_tx(conn, bot, document_id, message_id, symbol) -> None:
        conn.execute(
            "INSERT INTO emoji_documents(document_id, first_seen_at, example_symbol) "
            "VALUES(?,?,?) ON CONFLICT(document_id) DO NOTHING",
            (document_id, utcnow(), symbol))
        conn.execute(
            "INSERT INTO emoji_occurrences(bot, document_id, message_rowid, "
            "message_id, utf16_offset, order_index, symbol, context) "
            "VALUES(?,?,NULL,?,NULL,NULL,?,'button')",
            (bot, document_id, message_id, symbol))

    def buttons_for_screen(self, bot: str, screen_id: str) -> list[ButtonRef]:
        rows = self._query(
            "SELECT * FROM buttons WHERE bot=? AND screen_id=? ORDER BY row, col",
            (bot, screen_id))
        out = []
        for r in rows:
            out.append(ButtonRef(
                row=r["row"], col=r["col"], label=r["label"] or "",
                button_type=r["button_type"] or "other",
                callback_data=bytes(r["callback_data"]) if r["callback_data"] else None,
                url=r["url"], custom_emoji_id=r["custom_emoji_id"],
                message_id=r["message_id"], blocked_reason=r["blocked_reason"],
                db_id=r["id"], button_fp=r["button_fp"],
                style_bg_primary=bool(r["style_bg_primary"]),
                style_bg_success=bool(r["style_bg_success"]),
                style_bg_danger=bool(r["style_bg_danger"]),
                style_icon_id=r["style_icon_id"],
                requires_password=bool(r["style_requires_password"]),
            ))
        return out

    def buttons_all(self, bot: str) -> list[dict]:
        return [dict(r) for r in self._query(
            "SELECT * FROM buttons WHERE bot=? ORDER BY screen_id, row, col", (bot,))]

    def insert_button_instances(
        self, bot: str, screen_id: str, message_rowid: int, buttons: list[ButtonRef],
    ) -> list[int]:
        """Сохраняет актуальные button instances конкретной версии сообщения
        и синхронизирует стабильные действия (stable_actions)."""
        from .screen_identity import normalize_text, stable_action_id

        ids = []
        ts = utcnow()
        with self.transaction() as conn:
            for b in buttons:
                act_id = stable_action_id(
                    source_screen_id=screen_id,
                    row=b.row,
                    col=b.col,
                    label=b.label,
                    button_type=b.button_type,
                    style_icon_id=b.style_icon_id,
                    requires_password=b.requires_password,
                    url=b.url,
                )
                b.button_fp = act_id

                # 1. Upsert в stable_actions
                conn.execute(
                    """
                    INSERT INTO stable_actions(
                        bot, action_id, source_screen_id, row, col, label, label_norm,
                        button_type, style_bg_primary, style_bg_success, style_bg_danger,
                        style_icon_id, style_requires_password, url, blocked_reason,
                        explored, created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)
                    ON CONFLICT(bot, source_screen_id, row, col, label_norm, button_type)
                    DO UPDATE SET
                        blocked_reason=excluded.blocked_reason,
                        style_icon_id=excluded.style_icon_id,
                        style_bg_primary=excluded.style_bg_primary,
                        style_bg_success=excluded.style_bg_success,
                        style_bg_danger=excluded.style_bg_danger,
                        style_requires_password=excluded.style_requires_password
                    """,
                    (
                        bot, act_id, screen_id, b.row, b.col, b.label,
                        normalize_text(b.label), b.button_type,
                        int(b.style_bg_primary), int(b.style_bg_success),
                        int(b.style_bg_danger), b.style_icon_id,
                        int(b.requires_password), b.url, b.blocked_reason, ts,
                    ),
                )

                # 2. Insert в button_instances
                cur = conn.execute(
                    """
                    INSERT INTO button_instances(
                        bot, message_rowid, action_id, row, col, label, button_type,
                        callback_data, callback_b64, callback_hex, url, custom_emoji_id,
                        blocked_reason, style_bg_primary, style_bg_success, style_bg_danger,
                        style_icon_id, style_requires_password, created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        bot, message_rowid, act_id, b.row, b.col, b.label, b.button_type,
                        b.callback_data, b.callback_b64, b.callback_hex, b.url,
                        b.custom_emoji_id, b.blocked_reason, int(b.style_bg_primary),
                        int(b.style_bg_success), int(b.style_bg_danger), b.style_icon_id,
                        int(b.requires_password), ts,
                    ),
                )
                b.db_id = cur.lastrowid
                ids.append(b.db_id)

                if b.custom_emoji_id:
                    self._add_button_emoji_in_tx(conn, bot, b.custom_emoji_id, b.message_id, b.label)
        return ids

    def button_instances_for_message(self, message_rowid: int) -> list[dict]:
        return [dict(r) for r in self._query(
            "SELECT * FROM button_instances WHERE message_rowid=? ORDER BY row, col",
            (message_rowid,),
        )]

    def button_instances_for_screen(self, bot: str, screen_id: str) -> list[dict]:
        """Возвращает актуальные button instances из последней версии сообщения экрана."""
        msg_row = self._query_one(
            "SELECT id FROM messages WHERE bot=? AND screen_id=? ORDER BY id DESC LIMIT 1",
            (bot, screen_id),
        )
        if not msg_row:
            return []
        return self.button_instances_for_message(msg_row["id"])

    def actions_for_screen(self, bot: str, source_screen_id: str) -> list[dict]:
        return [dict(r) for r in self._query(
            "SELECT * FROM stable_actions WHERE bot=? AND source_screen_id=? ORDER BY row, col",
            (bot, source_screen_id),
        )]

    def unexplored_actions_all(self, bot: str) -> dict[str, list[dict]]:
        """Возвращает неисследованные безопасные действия, сгруппированные по screen_id.
        Исключает экраны, маршруты к которым помечены как stale."""
        rows = self._query(
            """
            SELECT * FROM stable_actions
            WHERE bot=? AND explored=0 AND (blocked_reason IS NULL OR blocked_reason='')
              AND button_type IN ('callback', 'reply')
              AND source_screen_id NOT IN (
                  SELECT screen_id FROM routes WHERE bot=? AND status='stale'
              )
            ORDER BY source_screen_id, row, col
            """,
            (bot, bot),
        )
        out: dict[str, list[dict]] = {}
        for r in rows:
            d = dict(r)
            out.setdefault(d["source_screen_id"], []).append(d)
        return out

    def mark_action_explored(self, bot: str, action_id: str) -> None:
        self._exec(
            "UPDATE stable_actions SET explored=1 WHERE bot=? AND action_id=?",
            (bot, action_id),
        )

    def action_is_explored(self, bot: str, action_id: str) -> bool:
        row = self._query_one(
            "SELECT explored FROM stable_actions WHERE bot=? AND action_id=?",
            (bot, action_id),
        )
        return bool(row["explored"]) if row else False

    def upsert_graph_edge(self, bot: str, edge: dict) -> None:
        self._exec(
            """
            INSERT INTO graph_edges(
                bot, source_screen_id, action_id, destination_screen_id,
                result_type, observations_count, success_count, failure_count,
                confidence, is_stable, first_observed_at, last_observed_at, last_success_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(bot, source_screen_id, action_id, destination_screen_id)
            DO UPDATE SET
                result_type=excluded.result_type,
                observations_count=excluded.observations_count,
                success_count=excluded.success_count,
                failure_count=excluded.failure_count,
                confidence=excluded.confidence,
                is_stable=excluded.is_stable,
                last_observed_at=excluded.last_observed_at,
                last_success_at=excluded.last_success_at
            """,
            (
                bot,
                edge["source_screen_id"],
                edge["action_id"],
                edge["destination_screen_id"],
                edge.get("result_type", "edit"),
                int(edge.get("observations_count", 1)),
                int(edge.get("success_count", 1)),
                int(edge.get("failure_count", 0)),
                float(edge.get("confidence", 1.0)),
                int(edge.get("is_stable", 1)),
                edge.get("first_observed_at", utcnow()),
                edge.get("last_observed_at", utcnow()),
                edge.get("last_success_at"),
            ),
        )

    def graph_edges_all(self, bot: str) -> list[dict]:
        return [dict(r) for r in self._query(
            "SELECT * FROM graph_edges WHERE bot=? ORDER BY id", (bot,),
        )]

    def metric_incr(self, bot: str, key: str, delta: int = 1) -> int:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO metrics(bot, key, value, updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(bot, key) DO UPDATE SET
                    value = value + excluded.value,
                    updated_at = excluded.updated_at
                """,
                (bot, key, delta, utcnow()),
            )
            row = conn.execute(
                "SELECT value FROM metrics WHERE bot=? AND key=?",
                (bot, key),
            ).fetchone()
            return int(row["value"]) if row else delta

    def metric_set(self, bot: str, key: str, value: int) -> None:
        self._exec(
            """
            INSERT INTO metrics(bot, key, value, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(bot, key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (bot, key, value, utcnow()),
        )

    def metric_get(self, bot: str, key: str, default: int = 0) -> int:
        row = self._query_one(
            "SELECT value FROM metrics WHERE bot=? AND key=?",
            (bot, key),
        )
        return int(row["value"]) if row else default

    def metrics_all(self, bot: str) -> dict[str, int]:
        rows = self._query("SELECT key, value FROM metrics WHERE bot=?", (bot,))
        return {r["key"]: int(r["value"]) for r in rows}


    # ------------------------------------------------------------- callbacks
    def add_callback(
        self, bot: str, button_rowid: int, action_id: str, res: CallbackResult,
    ) -> int:
        cur = self._exec(
            "INSERT INTO callbacks(bot, button_rowid, action_id, answer_message, "
            "is_alert, url, cache_time, duration_ms, exception, raw_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (bot, button_rowid, action_id, res.message, int(res.alert), res.url,
             res.cache_time, res.duration_ms, res.exception,
             json.dumps(clean(res.raw), ensure_ascii=False) if res.raw is not None else None),
        )
        return cur.lastrowid

    def callbacks_all(self, bot: str) -> list[dict]:
        return [dict(r) for r in self._query(
            "SELECT c.*, b.label, b.screen_id AS from_screen_id, b.callback_hex, "
            "b.callback_b64 FROM callbacks c LEFT JOIN buttons b ON b.id=c.button_rowid "
            "WHERE c.bot=? ORDER BY c.id", (bot,))]

    # ----------------------------------------------------------- переходы
    def button_explored(self, bot: str, button_rowid: int) -> bool:
        row = self._query_one(
            "SELECT 1 FROM transitions WHERE bot=? AND button_rowid=?",
            (bot, button_rowid))
        return row is not None

    def add_transition(
        self, bot: str, from_screen: str, to_screen: str, action: str,
        action_type: str, result_type: str, button_rowid: int | None,
        route_id: str | None, from_message_rowid: int | None,
        to_message_rowid: int | None,
    ) -> int:
        cur = self._exec(
            "INSERT OR REPLACE INTO transitions(bot, from_screen, to_screen, action, "
            "action_type, result_type, button_rowid, route_id, from_message_rowid, "
            "to_message_rowid, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (bot, from_screen, to_screen, action, action_type, result_type,
             button_rowid, route_id, from_message_rowid, to_message_rowid, utcnow()),
        )
        return cur.lastrowid

    def transitions_all(self, bot: str) -> list[dict]:
        return [dict(r) for r in self._query(
            "SELECT * FROM transitions WHERE bot=? ORDER BY id", (bot,))]

    # ------------------------------------------------------------ маршруты
    def upsert_route(
        self, bot: str, route_id: str, route_fp: str, parent_route: str | None,
        screen_id: str, path: list[dict], depth: int,
    ) -> tuple[str, bool]:
        """Атомарно; один и тот же route (по route_fingerprint) не дублируется."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT route_id FROM routes WHERE bot=? AND route_fingerprint=?",
                (bot, route_fp)).fetchone()
            if row:
                return row["route_id"], False
            conn.execute(
                "INSERT INTO routes(bot, route_id, route_fingerprint, parent_route, "
                "screen_id, path_json, depth, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (bot, route_id, route_fp, parent_route, screen_id,
                 json.dumps(path, ensure_ascii=False), depth, utcnow()))
            return route_id, True

    def mark_route_stale(self, bot: str, route_id: str) -> None:
        self._exec("UPDATE routes SET status='stale' WHERE bot=? AND route_id=?",
                   (bot, route_id))

    def routes_all(self, bot: str) -> list[dict]:
        rows = [dict(r) for r in self._query(
            "SELECT * FROM routes WHERE bot=? ORDER BY depth, id", (bot,))]
        for r in rows:
            r["path"] = json.loads(r.pop("path_json") or "[]")
        return rows

    # ------------------------------------------------------------- frontier
    def push_frontier(self, bot: str, route_id: str, screen_id: str,
                      path: list[dict], depth: int) -> None:
        self._exec(
            "INSERT INTO frontier(bot, route_id, screen_id, path_json, depth, status, "
            "created_at) VALUES(?,?,?,?,?,'pending',?)",
            (bot, route_id, screen_id, json.dumps(path, ensure_ascii=False), depth,
             utcnow()),
        )

    def pop_frontier(self, bot: str) -> dict | None:
        """DFS: сначала самые глубокие. Атомарный SELECT+UPDATE."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM frontier WHERE bot=? AND status='pending' "
                "ORDER BY depth DESC, id ASC LIMIT 1", (bot,)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE frontier SET status='running', taken_at=? WHERE id=?",
                         (utcnow(), row["id"]))
        d = dict(row)
        d["path"] = json.loads(d.pop("path_json") or "[]")
        return d

    def requeue_frontier(self, frontier_id: int) -> None:
        self._exec("UPDATE frontier SET status='pending', taken_at=NULL WHERE id=?",
                   (frontier_id,))

    def finish_frontier(self, frontier_id: int, status: str = "done") -> None:
        self._exec("UPDATE frontier SET status=? WHERE id=?", (status, frontier_id))

    def frontier_pending_count(self, bot: str) -> int:
        row = self._query_one(
            "SELECT COUNT(*) AS c FROM frontier WHERE bot=? AND status='pending'", (bot,))
        return row["c"] if row else 0

    def frontier_active_count(self, bot: str) -> int:
        """pending + running: всё, что ещё не обработано."""
        row = self._query_one(
            "SELECT COUNT(*) AS c FROM frontier WHERE bot=? "
            "AND status IN ('pending','running')", (bot,))
        return row["c"] if row else 0

    def requeue_running_frontier(self, bot: str) -> int:
        """Resume после аварии: зависшие running → pending. Идемпотентно."""
        cur = self._exec(
            "UPDATE frontier SET status='pending', taken_at=NULL "
            "WHERE bot=? AND status='running'", (bot,))
        return cur.rowcount

    # ---------------------------------------------------------------- прогресс
    def progress_get(self, bot: str, key: str, default: str = "0") -> str:
        row = self._query_one(
            "SELECT value FROM scan_progress WHERE bot=? AND key=?", (bot, key))
        return row["value"] if row else default

    def progress_set(self, bot: str, key: str, value: str) -> None:
        self._exec(
            "INSERT INTO scan_progress(bot, key, value) VALUES(?,?,?) "
            "ON CONFLICT(bot, key) DO UPDATE SET value=excluded.value",
            (bot, key, value))

    def progress_incr(self, bot: str, key: str, by: int = 1) -> int:
        """Атомарный инкремент (read+write в одной транзакции)."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT value FROM scan_progress WHERE bot=? AND key=?",
                (bot, key)).fetchone()
            new = (int(row["value"]) if row else 0) + by
            conn.execute(
                "INSERT INTO scan_progress(bot, key, value) VALUES(?,?,?) "
                "ON CONFLICT(bot, key) DO UPDATE SET value=excluded.value",
                (bot, key, str(new)))
        return new

    # --------------------------------------------------------------- timeline
    def timeline_create(self, action_id: str, bot: str, action: str, payload: dict) -> None:
        self._exec(
            "INSERT INTO timeline(action_id, bot, ts, action, status, payload_json) "
            "VALUES(?,?,?,?, 'pending', ?)",
            (action_id, bot, utcnow(), action, json.dumps(clean(payload), ensure_ascii=False)))

    def timeline_update(self, action_id: str, status: str,
                        duration_ms: int | None = None, error: str | None = None) -> None:
        self._exec(
            "UPDATE timeline SET status=?, duration_ms=COALESCE(?, duration_ms), "
            "error=COALESCE(?, error) WHERE id=(SELECT id FROM timeline "
            "WHERE action_id=? ORDER BY id DESC LIMIT 1)",
            (status, duration_ms, error, action_id))

    def mark_stale_pending(self, bot: str) -> int:
        """На resume: зависшие pending → interrupted (обрыв после аварии)."""
        cur = self._exec(
            "UPDATE timeline SET status='interrupted', error='interrupted by restart' "
            "WHERE bot=? AND status='pending'", (bot,))
        return cur.rowcount

    def timeline_all(self, bot: str) -> list[dict]:
        return [dict(r) for r in self._query(
            "SELECT * FROM timeline WHERE bot=? ORDER BY id", (bot,))]

    # ----------------------------------------------------------------- ошибки
    def errors_add(self, bot: str, kind: str, message: str, context: str = "") -> None:
        self._exec("INSERT INTO errors(bot, ts, kind, message, context) VALUES(?,?,?,?,?)",
                   (bot, utcnow(), kind, message, context))

    def errors_list(self, bot: str, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self._query(
            "SELECT * FROM errors WHERE bot=? ORDER BY id DESC LIMIT ?", (bot, limit))]

    # ----------------------------------------------------------- emoji export
    def emoji_documents_all(self) -> list[dict]:
        return [dict(r) for r in self._query("SELECT * FROM emoji_documents ORDER BY document_id")]

    def emoji_occurrences_all(self, bot: str | None = None) -> list[dict]:
        if bot:
            return [dict(r) for r in self._query(
                "SELECT * FROM emoji_occurrences WHERE bot=? ORDER BY id", (bot,))]
        return [dict(r) for r in self._query(
            "SELECT * FROM emoji_occurrences ORDER BY id")]
