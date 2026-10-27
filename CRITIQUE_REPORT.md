# Технический аудит и критика проекта tg-flowmap

> Дата: 2026-10-26 | Профиль: Open Source | Статус: Верифицировано родителем

## 1. 🚨 Критические дефекты и уязвимости (P0 / P1)

- [tg_flowmap/cli.py:L240-L242](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/cli.py#L240-L242) + [tg_flowmap/dast/config.py:L138-L139](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/config.py#L138-L139) — **Утечка приватного файла Telegram-сессии (.session) в пользовательскую папку отчетов**
  - **Механика**: В `run_dast_scan` при передаче аргумента `-o / --output` выполняется `cfg.root = output_dir`. Свойство `session_path` в `config.py` вычисляется как `self.root / self.session_name`. В результате файл Telethon-сессии (`market_research.session`), содержащий приватные ключи авторизации, хэши Telegram API и токены доступа пользователя, сохраняется прямо в пользовательскую папку с публичными отчетами.
  - **Последствия**: При публикации, отправке коллегам или загрузке отчетов на GitHub / сервер происходит полная компрометация учетной записи Telegram. Кроме того, `cfg.output_dir` превращается в `output_dir / "output"`, создавая ошибочную двойную вложенность.

- [tg_flowmap/cli.py:L298-L308](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/cli.py#L298-L308) + [tg_flowmap/dast/reports.py:L205](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/reports.py#L205) — **Полная неработоспособность сравнения DAST-обходов (`tg-flowmap compare`)**
  - **Механика**: В `graph.json`, генерируемом `reports.py:205`, ключами верхнего уровня являются `"nodes"`, `"edges"` и `"routes"`. Ключа `"screens"` в JSON не существует. Функция `_load_target_data` в `cli.py` вызывает `graph_data.get("screens", [])`, что всегда возвращает пустой список `[]`. Метрика `screens_count` всегда оказывается равной 0, массив экранов пуст, а `buttons_count` ошибочно вычисляется как `len(routes)`.
  - **Последствия**: Команда `tg-flowmap compare @bot1 @bot2` для динамических отчетов всегда формирует пустой отчет с 0 экранов и 0 кнопок.

- [.github/workflows/tests.yml:L30-L35](file:///C:/Projects/.github/tg-flowmap/.github/workflows/tests.yml#L30-L35) + [pyproject.toml:L17](file:///C:/Projects/.github/tg-flowmap/pyproject.toml#L17) — **Падение CI тестового пайплайна на чистых раннерах GitHub Actions**
  - **Механика**: В `pyproject.toml` зависимость `telethon` объявлена как опциональная `[project.optional-dependencies] dast`, а `dependencies = []`. В workflow указано `pip install -e .` (без экстра-пакета `[dast]`). В файле `tests/dast/conftest.py:22` происходит безусловный импорт `from telethon.tl.types import ...`.
  - **Последствия**: Запуск тестов на свежих раннерах в GitHub Actions падает на этапе сбора тестов с `ModuleNotFoundError: No module named 'telethon'`.

- [tg_flowmap/sast/evaluator.py:L26-L32](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/sast/evaluator.py#L26-L32) — **Логическая инверсия булевых условий при вычислении унарного `not` в AST**
  - **Механика**: В `evaluate_ast_node` блок `isinstance(node, ast.UnaryOp)` проверяет только `ast.USub` и `ast.UAdd`, а для остальных операторов выполняет `return val`. Если узел является оператором `not`, выражение `not True` вычисляется как `True`, а `not False` как `False`.
  - **Последствия**: Все инвертированные булевы условия в анализируемых ботах вычисляются некорректно, искажая дерево переходов и маппинг экранов.

- [tg_flowmap/sast/evaluator.py:L110-L118](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/sast/evaluator.py#L110-L118) & [L171-L175](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/sast/evaluator.py#L171-L175) — **Необработанный `TypeError: unhashable type` при подписке и вызове `.get()`**
  - **Механика**: При разборе конструкций `dict_obj.get(key)` или `val[key]`, если `key` вычисляется в нехэшируемый тип (список или словарь), операции `key in val` и `.get(key)` падают с исключением `TypeError: unhashable type: 'list'`, не перехваченным в `evaluate_ast_node`.
  - **Последствия**: Статический анализатор аварийно прерывает сканирование репозитория бота при наличии выражений с динамическими ключами-списками.

- [tg_flowmap/dast/crawler.py:L318](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/crawler.py#L318) + [L844-L851](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/crawler.py#L844-L851) — **Разрыв графового восстановления маршрутов (Graph Recovery Breakage)**
  - **Механика**: При переходе по экранам через прямое действие в `_observe_outcome_for_step` передается флаг `create_route=False`. Из-за этого запись в таблицу `routes` для открытого экрана не создается. Когда `RoutePlanner` позже инициирует восстановление через `/start`, `route_path_map` возвращает пустой маршрут `[]`. В методе `_replay_path` проверка `nav_ref.screen_id == target_screen_id` проваливается (поскольку `/start` вернул root-экран, а target глубоко вложен), экран помечается как `recovery_exhausted`, и исследование всей ветки блокируется.
  - **Последствия**: Краулер теряет способность восстанавливать контекст и исследовать глубокие ветки меню бота.

- [tg_flowmap/dast/crawler.py:L658-L664](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/crawler.py#L658-L664) + [L565-L571](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/crawler.py#L565-L571) — **Несовпадение формата ID действий блокирует Dijkstra-навигацию через кнопки Back**
  - **Механика**: Метод `_return_to_screen` регистрирует ребро графа с `action_id = btn_to_press.button_fp` (16-символьный хэш) или `"act_back"`. При последующем прохождении пути через `_execute_local_path` ищется действие в `state.actions_for_screen`, где все идентификаторы имеют каноничный формат `act_<sha256>`. Совпадения никогда не происходит (`act is None`), ребро признается нестабильным, и прохождение пути завершается ошибкой.
  - **Последствия**: Все локальные возвраты графа через кнопки «Назад» гарантированно терпят неудачу в рантайме.

- [tg_flowmap/dast/navigator.py:L210-L216](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/navigator.py#L210-L216) — **Преждевременный выход теряет реальные ответы ботов и создает мертвый код**
  - **Механика**: При ошибке или таймауте callback query в `_press_callback` метод сразу возвращает `PressOutcome(kind="error", ...)`, минуя `router.wait_result`. Большинство ботов редактируют сообщение без вызова `answerCallbackQuery`. В итоге краулер игнорирует пришедшее сообщение бота, а строка L231 (`elif err is not None:`) оказывается абсолютно недостижимой.
  - **Последствия**: Ложные таймауты и пропуск экранов на ботах, не вызывающих `answerCallbackQuery`.

---

## 2. ⚠️ Архитектурные костыли и антипаттерны (P2)

- [tg_flowmap/dast/map_render.py:L498-L503](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/map_render.py#L498-L503) — **Неэкранированные символы пайпа `|` и переводы строк `\n` ломают диаграммы Mermaid**
  - Синтаксис стрелок `-->|"label"|` нарушается, если в тексте кнопки содержится `|` (например, `Оплата | СБП`) или перенос строки. Файл `map.mmd` становится невалидным для парсеров GitHub и Mermaid CLI.

- [tg_flowmap/dast/safety.py:L148-L150](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/safety.py#L148-L150) & [L161-L174](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/safety.py#L161-L174) — **Обход проверки деструктивных callback payload через белый список названий**
  - Проверка `allowed_labels` выполняется до анализа опасных паттернов в `callback_data`. Кнопка с невинным текстом «Да» или «Меню», но с пейлоадом `delete_account` или `confirm_charge`, пропускается фильтром безопасности.

- [tg_flowmap/dast/safety.py:L14-L19](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/safety.py#L14-L19) — **Отсутствие поддержки TON-кошельков (The Open Network)**
  - Список `WALLET_REGEXES` содержит регулярные выражения для ETH, BTC и TRON, но не отслеживает адреса TON (`EQ...` / `UQ...`), являющиеся базовым платежным инструментом Telegram. Экраны с TON-оплатой не помечаются как финансово опасные.

- [tg_flowmap/dast/media.py:L76-L86](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/media.py#L76-L86) — **Утечка поврежденных файлов медиа при отмене загрузки (`asyncio.CancelledError`)**
  - Блок `except Exception:` не перехватывает отмену задачи (`BaseException`). Частично скачанный файл остается на диске, а при следующем запуске проверка `st_size > 0` воспринимает его как валидный, навсегда фиксируя поврежденный медиафайл.

- [tg_flowmap/sast/parser.py:L517](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/sast/parser.py#L517) — **Потеря метаданных кнопок при разворачивании списковых включений**
  - При генерации кнопок из list comprehension создается новый объект `Button(text=..., callback_data=...)`, теряя `icon_custom_emoji_id`, `style`, `url` и другие атрибуты оригинального `elt_btn`.

- [tg_flowmap/sast/parser.py:L613-L620](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/sast/parser.py#L613-L620) — **Ложные срабатывания `dead_end` на aiogram 3 CallbackData фабриках с `.pack()`**
  - Вызов `MyCallback(...).pack()` извлекает имя метода `"pack"` вместо префикса класса `MyCallback`, что приводит к несовпадению с зарегистрированными хэндлерами и ложным сообщениям о тупиковых кнопках.

- [tg_flowmap/dast/comparison.py:L70-L82](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/comparison.py#L70-L82) — **N+1 запросы к SQLite и квадратичная O(S*B) сложность в сборе статистики**
  - В цикле по экранам на каждой итерации выполняется отдельный SQL-запрос наличия медиа и полный перебор всех кнопок бота.

- [tg_flowmap/dast/config.py:L10](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/config.py#L10) — **Засорение `site-packages` рабочими базами данных при установке через pip**
  - `PACKAGE_ROOT = Path(__file__).resolve().parents[2]` указывает на каталог `site-packages` при установленном пакете. `Config()` без параметров начинает создавать `explorer.db` и файлы сессий прямо внутри системного окружения Python.

---

## 3. 🏰 Монолитность и архитектурная декомпозиция (God Objects & Complexity)

- **Файлы-монолиты (> 800 строк)**:
  - [`tg_flowmap/sast/parser.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/sast/parser.py): **1,193 строки** (класс `AstParser` — 1,144 строки, Maintainability Index: **C (0.00)**). Нарушение лимита в 1,000 строк.
  - [`tg_flowmap/dast/state.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/state.py): **1,014 строк** (класс `State` — 15 таблиц БД, 45+ методов, смешение DDL, DML и бизнес-логики без контекстного менеджера).
  - [`tg_flowmap/dast/crawler.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/crawler.py): **979 строк** (класс `BotCrawler` — 918 строк, Maintainability Index: **C (0.00)**).

- **Критическая цикломатическая сложность (radon cc rank E/F)**:
  - `tg_flowmap/sast/parser.py: AstParser._find_message_dispatch` — **F (109)** (180 строк, 6 уровней вложенности).
  - `tg_flowmap/sast/evaluator.py: evaluate_ast_node` — **F (103)**.
  - `tg_flowmap/sast/analyzer.py: GraphAnalyzer.build_map` — **F (79)**.
  - `tg_flowmap/sast/parser.py: AstParser._parse_keyboard_function` — **F (56)**.
  - `tg_flowmap/dast/reports.py: build_report_md` — **F (46)**.
  - `tg_flowmap/dast/safety.py: SafetyFilter.button_verdict` — **E (39)**.
  - `tg_flowmap/dast/comparison.py: generate_comparison` — **E (39)**.

- **Рекомендации по декомпозиции (SRP)**:
  - Выделить парсинг клавиатур из `AstParser` в отдельный `KeyboardExtractor`.
  - Выделить диспетчеризацию роутов из `AstParser` в `RouteExtractor`.
  - В `dast/crawler.py` вынести логику восстановления маршрутов и replay в `RecoveryEngine`.
  - Реализовать поддержку контекстного менеджера `__enter__` и `__exit__` в классе `State`.

---

## 4. 🪦 Мертвый код и рудименты (Dead Code Audit)

- **Заброшенные файлы**:
  - [`tg_flowmap/dast/console.py`](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/dast/console.py) (**188 строк**): модуль с функциями `main_menu`, `add_bot`, `list_bots`, `start_scan` нигде в проекте не импортируется и не используется.
- **Неиспользуемые и дублирующиеся импорты**:
  - `tg_flowmap/cli.py:210`: `telethon` (vulture 90%).
  - `tg_flowmap/cli.py:220`: повторный `import asyncio`.
  - `tg_flowmap/cli.py:221`: `Config` не используется в `run_dast_scan`.
  - `tg_flowmap/dast/fingerprint.py:9-12`: `json`, `re`, `Any`, `Iterable`.
  - `tg_flowmap/dast/navigator.py:43`: локальный дублирующий `import asyncio`.
  - `tg_flowmap/core/comparator.py:3, 5`: `json`, `List`, `Optional`.
  - `tg_flowmap/core/llm_exporter.py:3`: `Path`.
  - `tg_flowmap/sast/emoji.py:7`: `urllib.error`.
- **Мертвые ветки условий**:
  - `tg_flowmap/dast/navigator.py:231`: ветка `elif err is not None:` никогда не выполняется из-за досрочного `return` на L216.
  - `tg_flowmap/sast/parser.py:180-182`: ветка `not node.keyboard` недостижима из-за `if not node.keyboard: continue` на L165.
  - `tg_flowmap/sast/parser.py:1075-1080`: дублирующая ветка `if attr_name in self.keyboards: ... else: ...`.
- **Рудиментарные корневые шимы**:
  - `tg_flowmap/analyzer.py`, `tg_flowmap/ast_evaluator.py`, `tg_flowmap/emoji_fetcher.py`, `tg_flowmap/models.py`, `tg_flowmap/parser.py`.

---

## 5. 💎 Инженерные находки (Реальные плюсы)

- **Безопасный статический анализ без выполнения непроверенного кода**: парсер полностью анализирует структуру Telegram-ботов через AST Python без импорта и исполнения кода.
- **Эвристическая защита от списаний баланса и выполнения покупок в DAST**: многоуровневый фильтр контекста сообщений защищает от случайных оплат при динамическом сканировании.
- **Оптимизация обхода через граф переходов (Dijkstra)**: минимизация вызовов API и избежание FloodWait за счет локальных перемещений по известным ребрам.
- **Автономный интерактивный визуализатор**: генерация единого HTML-файла с поддержкой SVG, масштабированием и предпросмотром экранов.

---

## 6. 🛠 Приоритетный Roadmap исправлений

1. **Этап 1: Безопасность и работоспособность CI/CD (P0)**
   - Изолировать размещение файлов сессии Telethon от папки отчетов в `cli.py` и `config.py`.
   - Исправить сопоставление полей `graph.json` в `cli.py:299` для восстановления работы команды `tg-flowmap compare`.
   - В `.github/workflows/tests.yml` добавить установку `.[dast]`.
2. **Этап 2: Критические дефекты анализатора и краулера (P1)**
   - Добавить поддержку `ast.Not` и защиту от unhashable-типов в `evaluator.py`.
   - Исправить сохранение маршрутов `create_route=True` для новых экранов и выравнивание action_id в `crawler.py`.
   - Устранить досрочный возврат при callback-ошибке в `navigator.py`.
3. **Этап 3: Декомпозиция монолитов и чистка мертвого кода (P2 / P3)**
   - Удалить мертвый модуль `console.py` (188 строк) и почистить неиспользуемые импорты.
   - Экранировать спецсимволы в `map_render.py` для корректного рендеринга Mermaid.
   - Добавить регулярное выражение для TON-кошельков и переместить проверку callback payload в `safety.py`.
   - Провести декомпозицию `sast/parser.py` (1,193 строки) и `dast/crawler.py` (979 строк).
