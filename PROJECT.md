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
- [x] Full test suite (7 passing tests including performance & memory budgets) and dogfood verification on `pc-control/vds_bot`.
- [x] 4-type visual taxonomy (Commands, Screens, Callbacks, Popups) with live filter bar.
- [x] Multi-deck canvas layout (Commands, Popups, Secondary Handlers) and straight-vertical tree branches.
- [x] Dynamic GPU canvas acceleration, DirectWrite ClearType font sharpness, and zero deck collision cascading.

## 5. Known Traps & Rendering Gotchas (Не наступать на грабли!)
1. **Dynamic GPU Promotion (Устранение лагов без мыла шрифтов)**:
   - *Грабли 1 (Мыло)*: Постоянный `will-change: transform` на `#canvas-world` или `#viewport` превращает холст в фиксированную GPU-текстуру — при зуме шрифты мылятся, а ховер даёт резкость ровно на 1 кадр из-за инвалидации слоя.
   - *Грабли 2 (Лаги)*: Полное удаление GPU-слоя заставляет браузер программно перерисовывать все 70+ карточек с тенями и SVG на CPU при каждом `mousemove` (просадка до 10–15 FPS).
   - *Золотое правило*: Включать аппаратное ускорение `translate3d(rx, ry, 0) scale(scale)` и `willChange = "transform"` **строго во время движения** (`mousedown`, `wheel`, `smoothFlyTo`). В покое (`mouseup`, debounce `wheel` 100мс) сбрасывать `willChange = ""` и переходить на 2D `translate` с целыми пикселями `Math.round()` — шрифты рендерятся с кристальным субпиксельным DirectWrite ClearType.
2. **Селекторы драга O(1) вместо O(N)**:
   - Не использовать `#viewport.panning #canvas-world *` (перебивает дерево всех элементов DOM). Использовать `#viewport.panning #canvas-world` — отключает события у контейнера без пересчёта стилей сотен потомков.
3. **Шрифты на Windows**:
   - Запрещено вешать `-webkit-font-smoothing: antialiased`, `grayscale` и `text-rendering: geometricPrecision` — они отключают хинтинг и субпиксельный рендеринг DirectWrite на Windows.
4. **Каскадирование колод в DOM (`refineDeckWithDomHeights`)**:
   - Запрещено хардкодить `startY` для последующих колод (например, `remStartY = 620px` приводило к наезду `led` на `player`).
   - Всегда использовать двухпроходный каскад: замерять реальные DOM-высоты колоды в Pass 2 и сдвигать следующую колоду по фактическому максимуму: `realRemStartY = Math.max(realCmdMaxY, realUtilMaxY) + 100`.
