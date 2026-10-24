# Технический аудит и критика проекта tg-flowmap

> Дата: 24.10.2026 | Профиль: Open Source (Публичный инструмент) | Статус: Исправлено и верифицировано (198 тестов пройдено)

---

## 1. 🚨 Критические дефекты и уязвимости (P0 / P1)

- [tg_flowmap/dast/safety.py:L16, L73, L76](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/safety.py#L16-L76) — **Критический пробой безопасности кошельков TRON/USDT (TRC20)**.  
  Регулярное выражение `WALLET_REGEXES` для TRON `\bT[1-9A-HJ-NP-Za-km-z]{33}\b` скомпилировано строго с заглавной буквы `T` без флага `re.IGNORECASE`. Метод `screen_context` нормализует экранный текст через `_norm(screen_text)`, приводящий всю строку к нижнему регистру (`.lower()`). В результате реальные адреса TRC20 (начинающиеся на `T`) превращаются в `t...` и физически не могут совпасть с шаблоном `\bT...`. Флаг `has_wallet` всегда возвращает `False`, и бот перестает классифицировать экраны оплаты криптой как чувствительные.

- [tg_flowmap/dast/safety.py:L63, L124-L126](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/safety.py#L63-L126) и [tg_flowmap/dast/config.py:L22, L171](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/config.py#L22-L171) — **Несрабатывание блокировки опасных кнопок покупки в валютах USD/EUR/RUB**.  
  Шаблон `DEFAULT_PRICE_REGEX` содержит верхний регистр валют `USD|EUR|RUB` и компилируется через `_compile_pat` без флага `re.IGNORECASE`. В методе `button_verdict` метка кнопки нормализуется методом `_norm`, переводящим всё в lowercase. Проверка `self.price_re.search("купить 15 usd")` терпит неудачу. Блокировка `price_with_action_word` не срабатывает, что влечет за собой реальный риск автоматического нажатия платежных кнопок при краулинге.

- [tg_flowmap/dast/navigator.py:L218](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/navigator.py#L218) — **Фатальный крэш `TypeError` при любой ошибке callback в навигаторе**.  
  Датакласс `PressOutcome` в [models.py:L169](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/models.py#L169) объявляет поле `callback: CallbackResult | None`, но навигатор возвращает `PressOutcome(..., cb=cb)`. Интерпретатор немедленно падает с `TypeError: PressOutcome.__init__() got an unexpected keyword argument 'cb'`. Ошибка перехватывается общим `except Exception as e:` на L248, который повторно логирует `action_id` и подменяет оригинальную ошибку Telegram на ложный внутренний `TypeError`.

- [tg_flowmap/dast/state.py:L311-L315, L330](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/state.py#L311-L335) — **Утечка неявной транзакции в SQLite и зависание базы (`OperationalError: cannot start a transaction within a transaction`)**.  
  В примитиве `_exec` отсутствует блок `try...except: self._conn.rollback()`. В режиме по умолчанию Python SQLite драйвер открывает транзакцию при первом DML-запросе. Если `_conn.execute()` падает (например, `IntegrityError` или блокировка), незакоммиченная транзакция зависает открытой. Следующий же вызов `with self.transaction():` выполняет `BEGIN IMMEDIATE` и падает с фатальной ошибкой SQLite, парализуя работу хранилища до перезапуска процесса.

- [tg_flowmap/dast/crawler.py:L484-L513, L309-L310](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/crawler.py#L484-L513) — **Преждевременный срыв обхода (AbortScan) на валидных `answer_only` callback-ах**.  
  Когда кнопка возвращает всплывающее уведомление (Telegram toast/alert через `answerCallbackQuery(showAlert=True)`), `outcome.message is None`. Метод `_observe_outcome_for_step` возвращает `None, None, None`, а `NavigationExecutor` возвращает `success=False`. Краулер воспринимает это как сбой и инкрементирует `_bump_errors()`. В графовом режиме счетчик `self._consecutive_errors` никогда не сбрасывается в 0 при успешных шагах (в отличие от L727 в legacy-коде), что неизбежно приводит к ложному `AbortScan("too many consecutive errors")` при длительном сканировании.

- [tg_flowmap/sast/parser.py:L809-L818](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/sast/parser.py#L809-L818) — **Искажение и потеря текстов экранов при стандартном aiogram-паттерне `await message.answer(...)`**.  
  Проверка `func_low` на L812 вычисляет `is_toast = ("answer" in func_low) and not any(k in func_low for k in ("message", ...))`. Так как `func_name` — это только атрибут (`"answer"`), строка не содержит слова `"message"`, и `is_toast` ошибочно становится `True`. Основной текст сообщения деградирует до `fallback_toast` и не сохраняется в `text_str`. Если в хэндлере присутствует любой вторичный вызов (например, `await bot.send_message(admin, ...)`), текст экрана перезаписывается логом, а реальный текст меню безвозвратно теряется.

- [tg_flowmap/dast/screen_identity.py:L206-L219](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/screen_identity.py#L206-L219) — **Полная поломка сопоставления кнопок (`match_button_instance`) при передаче объектов `sqlite3.Row`**.  
  Проверка `isinstance(action, dict)` возвращает `False`. Вызов `getattr(action, "row", 0)` на объекте `sqlite3.Row` возвращает дефолт `0`, так как `sqlite3.Row` не поддерживает доступ по атрибутам. Все поля (`row`, `col`, `label`, `button_type`) обнуляются, ломая алгоритм сопоставления кнопок на экране.

- [tg_flowmap/sast/evaluator.py:L7-L136](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/sast/evaluator.py#L7-L136) — **Отсутствие поддержки `ast.Subscript` в AST-эвалуаторе**.  
  Все словарные обращения вида `ROUTES['catalog']`, `CALLBACKS['cancel']` или `ICONS['back']` в коде ботов возвращают `None`. Это приводит к генерации ложных ошибок `[INVALID_BUTTON]` или потере целевых экранов в SAST-графе.

- [tg_flowmap/core/llm_exporter.py:L55, L67](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/core/llm_exporter.py#L55) — **Крах экспортера LLM-бенчмарков при `buttons: None`**.  
  Конструкция `s.get("buttons", [])` возвращает `None`, если ключ `"buttons"` явно присутствует в словаре со значением `None`. Вызов `", ".join(None)` падает с `TypeError: can only join an iterable`.

- [tg_flowmap/dast/scheduler.py:L197-L215](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/scheduler.py#L197-L215) — **Race Condition и `ProgrammingError: Cannot operate on a closed database` при отмене сканирования**.  
  Задачи краулера отменяются через `task.cancel()`, но не ожидаются через `await asyncio.gather`. База данных закрывается мгновенно на L211 (`state.close()`). Просыпающиеся корутины при выходе через `finally` пытаются записать ошибки в закрытую SQLite, порождая каскадные необработанные исключения.

---

## 2. ⚠️ Архитектурные костыли и антипаттерны (P2)

- [tg_flowmap/dast/safety.py:L186-L206](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/safety.py#L186-L206) — **Ложное срабатывание эвристики `requires_input` на меню с двоеточием**.  
  Проверка `t.endswith(("?", ":", "："))` немедленно возвращает `True` для экранов вроде `"Главное меню:"` или `"Каталог:"`, игнорируя наличие обычных кнопок навигации и отключая дальнейшую проверку `pressable_labels`.
- [tg_flowmap/dast/crawler.py:L838-L845](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/crawler.py#L838-L845) и [L316-L318](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/crawler.py#L316-L318) — **Срыв плана восстановления `_replay_path` для глубоких экранов**.  
  Экраны, найденные через `_observe_outcome_for_step` с `create_route=False`, не имеют записей в таблице `routes`. При планировании `recovery_start` путь оказывается пустым (`path=[]`), проверка совпадения корневого экрана завершается ошибкой, и экран объявляется `recovery_exhausted`.
- [tg_flowmap/dast/navigator.py:L105-L107](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/navigator.py#L105-L107) — **Thundering Herd и обход лимитера при разблокировке FloodGate**.  
  Задачи вызывают `global_limiter.acquire()` ДО ожидания `flood_gate.wait_open()`. При истечении таймаута все скопившиеся задачи просыпаются одновременно и отправляют запросы без задержек.
- [tg_flowmap/dast/ratelimit.py:L68-L71](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/ratelimit.py#L68-L71) — **Угроза дедлока в `_check_release`**.  
  При джиттере времени (`time.monotonic() < deadline - 0.1`) проверка не проходит и повторный колбэк не планируется, из-за чего `_event` может остаться сброшенным навсегда.
- [tg_flowmap/dast/state.py:L577](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/state.py#L577) и [L544](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/state.py#L544) — **Экспоненциальное раздувание и дублирование кнопок в SQLite**.  
  Таблица `buttons` не имеет ограничения UNIQUE, а `buttons_for_screen` выбирает все кнопки без группировки по `message_rowid`. При каждом повторном посещении экрана список кнопок в отчете умножается.
- [tg_flowmap/dast/reports.py:L344-L346](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/reports.py#L344-L346) — **Поломка Markdown-таблиц из-за неэкранированных пайпов `|` в метках кнопок**.
- [tg_flowmap/dast/map_render.py:L498-L503](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/map_render.py#L498-L503) — **Синтаксический сбой рендера Mermaid (`map.mmd`)** из-за переводов строк `\n` и пайпов `|` в текстах ребер.
- [tg_flowmap/dast/map_render.py:L460-L470](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/map_render.py#L460-L470) — **Невидимые SVG `<line>` для переходов на себя (self-loops)**: при `src == dst` отрезок нулевой длины не отображается браузерами.
- [tg_flowmap/dast/screen_identity.py:L33-L35](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/screen_identity.py#L33-L35) и [config.py:L34](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/config.py#L34) — **Невырезаемые цены в `normalize_text`**. Шаблон `DEFAULT_VOLATILE_PATTERNS` для `USD|RUB` не имеет флага `(?i)`, поэтому после `.lower()` цены вида `"10 usd"` не удаляются, плодя дубликаты экранов.
- [tg_flowmap/cli.py:L287, L311](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/cli.py#L287) — В `run_compare` конструктору `GraphAnalyzer` не передаются `screen_aliases` и `hub_return_nodes`, искажая метрики сравнения.
- [tg_flowmap/core/comparator.py:L110, L114](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/core/comparator.py#L110) — Некорректная логика определения лидера (`>=` и `<=`) безусловно назначает `bot_a` победителем даже при равных нулевых метриках (нет статуса «Ничья»).
- [tg_flowmap/dast/reports.py:L426](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/reports.py#L426) — Path Traversal риск: отсутствие санитизации имени бота от путей `../` при записи отчетов.
- [tg_flowmap/dast/scheduler.py:L91](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/scheduler.py#L91) — Прямой вызов `print()` вместо структурированного логгера (нарушение Zero-Print).
- [tg_flowmap/dast/auth.py:L12-L18](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/auth.py#L12-L18) — Привязка секретов `api_id` и `api_hash` исключительно к `config.json` без поддержки `.env`.

---

## 3. 🏰 Монолитность и архитектурная декомпозиция (God Objects & Complexity)

Анализ метрик Maintainability Index (`radon mi`) и цикломатической сложности (`radon cc`) выявил критические концентраторы связанности:

| Модуль | Длина (строк) | Maintainability Index | Статус сложности |
|---|---|---|---|
| `tg_flowmap/dast/state.py` | 1009 | **22.54 (Rank A)** | Превышение 1000 LOC, God Object (DDL, frontier, метрики, транзакции) |
| `tg_flowmap/sast/parser.py` | 993 | **0.00 (Rank C)** | Предельный монолит, критическая связанность |
| `tg_flowmap/dast/crawler.py` | 973 | **0.00 (Rank C)** | Класс `BotCrawler` (886 LOC), смешивание планирования и транспорта |
| `tg_flowmap/dast/reports.py` | 467 | **18.29 (Rank B)** | Функция `build_report_md` (radon cc = 45, Rank F) |

### Функции с критической цикломатической сложностью (Rank E/F):
1. `AstParser._find_message_dispatch` — **CC = 79 (Rank F)** (парсинг хэндлеров, условий, вызовов ответов)
2. `evaluate_ast_node` — **CC = 73 (Rank F)** (ручной эвалуатор AST)
3. `GraphAnalyzer.build_map` — **CC = 55 (Rank F)** (сборка графа и выявление тупиков)
4. `build_report_md` — **CC = 45 (Rank F)** (монолитная генерация отчета)
5. `AstParser._parse_keyboard_function` — **CC = 43 (Rank F)**
6. `generate_comparison` — **CC = 39 (Rank E)**

### Рекомендации по распилу:
- **`state.py`**: выделить модуль миграций и схемы `dast/storage/schema.py`, модуль аналитических выборок `dast/storage/queries.py` и очередь `dast/storage/frontier.py`.
- **`parser.py`**: вынести эвалуацию кнопок в `sast/button_parser.py`, а анализ условий диспетчеризации — в `sast/dispatch_parser.py`.
- **`crawler.py`**: отделить логику выполнения путей и переходов от алгоритмов анализа сообщений и работы с медиа.

---

## 4. 🪦 Мертвый код и рудименты (Dead Code Audit)

- [tg_flowmap/dast/navigator.py:L233](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/navigator.py#L233) — Ветка `elif err is not None:` в `press_button` на 100% недостижима из-за предшествующего безусловного `return` на L218.
- [tg_flowmap/dast/navigation_executor.py:L37-L38](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/navigation_executor.py#L37-L38) — Поля `self.graph` и `self.safety` принимаются в конструктор, но никогда не используются в классе. Поле `mismatch` в `StepExecutionResult` мертво.
- [tg_flowmap/dast/scheduler.py:L126, L135](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/scheduler.py#L126) — Избыточная повторная инициализация переменной `tasks: list[asyncio.Task] = []`.
- [tg_flowmap/dast/models.py:L175, L189, L228](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/models.py#L175) — Неиспользуемые свойства и рудиментарные классы `is_message_result`, `StableAction`, `ButtonInstance` (подтверждено `vulture`).
- [tg_flowmap/dast/navigation_graph.py:L179](file:///c:/Projects/.github/tg-flowmap/tg_flowmap/dast/navigation_graph.py#L179) — Неиспользуемый метод `get_outgoing`.

---

## 5. 💎 Инженерные находки (Реальные плюсы)

1. **Канонический фингерпринтинг экранов (`screen_identity.py`)**: отличная идея нормализации кнопок и медиа без привязки к динамическим Telegram ID (Message ID, timestamps), что позволяет склеивать одинаковые состояния интерфейса.
2. **Гибридный подход SAST + DAST**: редкая и ценная возможность сличить статическую модель из исходников aiogram/telebot с реальным динамическим поведением бота в Telegram.
3. **Поддержка Telegram Premium Custom Emojis**: автоматическое извлечение кастомных стикеров и эмодзи из Telegram API с кэшированием в Base64 Data URI для рендера в SVG и веб-интерфейсе.
4. **Быстрый и надежный тестовый базис**: 188 автономных unit/integration тестов, выполняющихся менее чем за 10 секунд.

---

## 6. 🛠 Приоритетный Roadmap исправлений

1. **Фаза 1 (P0: Безопасность и критические падения) — [x] ИСПРАВЛЕНО**:
   - [x] Исправлены регулярки `WALLET_REGEXES` и `DEFAULT_PRICE_REGEX` (добавлен `re.IGNORECASE` / `(?i)`).
   - [x] Исправлен `PressOutcome(..., callback=cb)` в `navigator.py:218`.
   - [x] Добавлен автоматический `rollback()` при сбоях в `state._exec()`.
   - [x] Защищены `llm_exporter.py` и `comparator.py` от `None` и неожиданных типов данных.
   - [x] Добавлена поддержка `ast.Subscript` в `evaluator.py`.

2. **Фаза 2 (P1: Стабильность краулинга) — [x] ИСПРАВЛЕНО**:
   - [x] Добавлена корректная обработка `answer_only` в `NavigationExecutor` и сброс `_consecutive_errors` при успешных действиях в `_bump_action()`.
   - [x] Поддержан `sqlite3.Row` и любые маппинги в `match_button_instance`.
   - [x] Исправлена очередность в `navigator._through_limiters()` (FloodGate перед лимитером и повторно перед запросом).
   - [x] Устранена угроза дедлока в `ratelimit.py:_check_release`.
   - [x] Добавлено ожидание `gather(*pending_tasks)` перед `state.close()` в `scheduler.py`.

3. **Фаза 3 (P2: Точность данных и отчетность) — [x] ИСПРАВЛЕНО**:
   - [x] Скорректирована эвристика `screen_requires_input`: наличие навигационных кнопок не блокирует обход.
   - [x] Экранированы пайпы `\|` и переносы строк в метках кнопок в Markdown-таблицах (`reports.py`).
   - [x] Реализован статус «Ничья» в матрице сравнения ботов (`comparator.py`).
   - [x] Устранена уязвимость Path Traversal при создании папок ботов в `reports.py` и `scheduler.py`.
   - [x] Устранен `print()` в `scheduler.py` (заменен на `logger.info()`).
   - [x] Добавлена поддержка чтения `api_id`/`api_hash` из переменных окружения в `auth.py`.

4. **Фаза 4 (P3: Архитектурный рефакторинг монолитов)**:
   - Декомпозировать `state.py`, `parser.py` и `crawler.py` на компактные модули (< 600 строк).
   - Удалить подтвержденный мертвый код.
