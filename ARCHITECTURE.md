# Архитектурная карта проекта tg-flowmap

> Сгенерировано скиллом `/study` | Дата: 2026-10-07 | Статус: Актуально

## 1. 🧭 Обзор и стек
- **Тип системы:** Zero-runtime статический AST-анализатор, линтер и интерактивный визуализатор графов Telegram-ботов.
- **Стек:** Python 3.10+ (Standard Library: `ast`, `re`, `json`, `pathlib`, `urllib`), Standalone HTML5 / SVG / CSS3 Canvas (без внешних CDN-зависимостей, нативный субпиксельный рендеринг DirectWrite, GPU-композитинг).
- **Архитектурный паттерн:** Двухпроходный компиляторный конвейер (Two-Pass AST Extraction ➔ Graph Synthesis & Linting ➔ Self-Contained Artifact Bundling ➔ Vector/DOM Canvas Engine).

---

## 2. 🗺 Карта модулей и компонентов

### Зона 1: Оркестрация, CLI и модели данных
- [`run.py`](file:///C:/Projects/.github/tg-flowmap/run.py) — интерактивный лаунчер и Drag-and-Drop точка входа для Windows. Сканирует родительские каталоги, эвристически обнаруживает проекты Telegram-ботов по сигнатурам кода, управляет `.env` токенами и открывает браузер.
- [`tg_flowmap/__main__.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/__main__.py) — пакетный шим для запуска через `python -m tg_flowmap`.
- [`tg_flowmap/cli.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/cli.py) — CLI-интерфейс командной строки (`argparse`). Координирует сквозной пайплайн: парсинг, линтинг, загрузку кастомных эмодзи, вывод терминальных отчетов и экспорт в HTML/JSON. Поддерживает `--strict` для CI/CD.
- [`tg_flowmap/models.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/models.py) — предметная модель данных графа: `Button`, `Keyboard`, `MessageNode`, `Edge`, `Issue`, `BotMap`. Предоставляет единую схему сериализации `.to_dict()`.
- [`tg_flowmap/visualizer.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/visualizer.py) — компилятор единого автономного HTML-артефакта. Встраивает CSS, JS и экранированный JSON графа (`__DATA_JSON__`) в шаблон `viewer.html` с защитой от разрыва `<script>` тегов (`replace("</", "<\\/")`).

### Зона 2: Движок AST-анализа, линтинга и эмодзи
- [`tg_flowmap/parser.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/parser.py) — ядро статического извлечения без исполнения кода (`AstParser`).
  - Выполняет двухпроходный обход дерева каталогов с пропуском виртуальных окружений и тестов.
  - Извлекает клавиатуры из функций, фабрик билдеров (`InlineKeyboardBuilder`), списковых включений и inline-словарей.
  - Распознает маршрутизаторы: декораторы aiogram 3 (`F.data == ...`), Telebot (`@bot.callback_query_handler`), цепочки `if/elif/else`, а также конструкции `match/case` (Python 3.10+).
  - Распознает вызовы отправки сообщений (`send_message`, `edit_text` и др.) и объединяет дублирующиеся экраны (`_consolidate_duplicate_screens`).
- [`tg_flowmap/ast_evaluator.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/ast_evaluator.py) — песочница статического вычисления AST-выражений без вызова `eval()`. Безопасно разворачивает литералы, конкатенации строк, f-строки, списки, словари, константы модулей и PEP 526 аннотации в константные значения.
- [`tg_flowmap/analyzer.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/analyzer.py) — топологический анализатор и линтер (`GraphAnalyzer`).
  - Разрешает целевые переходы `callback_data` по цепочке: точное совпадение ➔ алиасы экранов ➔ алиасы нод ➔ wildcard (`cb:*`) ➔ префиксные разделители (`:`, `_`) ➔ возврат в хаб меню ➔ dead_end.
  - Линтует ограничения Telegram API: лимит 64 байта на `callback_data`, валидность `icon_custom_emoji_id` (numeric digits), кнопки без действий.
  - Выявляет структурные аномалии: висячие экраны (`dangling_handler`), тупики без навигации (`dead_end`), отсутствие кнопки «Назад» (`missing_back`), дубликаты экранов (`duplicate_screen`).
- [`tg_flowmap/emoji_fetcher.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/emoji_fetcher.py) — клиент Telegram Bot API для извлечения кастомных Telegram Premium эмодзи. Проверяет локальный дисковый кэш (`.cache/emojis/`), при наличии токена загружает недостающие стикеры пачками по 100 штук и кодирует их в Base64 Data URL.

### Зона 3: Интерактивный Canvas-визуализатор и UI
- [`tg_flowmap/templates/viewer.html`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/templates/viewer.html) — DOM-каркас визуализатора: трехслойная сцена (`#svg-layer` для кривых Безье, `#edge-labels-container` для счетчиков бандлов, `#nodes-container` для карточек сообщений), поисковый хэдер и HUD-контроллеры зума.
- [`tg_flowmap/templates/viewer.js`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/templates/viewer.js) — реактивный движок визуализации и раскладки:
  - *Layout Engine*: строит остовное BFS-дерево от `/start` и `cb:menu` с трифуркацией дочерних ветвей (влево, по центру вниз, вправо).
  - *Multi-Deck Grid*: раскладывает вторичные команды, утилиты/попапы и обработчики в отдельные колоды.
  - *Pass 2 Height Refinement*: двухпроходный каскад (`refineDeckWithDomHeights`) измеряет реальные DOM-высоты карточек и динамически сдвигает колоды вниз во избежание наложений.
  - *Edge Bundler*: группирует множественные связи между одними и теми же узлами в единые кривые со счетчиком (`×N кнопок`).
  - *Viewport Camera*: плавный зум/пан, drag-and-drop карточек с синхронным пересчетом связей, подсветка ветвей по клику и наведению.
- [`tg_flowmap/templates/viewer.css`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/templates/viewer.css) — стили и производительность: динамическое переключение аппаратного GPU-ускорения (`translate3d` + `will-change: transform` на время движения, субпиксельный 2D `translate` в покое для четкости DirectWrite), цветовое кодирование нод (Command, Screen, Callback, Popup), адаптивные бейджи и LOD (Level-of-Detail).

---

## 3. 🔄 Жизненный цикл и сквозной Data Flow

1. **Инициализация и запуск:**
   - Пользователь запускает `run.py` (интерактивно или перетаскиванием папки бота) либо вызывает CLI: `tg-flowmap /path/to/bot -o map.html`.
   - Система валидирует входной путь, загружает токен бота из окружения или `.env`.
2. **Проход 1 — Статический сбор определений:**
   - `AstParser` сканирует `.py` файлы (исключая `.venv`, `tests`).
   - `extract_module_constants` собирает глобальные константы и метаданные иконок (`icons.json`).
   - `_extract_keyboards` парсит клавиатуры, разрешает локальные переменные, методы билдеров и присваивает имена клавиатурам.
3. **Проход 2 — Извлечение маршрутов и экранов:**
   - `_extract_handlers` парсит функции-обработчики, сопоставляет декораторы (`@dp.message`, `@dp.callback_query`), ветки `if/elif` и блоки `match/case`.
   - `_find_message_dispatch` находит точки генерации сообщений (`send_message`, `edit_text`) и связывает текст с клавиатурой.
   - `_consolidate_duplicate_screens` объединяет команды-дубликаты и помечает узлы возврата в меню.
4. **Топологический синтез и аудит:**
   - `GraphAnalyzer` связывает кнопки с целевыми экранами через многоуровневый резолвер.
   - Выполняется аудит: поиск `dead_end`, `null_emoji`, `callback_too_long`, `missing_back`, `dangling_handler`, `duplicate_screen`.
   - Формируется объект `BotMap`.
5. **Обогащение кастомными эмодзи:**
   - `emoji_fetcher` извлекает `custom_emoji_ids` из кнопок и тегов `<tg-emoji>`.
   - Проверяется кэш `.cache/emojis/`; недостающие стикеры скачиваются через Telegram API и конвертируются в base64 data URI.
6. **Компиляция артефакта и доставка:**
   - Терминал выводит статистику и список проблем с привязкой к строкам исходников (`file:line`).
   - `HtmlVisualizer` генерирует самодостаточный `.html` файл (или дамп `.json`).
   - `run.py` открывает сгенерированный холст в браузере по умолчанию.

---

## 4. 📊 Визуальная схема взаимодействия (Mermaid)

```mermaid
flowchart TD
    subgraph Input["Точки входа"]
        User["Разработчик"] --> Run["run.py (Interactive / Drag&Drop)"]
        CLI["tg_flowmap/cli.py (Headless CLI)"]
        User --> CLI
    end

    subgraph AST["Движок статического AST-анализа"]
        Run --> Parser["AstParser (parser.py)"]
        CLI --> Parser
        Parser --> Eval["ast_evaluator.py (Sandboxed AST Eval)"]
        Eval --> Parser
        Parser -->|Nodes, Keyboards, Aliases| Analyzer["GraphAnalyzer (analyzer.py)"]
    end

    subgraph Network["Сетевой слой & Кэш"]
        Analyzer -.->|Custom Emoji IDs| Fetcher["emoji_fetcher.py"]
        Fetcher <-->|Check / Save| Cache[(".cache/emojis/")]
        Fetcher <-->|HTTP API (Token)| TG_API["Telegram Bot API (Stickers CDN)"]
    end

    subgraph Synthesis["Синтез графа и аудит"]
        Analyzer --> Model["BotMap (models.py)"]
        Fetcher -->|Base64 Data URIs| Model
        Model --> Diagnostics["Консольный отчет (stdout)"]
    end

    subgraph Export["Генерация артефакта"]
        Model --> Viz["HtmlVisualizer (visualizer.py)"]
        Viz --> BundledHTML["Автономный HTML-файл (*_flowmap.html)"]
        Model -.-> JSON["Dump JSON (*.json)"]
    end

    subgraph Frontend["Холст в браузере (viewer.js)"]
        BundledHTML --> Viewer["viewer.html / viewer.css / viewer.js"]
        Viewer --> Forest["BFS Spanning Forest (/start, cb:menu)"]
        Forest --> Decks["Two-Pass Multi-Deck Cascade"]
        Decks --> Connectors["Edge Bundling & Bézier Routing"]
        Connectors --> Canvas["Интерактивный граф (Zoom, Pan, Drag, Filter)"]
    end
```

---

## 5. ⚠️ Зоны хрупкости («Где может повалиться»)

### 1. Безопасность: Stored DOM XSS через `node.text_template` в браузере
- **Механика сбоя:** В [`viewer.js`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/templates/viewer.js) при создании карточки выполняется присваивание `body.innerHTML = node.text_template` (строки 804 и 858). Функция `formatMessageText` заменяет только теги `<tg-emoji>`, но не санитизирует произвольный HTML.
- **Последствия:** Если в анализируемом боте шаблон сообщения содержит сырой пользовательский ввод, теги `<script>` или `<img onerror=...>`, при открытии сгенерированного HTML-файла в браузере выполнится произвольный JavaScript-код в контексте локального файла (`file:///`).
- **Архитектурная рекомендация:** Прогонять `node.text_template` через экранирование (`textContent` или `escapeHtml()`) перед подстановкой или разрешать только безопасное подмножество Telegram HTML-тегов (`<b>`, `<i>`, `<code>`, `<pre>`).

### 2. Производительность: Reflow Thrashing и взрыв DOM на графах 500+ узлов
- **Механика сбоя:** В [`viewer.js`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/templates/viewer.js) при перемещении карточки мышью (`setupCardDrag`) обработчик `mousemove` вызывает `renderConnectors()`, который полностью удаляет и пересоздает все SVG-пути (`edgesGroup.innerHTML = ""`) и баджи лейблов (`labelsContainer.innerHTML = ""`), параллельно рассчитывая координаты центров кнопок через циклы `while (el.offsetParent)`.
- **Последствия:** Синхронный `forced synchronous reflow` на каждый кадр движения мыши. При 300+ карточках и 1000+ кнопках FPS проседает до 5–10, интерфейс фризится.
- **Архитектурная рекомендация:** При драге обновлять только пути, инцидентные перемещаемой карточке, а координаты портов кэшировать относительно карточки, избегая постоянного опроса `offsetParent`.

### 3. Сеть: Блокирующий опрос стикеров и лимиты Telegram API (HTTP 429)
- **Механика сбоя:** В [`emoji_fetcher.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/emoji_fetcher.py) запросы на скачивание эмодзи выполняются синхронно через `urllib.request`. Для каждого недостающего стикера выполняются отдельные вызовы `getFile` и скачивание файла с жестким таймаутом 8.0с.
- **Последствия:** Если в боте используется 50 новых кастомных эмодзи, CLI блокируется на десятки секунд. При получении HTTP 429 (Rate Limit) повторные попытки с экспоненциальной задержкой отсутствуют — стикеры просто отбрасываются.
- **Архитектурная рекомендация:** Добавить пул потоков (`concurrent.futures.ThreadPoolExecutor`) для параллельной загрузки недостающих стикеров и базовую обработку заголовка `Retry-After`.

### 4. Статический анализ: Динамические колбэки и кастомные фасады диспетчеризации
- **Механика сбоя:** AST-парсер не исполняет код во время работы. Динамические конструкции вроде `f"user_{user.id}_{action}_{salt()}"` или ключи, сформированные из БД, вычисляются как `"${action}"` или `"*"`. Вызовы кастомных фабрик рендеринга (`await ctx.render_screen(...)`, FSM-машины, aiogram Dialogs) не распознаются методом `_find_message_dispatch`.
- **Последствия:** Такие переходы помечаются анализатором как ложные тупики (`dead_end`), а экраны сообщений теряют связь с клавиатурами и фиксируются как висячие (`dangling_handler`).
- **Архитектурная рекомендация:** Поддержать конфигурационный файл сопоставлений (mapping rules) или кастомных хелперов проекта для явного указания нестандартных методов отправки.

### 5. Окружение: Пути и неинтерактивный ввод в CI/CD
- **Механика сбоя:** В [`run.py`](file:///C:/Projects/.github/tg-flowmap/run.py) `discover_candidate_bots()` жестко рассчитывает на структуру каталогов `SCRIPT_DIR.parent.parent`. При размещении в плоском корневом каталоге сканирование возвращает пустой список. В неинтерактивном окружении вызов `input()` завершается `EOFError`.
- **Последствия:** Сбои при автоматическом вызове скрипта через пайплайны или скрипты автоматизации.
- **Архитектурная рекомендация:** Проверять `sys.stdin.isatty()` перед `input()` и использовать аргументы CLI как приоритетный источник без перехода в диалог.

---

## 6. 🚀 Навигация для разработки (Точки входа)

- **Добавить новое правило линтинга кнопок или экранов:** [`tg_flowmap/analyzer.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/analyzer.py) ➔ методы `_inspect_button_lint` и `_check_missing_backs`.
- **Добавить поддержку нового фреймворка или синтаксиса роутеров:** [`tg_flowmap/parser.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/parser.py) ➔ метод `_inspect_decorated_handler` и `_inspect_if_route`.
- **Добавить поддержку новых билдеров клавиатур:** [`tg_flowmap/parser.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/parser.py) ➔ метод `_parse_keyboard_function` (словарь `builders`).
- **Изменить алгоритм раскладки колод или остовного дерева:** [`tg_flowmap/templates/viewer.js`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/templates/viewer.js) ➔ функции `layoutDeck`, `placeTreeNode`, `refineDeckWithDomHeights`.
- **Изменить стили карточек, связей или цветовое кодирование:** [`tg_flowmap/templates/viewer.css`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/templates/viewer.css).
- **Запуск тестов регрессии:** `pytest -v tests/` (содержит тесты производительности и линтинга).
