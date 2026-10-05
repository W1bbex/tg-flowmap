# tg-flowmap

## 1. Overview & Architecture
Zero-runtime AST static analyzer, linter, and interactive flow-map visualizer for Telegram Bots.
Extracts message templates, inline keyboards, callbacks, and state transitions without launching the bot, producing an n8n-style interactive canvas with dead-end and broken API audits.

## 2. Tech Stack
- Core Engine: Python 3.10+ (Standard Library: `ast`, `re`, `json`, `pathlib`, `typing`)
- Visualization: Standalone HTML5 / Vis.js Canvas (ForceAtlas2 physics, node inspector side panel)
- CLI: Lightweight entrypoint for analyzing project directories or files (`tg_flowmap.cli`)
- Tests: `pytest` with regression coverage in `tests/test_flowmap.py`

## 3. Key Design Rationale
- Pure AST analysis: No live execution, no database required, zero secret/token requirements.
- Standard Telegram Bot API schema as canonical source of truth for keyboards and callbacks.
- Resilient pattern recognition: handles custom dicts (`inline_keyboard`), standard aiogram/telebot button builders, match-case, and if-else / decorator router dispatching.
- Auto-resolution of module constants and `resources/icons.json` to prevent false positives while strictly flagging real broken/missing custom emojis.

## 4. Active Tasks & Gotchas
- [x] Initial repository setup and passport creation in `C:\Projects\.github\tg-flowmap`.
- [x] Core AST parser: keyboard extractor, callback router extractor, message caller extractor.
- [x] Graph builder and linter (detects dead ends, null emoji IDs, orphan buttons, callback length limits).
- [x] Standalone interactive HTML exporter with pan/zoom/search and node inspector.
- [x] Full test suite (6 passing tests) and dogfood verification on `pc-control/vds_bot`.
