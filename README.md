# 🧭 tg-flowmap

> **Zero-runtime static AST analyzer, linter, and interactive flow-map visualizer for Telegram Bots.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-brightgreen.svg)]()
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)]()

`tg-flowmap` analyzes your Telegram bot's source code **without running it**, without installing heavy dependencies, and without requiring database connections or bot tokens. It parses Python AST to construct an interactive, node-graph visualization of all screens, inline keyboards, callbacks, and state transitions, while automatically linting for common Telegram Bot API defects and dead-ends.

---

## ✨ Features

- 🗺️ **Interactive Canvas (n8n/Miro style)**: Pan, zoom, drag nodes, and explore every message screen, keyboard layout, and button route.
- 🔍 **Dead-End Detection**: Automatically catches buttons whose `callback_data` has no corresponding handler in the code.
- ⚡ **Zero-Execution Static AST**: Safely analyze bots without executing untrusted code, importing libraries, or connecting to Telegram servers.
- 🚨 **Telegram API Validation**:
  - Catches invalid/null `icon_custom_emoji_id` values before they trigger `400 Bad Request` in production.
  - Flags buttons with missing action (no `callback_data` and no `url`).
  - Warns about `callback_data` strings exceeding the Telegram 64-byte limit.
- ↩️ **UX Audit (Missing Back Buttons)**: Identifies dead-end screens where users have no option to return to previous or main menus.
- 📦 **Framework Agnostic**: Works seamlessly with raw Telegram Bot API dicts, `aiogram` (v2 & v3), `telebot` (pyTelegramBotAPI), and custom bot frameworks.
- 📑 **Export Options**: Generates standalone single-file HTML reports (with Vis.js) and structured JSON for CI/CD pipelines.

---

## 🚀 Quick Start

### 1. Installation

Clone and install in virtual environment:

```bash
git clone https://github.com/w1bbex/tg-flowmap.git
cd tg-flowmap
python -m venv .venv
.\.venv\Scripts\activate  # On Linux/macOS: source .venv/bin/activate
pip install -e .
```

### 2. Run Analysis

Analyze a bot file or an entire project directory:

```bash
python -m tg_flowmap path/to/bot -o flowmap.html
```

Or run directly if installed as package:

```bash
tg-flowmap path/to/bot/bot.py -o flowmap.html --json report.json
```

### 3. CI/CD Strict Mode

Fail your build if dead-ends or broken emojis are detected:

```bash
tg-flowmap path/to/bot --strict
```

---

## 📊 Sample Output

```text
============================================================
  🧭 TG-FLOWMAP — Telegram Bot Visualizer & Linter
============================================================
Цель:            C:\Projects\pc-control\vds_bot
Всего экранов:   91
Всего связей:    302
Клавиатур найдено: 26
Тупиков (Dead-end): 0
Ошибок эмодзи:   0
Без кнопки Назад: 28
------------------------------------------------------------

🔍 НАЙДЕННЫЕ ДЕФЕКТЫ И ПРЕДУПРЕЖДЕНИЯ:
  1. ⚠️ [MISSING_BACK] В экране 'power_menu' нет кнопки возврата (« Назад / В меню »).
  2. ℹ️ [DANGLING_HANDLER] Обработчик 'console_close' определён в коде, но ни одна кнопка на него не ссылается.

📊 Интерактивная карта сохранена: output/pc_control_flowmap.html
📄 JSON-отчёт сохранён: output/pc_control_flowmap.json
```

---

## 🛠️ Architecture

- `tg_flowmap/models.py`: Data models (`Button`, `Keyboard`, `MessageNode`, `Edge`, `Issue`, `BotMap`).
- `tg_flowmap/parser.py`: Pure Python AST parser extracting inline keyboards, variable assignments, callback routes, startswith prefixes, match-case statements, and decorators.
- `tg_flowmap/analyzer.py`: Resolves edges, wildcard prefixes (`volume:*`, `player_*`), inspects button constraints, and detects dead-ends.
- `tg_flowmap/visualizer.py`: Generates standalone interactive HTML visualizer with ForceAtlas2 physics layout, search filter, and node detail side-panel.
- `tg_flowmap/cli.py`: Command-line interface and terminal reporter.

---

## 📄 License

MIT License. Built by w1bbex.
