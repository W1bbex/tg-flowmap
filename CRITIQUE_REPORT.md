# Технический аудит и критика проекта tg-flowmap

> Дата: 2026-10-24 | Профиль: Open Source | Статус: Верифицировано родителем (Zero False Positives)

---

## 1. 🚨 Критические дефекты и уязвимости (P0 / P1)

- [tg_flowmap/dast/navigation_executor.py:L98-L105](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/navigation_executor.py#L98-L105) — **Искажение и порча callback_data через слепой `base64.b64decode`**.
  Метод `_to_button_ref` безоговорочно пытается выполнить `base64.b64decode` для любой строковой `callback_data`. Любые стандартные ASCII-слова длиной кратной 4 символам (`"menu"`, `"page"`, `"user"`, `"test"`, `"help"`, `"news"`, `"shop"`) корректно парсятся base64 в бинарный мусор (например, `"menu"` превращается в `b'\x99\xe9\xee'`, а `"user"` в `b'\xba\xc7\xab'`). В результате Telegram или удаленный бот отвергают искаженные байты, либо обработчики бота не могут сопоставить входящий callback.

- [tg_flowmap/cli.py:L210, L242-L248](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/cli.py#L242-L248) — **Фиктивный запуск DAST краулера в CLI (`run_dast`)**.
  Класс `BotCrawler` импортируется в строке 210, но нигде не инстанцируется и не вызывается. Функция `run_dast()` просто подключается к локальной базе `State(cfg.state_db_path)`, вызывает `generate_reports(...)` на существующих в БД данных (или пустой БД) и бодро выводит: `✅ Обход завершён!`. Реальный сетевой обход Telegram-бота через команду CLI `tg-flowmap dast @bot` полностью отсутствует.

- [tg_flowmap/dast/scheduler.py:L140-L191](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/scheduler.py#L140-L191) — **Рассинхронизация статусов ботов при ошибке разрешения (`zip(bots, results)`)**.
  В цикле планировщика при сбое `_resolve_entity` выполняется `continue` (строка 147) без добавления задачи в список `tasks`. В итоге `len(tasks) < len(bots)`. В строке 185 `zip(bots, results)` сопоставляет результаты успешных задач с именами ботов со сдвигом с индекса 0: бот, упавший на резолве, получает статус успешно завершившегося соседа, а последний бот списка бесследно теряется.

- [tg_flowmap/dast/reports.py:L441-L443](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/reports.py#L441-L443) — **Фатальный сбой `KeyError: 'payload_json'` при сбое парсинга JSON в таймлайне**.
  В блоке `try` выражение `row["payload"] = json.loads(row.pop("payload_json") or "null")` удаляет ключ `"payload_json"` до передачи строки в `json.loads`. Если `json.loads` выбрасывает `json.JSONDecodeError`, управление переходит в блок `except`, где вызывается `row.pop("payload_json")` повторно. Из-за отсутствия ключа возникает неперехваченный `KeyError`, прерывающий генерацию отчета.

- [.gitignore:L1-L23](file:///C:/Projects/.github/tg-flowmap/.gitignore#L1-L23) — **Утечка приватных сессий Telethon в открытый репозиторий (P1 Security)**.
  В `.gitignore` отсутствуют правила для `*.session` и `*.session-journal`. При запуске DAST Telethon сохраняет файл сессии SQLite с полным авторизационным `auth_key`. Публикация репозитория в GitHub с этим файлом приводит к перманентной компрометации учетной записи Telegram и возможности удаленного перехвата управления.

- [tg_flowmap/dast/crawler.py:L316-L318, L838-L845](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/crawler.py#L316-L318) — **Обрыв восстановления экранов при навигации по графу (`create_route=False`)**.
  При переходе к новым экранам вызов `_observe` выполняется с флагом `create_route=False`. В результате в `known_routes` не сохраняется путь восстановления. Когда `RoutePlanner` запускает восстановление через `/start` (`_replay_path`), шаги пути оказываются пустыми (`path = []`), проверка `nav_ref.screen_id == target_screen_id` проваливается на корневом экране (`/start`), экран помечается как stale, а краулер исчерпывает лимит попыток и аварийно завершается с `AbortScan("too many consecutive errors")`.

- [tg_flowmap/dast/navigator.py:L211-L228](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/navigator.py#L211-L228) — **10-секундное зависание и ложный статус "success" при RPC-ошибках кнопок**.
  Если `_press_callback` возвращает ошибку (например, `FloodWaitError`, `BotResponseTimeoutError`), навигатор не прерывает обработку, а уходит в ожидание `wait_result(10s)`. Если в течение этого времени приходит любое фоновое сообщение чата, `primary is not None` оценивается как `True` и упавшему действию ошибочно присваивается статус `success`.

- [tg_flowmap/dast/map_render.py:L498-L500](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/map_render.py#L498-L500) — **Генерация синтаксически невалидного графа Mermaid для recovery-связей**.
  При `result_type == "recovery"` переменная `arrow` принимает значение `-.->|recovery|`. Строка 500 формирует запись `src -.->|recovery||"label"| dst`. Два блока меток в вертикальных чертах подряд (`|recovery||"label"|`) запрещены грамматикой Mermaid и приводят к ошибкам парсинга файла `map.mmd` во всех просмотрщиках.

- [tg_flowmap/core/comparator.py:L51-L55, L79, L115](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/core/comparator.py#L51-L55) — **Крах `AttributeError` при сравнении ботов (NoneType клавиатуры и BotMap)**.
  1. Выражение `len(n.get("keyboard", {}).get("rows", []))` падает с `AttributeError: 'NoneType' object has no attribute 'get'`, если нода имеет `"keyboard": None` в словаре.
  2. Методы `build_comparison_markdown` и `export` вызывают `self.bot_a_data.get("metrics")`. Если передан инстанс датакласса `BotMap` (что разрешено конструктором), код падает с `AttributeError: 'BotMap' object has no attribute 'get'`.

- [tg_flowmap/dast/state.py:L823, L969](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/state.py#L969) — **Падение `TypeError` при прямой сериализации `json.dumps()` в State**.
  В `timeline_create` и `add_callback` вызывается стандартный `json.dumps(payload)` без вызова функции санитарной очистки `clean()`. При наличии в `payload` сырых байтов `bytes` (из `callback_data`), объектов Telethon или дат, процесс аварийно завершается с `TypeError: Object of type bytes is not JSON serializable`.

- [tg_flowmap/dast/config.py:L10, L210, L231](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/config.py#L10) — **Смещение якоря `PACKAGE_ROOT` внутрь пакета**.
  `PACKAGE_ROOT = Path(__file__).resolve().parent.parent` в файле `tg_flowmap/dast/config.py` указывает на папку пакета `tg_flowmap/`, а не на корень репозитория `tg-flowmap`. В результате дефолтный конфиг ищется в `tg_flowmap/config.json`, ответы в `tg_flowmap/manual_answers.json`, а база данных `explorer.db` создается прямо внутри папки исходного кода пакета.

---

## 2. ⚠️ Архитектурные костыли и антипаттерны (P2)

- [tg_flowmap/cli.py:L333-L337](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/cli.py#L333-L337) — **Фальсификация метрик конкурента в режиме `compare`**.
  Если целевой бот `target_b` отсутствует на диске и не найден в локальном кэше графов, утилита молча генерирует фейковые синтетические данные (15 экранов, 42 кнопки, разделы «Каталог», «Корзина», «Помощь») и формирует на их основе сравнительный отчет и LLM-промпт, вводя пользователя и нейросеть в заблуждение без единого предупреждения.

- [tg_flowmap/dast/map_render.py:L402](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/map_render.py#L402) — **Искажение метрики доверия (confidence) в UI инспектора графа**.
  В JavaScript выражение `((e.confidence || 1.0) * 100).toFixed(0)` при значении `confidence: 0.0` (связь со 100% сбоем) вычисляет `1.0` (так как 0 — falsy), отображая пользователю `100%` вместо `0%` (требуется `e.confidence ?? 1.0`).

- [tg_flowmap/sast/evaluator.py:L48, L55](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/sast/evaluator.py#L48) — **Незащищенная рекурсия в `evaluate_ast_node` (`RecursionError`)**.
  При циклических или самоссылающихся присваиваниях переменных (например, `x = x` или `a = b; b = a`) функция рекурсивно разворачивает переменные без отслеживания посещенных нод и лимита глубины, приводя к переполнению стека вызовов.

- [tg_flowmap/sast/evaluator.py:L18-L115](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/sast/evaluator.py#L18-L115) — **Потеря AST-нод `Tuple`, `Set`, `UnaryOp`, `Subscript`**.
  Отсутствие обработчиков приводит к тому, что отрицательные константы (`-1`), кортежи фильтров `("/start", "/help")` и множества возвращают `None`, искажая карту переходов и отбрасывая валидные ветки кнопок.

- [tg_flowmap/sast/evaluator.py:L59-L60](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/sast/evaluator.py#L59-L60) — **Схлопывание атрибутов Enum в общий идентификатор `$value`**.
  Любой доступ к значению перечисления (`Action.START.value`, `State.MENU.value`) возвращает литерал `"$value"`, из-за чего все кнопки разных перечислений считаются указывающими на один и тот же маршрут.

- [tg_flowmap/dast/safety.py:L51](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/safety.py#L51) — **Отсутствие импорта `Any` в `safety.py`**.
  В строке 51 используется аннотация `s: Any`, однако `Any` не импортирован из `typing`. При инспекции сигнатур через `typing.get_type_hints` возникает `NameError: name 'Any' is not defined`.

- [tg_flowmap/dast/state.py:L523-L532](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/state.py#L523-L532) — **Шторм запросов N+1 в `messages_all`**.
  Метод выполняет $2N + 1$ мелких SQL-запросов (отдельные SELECT для entities и media на каждое сообщение). Для 1000 сообщений это порождает свыше 2000 запросов и блокирует поток SQLite.

- [tg_flowmap/dast/reports.py:L426](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/reports.py#L426) — **Потенциальный Path Traversal в имени бота**.
  Имя бота очищается только через `lstrip("@")`. Если имя содержит `../`, файлы `report.md`, `errors.log` и `graph.json` сохраняются за пределами каталога `output_dir`.

- [tg_flowmap/cli.py:L373, L416](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/cli.py#L373) — **Утечка токена бота через аргументы командной строки**.
  Флаг `--token` передается открытым текстом в аргументах CLI, раскрывая секретный токен в таблице процессов ОС (`ps`, Process Explorer) и истории оболочек.

- [run.py:L60-L72](file:///C:/Projects/.github/tg-flowmap/run.py#L60-L72) — **Преждевременный обрыв сканирования рабочих пространств**.
  Одиночный `try...except` оборачивает весь цикл поиска ботов в `C:\Projects`. Если одна из соседних папок вызывает `PermissionError`, сканирование полностью прерывается, игнорируя все оставшиеся проекты.

---

## 3. 🏰 Монолитность и архитектурная декомпозиция (God Objects & Complexity)

Кодовая база содержит три выраженных монолитных God-объекта, вплотную приближающихся к критическому порогу в 1000 строк (нарушение правила 3):

1. **`tg_flowmap/dast/state.py` (1008 строк, класс `State` — 736 строк)**:
   - *Проблема*: Класс `State` управляет 18 независимыми таблицами базы данных, совмещая миграции, хранение снимков сообщений, топологию графа, очереди обхода (frontier), лог таймлайна, кэш сущностей эмодзи и счетчики метрик.
   - *Maintainability Index*: **A (22.58)** при высокой структурной связанности.
   - *Рекомендация по декомпозиции (SRP)*: Разделить монолит на специализированные репозитории: `ScreenRepository`, `GraphEdgeRepository`, `TimelineRepository`, `CrawlerProgressRepository`, объединенные через легкий фасад `DatabaseSession`.

2. **`tg_flowmap/sast/parser.py` (993 строки, класс `AstParser` — 944 строки)**:
   - *Проблема*: Совмещает обход файловой системы, разбор AST модулей, извлечение констант, парсинг Reply/Inline клавиатур aiogram и telebot, анализ условий `if/elif/match`, парсинг регулярных выражений и разрешение алиасов экранов.
   - *Maintainability Index*: **C (0.00)** — наихудший показатель в проекте.
   - *Рекомендация по декомпозиции (SRP)*: Выделить `KeyboardAstParser` (парсинг кнопок и разметки) и `HandlerRouteExtractor` (анализ условий диспетчеризации сообщений) в отдельные изолированные модули.

3. **`tg_flowmap/dast/crawler.py` (973 строки, класс `BotCrawler` — 913 строк)**:
   - *Проблема*: Объединяет в себе навигационный цикл, планирование маршрутов, обработку сценариев диалогов, скачивание медиа, эвристику смены состояний и обработку ручных ответов.
   - *Maintainability Index*: **C (0.00)**.
   - *Рекомендация по декомпозиции (SRP)*: Вынести логику восстановления путей (`_replay_path`, `_return_to_screen`) в отдельный навигационный компонент `PathReplayer`.

### Функции с критической цикломатической сложностью (Radon CC Rank E/F > 30):
- `tg_flowmap/sast/parser.py:AstParser._find_message_dispatch` — **F (79)**
- `tg_flowmap/sast/evaluator.py:evaluate_ast_node` — **F (59)**
- `tg_flowmap/sast/analyzer.py:GraphAnalyzer.build_map` — **F (55)**
- `tg_flowmap/dast/reports.py:build_report_md` — **F (45)**
- `tg_flowmap/sast/parser.py:AstParser._parse_keyboard_function` — **F (43)**
- `tg_flowmap/sast/parser.py:AstParser._parse_keyboard_expr` — **F (42)**
- `tg_flowmap/dast/comparison.py:generate_comparison` — **E (39)**
- `tg_flowmap/sast/parser.py:AstParser._extract_keyboards` — **E (38)**
- `tg_flowmap/sast/parser.py:AstParser._parse_button_element` — **E (37)**
- `tg_flowmap/dast/screen_identity.py:match_button_instance` — **E (34)**

---

## 4. 🪦 Мертвый код и рудименты (Dead Code Audit)

### 1. Подтвержденный мертвый код (Vulture & Static Audit):
- `tg_flowmap/dast/config.py:L7`: неиспользуемый импорт `asdict` (Vulture confidence 90%).
- `tg_flowmap/dast/navigation_graph.py:L15`: неиспользуемый импорт `Any`.
- `tg_flowmap/dast/comparison.py:L9`: неиспользуемый импорт `defaultdict`.
- `tg_flowmap/dast/fingerprint.py:L10-L12`: неиспользуемые импорты `json`, `re`, `Any`, `Iterable`.
- `tg_flowmap/dast/crawler.py:L31`: неиспользуемый импорт `PressOutcome`.
- `tg_flowmap/dast/navigation_graph.py:L238-L240`: мертвые переменные `best_target`, `best_path`, `best_cost` в методе `find_nearest_screen_with_targets`.
- `tg_flowmap/dast/models.py:L229-L272`: неиспользуемый класс `ButtonInstance` (0 вызовов создания экземпляров во всей кодовой базе).

### 2. Дублирование статических ассетов и устаревшие модули-обертки:
- **Дубликаты ассетов**: Каталоги `tg_flowmap/templates/` и `tg_flowmap/visualizer/templates/` содержат идентичные файлы (`viewer.html`, `viewer.css`, `viewer.js`). При этом рендерер `html_builder.py` обращается исключительно к `visualizer/templates/`. Корневая папка `tg_flowmap/templates/` является неиспользуемым балластом.
- **Устаревшие корневые модули-обертки**: Модули `tg_flowmap/models.py`, `tg_flowmap/parser.py`, `tg_flowmap/analyzer.py`, `tg_flowmap/visualizer.py`, `tg_flowmap/emoji_fetcher.py` и `tg_flowmap/ast_evaluator.py` служат реэкспортом. Внутренние модули пакета (`sast/parser.py`, `sast/analyzer.py`) ошибочно импортируют зависимости из этих внешних оберток, формируя запутанные перекрестные связи.

---

## 5. 💎 Инженерные находки (Реальные плюсы)

- **Комплексная синергия статического и динамического анализа (SAST + DAST)**: Проект элегантно объединяет абстрактный синтаксический анализ исходного кода Telegram-бота с динамическим исследованием реального работающего бота через Telethon API.
- **Устойчивая нормализация экранов (`screen_identity.py`)**: Качественная реализация очистки динамических данных (даты, таймстемпы, юзернеймы, балансы кошельков, хэши транзакций), позволяющая сопоставлять экраны с динамическим содержимым.
- **Развитая интерактивная визуализация**: Модуль генерации HTML-карты строит функциональный интерактивный граф на SVG с подсветкой тупиковых экранов, отсутствующих кнопок возврата в меню и инспектором переходов.
- **Надежный набор регрессионных тестов**: 182 теста, полностью покрывающих базовые механизмы графа, фингерпринтов, таймлайна и экранов, отрабатывающих за 9 секунд.

---

## 6. 🛠 Приоритетный Roadmap исправлений

### 🔴 Спринт 1: Критическая безопасность и починка сломанного функционала
1. **Защитить сессии**: Добавить `*.session` и `*.session-journal` в `.gitignore`.
2. **Исправить порчу callback_data**: Убрать `base64.b64decode` для обычных строк в `navigation_executor.py:L98-L105`.
3. **Подключить краулер в CLI**: Связать `run_dast` в `cli.py` с вызовом `BotCrawler.run()`.
4. **Исправить сбои отчетов и БД**: Устранить двойной `.pop()` в `reports.py` и защитить `json.dumps()` в `state.py` через `clean()`.
5. **Починить планировщик**: Устранить рассинхронизацию `zip(bots, results)` в `scheduler.py`.
6. **Скорректировать `PACKAGE_ROOT`**: Указать в `config.py` правильный путь к корню репозитория.

### 🟡 Спринт 2: Устранение фальсификаций и ошибок компаратора
1. **Починить `BotComparator`**: Добавить безопасную обработку отсутствующих клавиатур (`n.get("keyboard") or {}`) и поддержку датакласса `BotMap`.
2. **Убрать синтетические моки**: В `cli.py` при отсутствии второго бота выбрасывать понятную ошибку вместо тихой генерации фейковых экранов.
3. **Починить синтаксис графов**: Исправить генерацию Mermaid-диаграмм в `map_render.py` и выражение `(e.confidence ?? 1.0)`.

### 🟢 Спринт 3: Декомпозиция монолитов и чистка кодовой базы
1. **Декомпозировать `state.py`** на отдельные репозитории для экранов, переходов и таймлайна.
2. **Декомпозировать `sast/parser.py`** с выделением парсера клавиатур в отдельный модуль.
3. **Удалить дублирующуюся папку `tg_flowmap/templates/`** и очистить неиспользуемые импорты и переменные.
4. **Устранить импорты через рудиментарные обертки**: перевести внутренние модули на канонические пути `tg_flowmap.core.models` и `tg_flowmap.sast.evaluator`.
