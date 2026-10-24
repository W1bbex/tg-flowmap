# tg-flowmap

## 1. Overview & Architecture
Unified Telegram Bot Analysis, Reverse-Engineering, and Benchmarking Suite.
Combines Zero-runtime AST Static Analysis (SAST), State-Aware Userbot Crawling (DAST via Telethon), and LLM-ready Product Benchmarking (Claude / ChatGPT) into a single cohesive toolkit.

## 2. Tech Stack
- SAST Engine: Python 3.10+ (Standard Library: `ast`, `re`, `json`, `pathlib`, `typing`) — 0 runtime dependencies.
- DAST Engine: Telethon, SQLite3 state persistence (15 tables), Dijkstra locality navigation, Safety Filter.
- Core / Benchmarker: Unified `BotMap` data models, `comparator.py`, `llm_exporter.py`.
- Visualization: Standalone HTML5 / SVG / Vis.js Canvas (ForceAtlas2 physics, DirectWrite ClearType, zero-deck collision).
- CLI: Zero-flag frictionless entrypoint (`tg-flowmap sast`, `tg-flowmap dast`, `tg-flowmap compare`).
- Tests: `pytest` with 182 passing regression and performance tests in `tests/sast` and `tests/dast`.

## 3. Key Design Rationale
- Pure AST analysis for local code (SAST): 0 dependencies, 50ms execution, safe for untrusted code and CI/CD.
- Graph-First Locality Navigation for external bots (DAST): Dijkstra shortest path over known transitions prevents spamming `/start` and protects against Telegram FloodWait bans.
- Zero-flag sensible defaults: running commands prints rich summaries and automatically saves structured Markdown and JSON into `output/` without requiring tedious `-o` flags.
- Prompt-ready LLM export: automatic generation of `llm_prompt.md` containing side-by-side metrics and structured screen maps for instant AI UX/CRO auditing.

## 4. Active Tasks & Gotchas
- [x] Initial repository setup and passport creation in `C:\Projects\.github\tg-flowmap`.
- [x] Core AST parser, keyboard extractor, and dead-end linter (SAST).
- [x] Standalone interactive HTML visualizer with GPU acceleration and ClearType font rendering.
- [x] Security & Parser audit fixes: Stored DOM XSS eliminated, /start hijacking prevented, ast.BoolOp & ast.Attribute support.
- [x] Multi-deck canvas layout and collision-free two-pass height refinement (`refineDeckWithDomHeights`).
- [x] Integration of DAST engine from `TgBotExplorer` into `tg_flowmap/dast/`.
- [x] Unified `core/` models, `BotComparator`, and `llm_exporter` for instant comparison of Bot A vs Bot B.
- [x] Frictionless zero-flag CLI supporting `sast`, `dast`, `compare` with automatic Markdown and LLM prompt exports.
- [x] 182 passing automated tests across SAST and DAST suites.
- [x] SAST v2: Wildcard-трансформация f-строк (`f"prefix:{var}"` ➔ `prefix:*`) для устранения ложных `[DANGLING_HANDLER]`.
- [x] SAST v2: Подавление `[MISSING_BACK]` при возврате в корневой хаб (`main_menu_markup`).
- [ ] SAST v2: Двухпроходный резолвинг параметризованных карточек (`card_markup(data)`) и вызовов из брокеров/диспетчеров.
- [ ] Детальный разбор ограничений: см. `LIMITATIONS_AND_ROADMAP.md`.

## 5. Known Traps & Rendering Gotchas (Не наступать на грабли!)
1. **Dynamic GPU Promotion (Устранение лагов без мыла шрифтов)**:
   - Включать аппаратное ускорение `translate3d(rx, ry, 0) scale(scale)` и `willChange = "transform"` строго во время движения (`mousedown`, `wheel`, `smoothFlyTo`). В покое сбрасывать `willChange = ""` и переходить на 2D `translate` с целыми пикселями `Math.round()` — шрифты рендерятся с кристальным субпиксельным DirectWrite ClearType.
2. **Селекторы драга O(1) вместо O(N)**:
   - Не использовать `#viewport.panning #canvas-world *`. Использовать `#viewport.panning #canvas-world` — отключает события у контейнера без пересчёта стилей сотен потомков.
3. **Шрифты на Windows**:
   - Запрещено вешать `-webkit-font-smoothing: antialiased`, `grayscale` и `text-rendering: geometricPrecision` — они отключают хинтинг и субпиксельный рендеринг DirectWrite на Windows.
4. **Каскадирование колод в DOM (`refineDeckWithDomHeights`)**:
   - Всегда использовать двухпроходный каскад: замерять реальные DOM-высоты колоды в Pass 2 и сдвигать следующую колоду по фактическому максимуму: `realRemStartY = Math.max(realCmdMaxY, realUtilMaxY) + 100`.
5. **Экранирование HTML в шаблонах карточек (XSS Guard)**:
   - В `viewer.js` запрещено делать `body.innerHTML = node.text_template` без санитизации: экранировать через `escapeHtml()` перед вставкой в DOM.
6. **DAST Safety & FloodGate**:
   - Краулер никогда не должен нажимать опасные кнопки ("Купить", "Оплатить", "Списать") — они отсекаются в `safety.py`. Рейт-лимитер должен строго уважать задержки Telegram и перехватывать `FloodWait`.
7. **SAST в асинхронных IoT-ботах (Слепые зоны парсера)**:
   - Статический AST не видит `send_message`, если отправка происходит асинхронно через брокер (`mqtt_dispatcher.py`). F-строки в `callback_data` без wildcard-нормализации порождают ложные `[DANGLING_HANDLER]`. Не считать такие предупреждения реальными багами в боте до ручной проверки.
