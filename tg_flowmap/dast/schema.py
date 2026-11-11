"""SQLite-схема и миграции для DAST хранилища tg-flowmap."""

from __future__ import annotations

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
