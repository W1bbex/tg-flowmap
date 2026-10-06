# Технический аудит и критика проекта tg-flowmap

> Дата: 2026-10-07 | Профиль: Open Source Library (C:\Projects\.github\tg-flowmap) | Статус: Верифицировано родителем (Anti-Hallucination Gate пройден)

---

## 1. 🚨 Критические дефекты и уязвимости (P0 / P1)

### 1.1. Пропуск метода `edit_text` при поиске ответа бота (`_find_message_dispatch`)
- **Файл**: [tg_flowmap/parser.py:749](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/parser.py#L749)
- **Механика сбоя**: В `AstParser._find_message_dispatch` перехват отправки сообщений реализован через подстрочную проверку:
  `if any(k in func_name.lower() for k in ("send_message", "edit_message", "sendphoto", "answer", "send_player_card")):`
  В aiogram 3 каноническим методом редактирования сообщения при нажатии на inline-кнопку является `await callback.message.edit_text(text, reply_markup=...)`. Имя функции здесь — `edit_text`. Строка `"edit_text"` не содержит `"send_message"`, `"edit_message"`, `"sendphoto"`, `"answer"`.
- **Доказательство в production**: Для любого стандартного aiogram 3 бота, использующего `message.edit_text()`, парсер не находит факт отправки сообщения. Экран создается с пустым текстом (`text_template = ""`) и потерянной клавиатурой (`inline_kb = None`), разрушая граф переходов.

### 1.2. Ложный `missing_back` на всех экранах с Reply-клавиатурами
- **Файл**: [tg_flowmap/analyzer.py:50-80](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/analyzer.py#L50-L80)
- **Механика сбоя**: Обычные текстовые кнопки Telegram (`KeyboardButton`) не имеют `callback_data`. На строке 50 условие `if not btn.callback_data:` перехватывает обработку кнопки, выполняет поиск цели и вызывает `continue` на строке 74. Выражение `has_back_button = True` (строки 77–79) находится ниже `continue` и для Reply-кнопок физически недостижимо.
- **Доказательство в production**:
  ```python
  nodes = {'cmd:/profile': MessageNode(id='cmd:/profile', title='Profile', keyboard=Keyboard(name='p_kb', keyboard_type='reply', rows=[[Button(text='« Назад')]]))};
  # analyzer.build_map() возвращает Issue(severity="warning", issue_type="missing_back")
  ```
  Каждый экран с Reply-клавиатурой (даже содержащий кнопку «« Назад») ложно помечается ошибкой отсутствия кнопки возврата, а в самом ребре графа жестко выставлено `is_back=False`.

### 1.3. Ложные тупики (False Dead-Ends) при разделении префиксов через подчеркивание `_`
- **Файл**: [tg_flowmap/analyzer.py:267-276](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/analyzer.py#L267-L276)
- **Механика сбоя**: Комментарий в коде заявляет `# Prefix splitting (colon or underscore)`, однако реальная имплементация проверяет исключительно `if ":" in cb:` и полностью игнорирует символ `_`.
- **Доказательство в production**:
  ```python
  nodes = {'cb:item': MessageNode(id='cb:item', title='Item')};
  analyzer._resolve_target('item_42') # Возвращает ('unresolved:item_42', 'dead_end')!
  ```
  В тысячах Telegram-ботов, использующих паттерны `item_<id>` или `user_<id>`, кнопки с динамическими ID не связываются с хэндлером `cb:item`, а помечаются критической ошибкой тупика (`dead_end`), генерируя лавину ложных тревог.

### 1.4. Схлопывание списков Python до последнего элемента в `evaluate_ast_node`
- **Файл**: [tg_flowmap/ast_evaluator.py:44-49](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/ast_evaluator.py#L44-L49)
- **Механика сбоя**: При вычислении переменной `evaluate_ast_node` выполняет:
  `if isinstance(val, list) and val: val = val[-1]`
  Авторы предполагали, что любой `list` в словаре переменных — это история присваиваний из `local_vars.setdefault(k, []).append(...)`. Если же в коде бота переменная была объявлена как обычный Python-список (`tabs = ["main", "settings"]`), `isinstance(val, list)` истинно, и извлекается только последний скалярный элемент `"settings"`.
- **Доказательство в production**: Любой генератор кнопок на основе списков категорий или вкладок при чтении переменной получает одно строковое значение вместо списка, разрушая генерацию клавиатур в цикле.

### 1.5. Искажение числовых типов `int(...)` и `float(...)` в строковые значения
- **Файл**: [tg_flowmap/ast_evaluator.py:83-86](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/ast_evaluator.py#L83-L86)
- **Механика сбоя**: При обработке встроенных функций:
  `if isinstance(node.func, ast.Name) and node.func.id in ("str", "int", "float") and node.args: return str(arg_val)`
  Вызовы `int(2)` или `float(1.5)` принудительно преобразуются в строку `str(arg_val)`.
- **Доказательство в production**: В `parser.py:742` метод билдера проверяет `if isinstance(adj_val, int) and adj_val > 0`. Из-за приведения к `str` проверка падает, и выравнивание сетки кнопок (`builder.adjust(int(N))`) игнорируется.

### 1.6. Фронтенд-крэш `TypeError: Cannot read properties of undefined (reading 'toLowerCase')`
- **Файл**: [tg_flowmap/templates/viewer.js:789, 833, 1355](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/templates/viewer.js#L789)
- **Механика сбоя**: Вызов `btn.text.toLowerCase()` и `node.title.toLowerCase()` выполняется напрямую без проверки `btn.text` на `null` или `undefined`:
  `const tLow = btn.text.toLowerCase();`
- **Доказательство в production**: Если в анализируемом боте у кнопки отсутствует текст (например, кнопка-картинка или динамический плейсхолдер), цикл `createCard` падает с необработанным исключением JavaScript при загрузке страницы. Отрисовка канваса полностью прекращается, оставляя белый экран. Аналогичный крэш происходит при первом нажатии клавиши в строке поиска (`#search-input`).

### 1.7. Ослепление CI/CD пайплайнов в режиме `--strict`
- **Файл**: [tg_flowmap/cli.py:136-140](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/cli.py#L136-L140)
- **Механика сбоя**: В режиме `--strict` проверка статуса опирается только на два счетчика:
  `if strict and (dead_ends > 0 or broken_emojis > 0): return 1`
  При этом анализатор выставляет `severity="error"` для дефектов `callback_too_long` (>64 байт, гарантированно валит Telegram Bot API) и `invalid_button`.
- **Доказательство в production**: Бот с невалидными кнопками или коллбеками длиной 80 байт проходит проверку `tg-flowmap --strict` с кодом возврата `0` (Success), пропуская фатальный баг в продакшн.

### 1.8. Утечка токена бота в stderr и зависание на эмодзи
- **Файл**: [tg_flowmap/emoji_fetcher.py:69-73, 81, 138-140](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/emoji_fetcher.py#L138-L140)
- **Механика сбоя**: 
  1. `batch = list(missing_ids)[:100]` не содержит цикла пагинации — любые эмодзи сверх первой сотни безвозвратно теряются.
  2. При возникновении сетевой ошибки `urllib.error.HTTPError` в stderr выводится сырой объект исключения `e`. Поле `e.url` содержит полный путь вида `https://api.telegram.org/bot<TOKEN>/...`, компрометируя приватный токен в логах CI/CD.
  3. Все запросы на скачивание выполняются синхронно и последовательно в цикле на главном потоке (до 200+ сетевых обращений).

### 1.9. Сброс камеры в (0,0) и сбой зума HUD
- **Файл**: [tg_flowmap/templates/viewer.js:145-159](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/templates/viewer.js#L145-L159)
- **Механика сбоя**: 
  1. `centerOnStart` ищет жестко заданные ключи `"cmd:/start"` и `"cb:menu"`. Если у бота точка входа — `/help` или `/login`, камера центрируется на координаты `{ x: 0, y: 0 }`, уводя канвас в пустоту.
  2. Кнопки `btn-zoom-in` / `btn-zoom-out` изменяют `scale`, но не корректируют `panX` / `panY` относительно центра экрана (в отличие от колеса мыши). В результате каждый клик по зуму сдвигает схему по диагонали к краю экрана.

### 1.10. Уязвимость Stored DOM XSS в визуализаторе
- **Файлы**: [tg_flowmap/templates/viewer.js:683-690, 795](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/templates/viewer.js#L683-L690), [tg_flowmap/visualizer.py:28-30](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/visualizer.py#L28-L30)
- **Механика сбоя**: Заголовки карточек (`displayTitle`), имена исходных файлов (`srcName`), тексты кнопок (`btn.text`) и шаблоны сообщений подставляются напрямую через `innerHTML` без экранирования спецсимволов HTML (`<`, `>`, `&`). Кроме того, замена `/* __SCRIPTS__ */` после подстановки `__DATA_JSON__` ломает файл при совпадении подстроки.

---

## 2. ⚠️ Архитектурные костыли и антипаттерны (P2)

### 2.1. Утечка чужих текстов PC Control Agent в универсальную open-source библиотеку
- **Файлы**: [tg_flowmap/parser.py:587-613](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/parser.py#L587-L613), [tg_flowmap/templates/viewer.js:834-836](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/templates/viewer.js#L834-L836)
- **Проблема**: В парсере универсального инструмента жестко зашиты русскоязычные тексты управления ПК:
  - `sound` / `volume` ➔ *"🔊 Управление звуком"*
  - `led` ➔ *"💡 Подсветка (ARGB)"*
  - `power` ➔ *"⚡ Управление питанием"*
  - `reboot` ➔ *"🔄 Перезагрузка ПК"*
  - `shutdown` ➔ *"🛑 Выключение ПК"*
  - `workspace` ➔ *"🚀 Рабочий сетап (VPN)"*
  - `physical` ➔ *"🕹 Физическая кнопка"*
  В `viewer.js` аналогично захардкожены цвета кнопок под `"питание"`, `"разблокировать"`, `"скриншот"`.
- **Последствия**: При анализе любого стороннего бота (например, интернет-магазина или игрового бота с кнопкой `power`) инструмент галлюцинирует текстами перезагрузки ПК и подсветки ARGB.

### 2.2. Преждевременная popup-классификация, отбирающая клавиатуры
- **Файл**: [tg_flowmap/parser.py:644-647](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/parser.py#L644-L647)
- **Проблема**: `elif any(k in node_id.lower() for k in ("cancel", "retry", "noop", "close")):` срабатывает до проверки `elif node.keyboard`.
- **Последствия**: Любой экран с подтверждением отмены действия (например, `cb:cancel_order` с кнопками «Да»/«Нет») насильно помечается как `node_type = "popup"` со сбросом семантики экрана.

### 2.3. Квадратичный цикл $O(N^2)$ и ложные предупреждения `duplicate_screen`
- **Файл**: [tg_flowmap/analyzer.py:152-174](file:///C:/Projects/.github/tg-flowmap/tg_flowmap/analyzer.py#L152-L174)
- **Проблема**: Анализатор проверяет все пары узлов двойным циклом `for id1 in nodes: for id2 in nodes:`. Если у двух экранов совпадает имя клавиатуры (`n1.keyboard.name == n2.keyboard.name`), выставляется ворнинг о дубликате.
- **Последствия**: Использование общих модульных клавиатур (`back_kb`, `cancel_markup`) на 10 экранах порождает 45 ложных предупреждений.

### 2.4. Двойной полный парсинг кодовой базы в `run.py`
- **Файл**: [run.py:104-108, 132](file:///C:/Projects/.github/tg-flowmap/run.py#L104-L132)
- **Проблема**: `run.py` целиком парсит проект через `parser_probe` только для проверки наличия кастомных эмодзи, после чего `run_analysis()` парсит этот же проект с нуля.

---

## 3. 🏰 Монолитность и архитектурная декомпозиция (God Objects & Complexity)

### Метрики сложности (Radon MI & CC):
- `tg_flowmap/parser.py`: **Maintainability Index = 0.00 (Rank C, критический монолит)**
  - `AstParser._find_message_dispatch`: **CC = 65 (Rank F)**
  - `AstParser._parse_keyboard_function`: **CC = 43 (Rank F)**
  - `AstParser._parse_keyboard_expr`: **CC = 42 (Rank F)**
  - `AstParser._parse_button_element`: **CC = 37 (Rank E)**
  - `AstParser._add_node`: **CC = 32 (Rank E)**
- `tg_flowmap/ast_evaluator.py`:
  - `evaluate_ast_node`: **CC = 53 (Rank F)**
- `tg_flowmap/analyzer.py`:
  - `GraphAnalyzer.build_map`: **CC = 49 (Rank F)**
  - `GraphAnalyzer._resolve_target`: **CC = 22 (Rank D)**
- `tg_flowmap/templates/viewer.js`: **1519 строк в одном файле** с плотной смесью математики DAG-раскладки, рендеринга SVG-кривых, DOM-манипуляций и обработчиков событий.

### Рекомендации по декомпозиции:
1. **Вынести из `parser.py` логику билдеров**: Классы `AiogramBuilderTracker` и `TelebotMarkupExtractor` должны быть изолированы от главного AST-визитора.
2. **Изолировать эвристики генерации текстов**: Заменить захардкоженные словари текстов на подключаемые генераторы заглушек без привязки к конкретным доменам.
3. **Разбить `viewer.js` на модули**:
   - `dag_layout.js` — топологическая сортировка и расчет координат (X, Y).
   - `connector_renderer.js` — расчет кубических кривых Безье и стрелок.
   - `canvas_interactions.js` — панорамирование, зум, перетаскивание карточек.

---

## 4. 🪦 Мертвый код и рудименты (Dead Code Audit)

- **Сканирование Vulture (порог 60–70%)**: 0 подтвержденных синтаксически мертвых функций (кодовая база очищена от неиспользуемых определений).
- **Неиспользуемый импорт**: В `tg_flowmap/parser.py:10` импортируется `evaluate_ast_node`, но в теле модуля используется только псевдоним `_ast_to_value`.
- **Мертвое поле модели**: Поле `popup_text: Optional[str] = None` в `MessageNode` нигде в парсере не заполняется.
- **Дублирование логики распаковки билдеров**: В `parser.py:775-784` и `807-816` скопирован идентичный 10-строчный блок извлечения `as_markup`.

---

## 5. 💎 Инженерные находки (Реальные плюсы)

1. **Автономность нулевого рантайма**: Парсинг структуры Telegram-ботов выполняется на чистом AST без импорта зависимостей бота, запуска Python-рантайма или потребности в реальном токене.
2. **Тестирование лимитов производительности**: Наличие теста `test_pipeline_performance_and_memory_budget`, фиксирующего пороги по времени (<2.0s) и памяти (<40MB) при анализе графов из десятков модулей.
3. **Безопасная упаковка JSON в HTML**: Корректная подмена `</` на `<\\/` в `visualizer.py` эффективно блокирует закрытие тега `<script>` браузерным парсером.
4. **Интерактивный DAG-канвас**: Качественная визуализация переходов с подсветкой обратных путей и динамическими стрелками при наведении на кнопки.

---

## 6. 🛠 Приоритетный Roadmap исправлений

1. **[P0] Поддержка `edit_text`**: Добавить `"edit_text"` в фильтр методов в `parser.py:749`.
2. **[P0] Защита от Null в JS**: Добавить `(btn.text || "")` перед `.toLowerCase()` в `viewer.js` (строки 789, 833, 1355).
3. **[P0] Исправление Reply-кнопок в анализаторе**: Вынести вычисление `has_back_button` до `continue` для `KeyboardButton` в `analyzer.py:50-80`.
4. **[P0] Поддержка префиксов с подчеркиванием**: Реализовать сплит по `_` в `analyzer.py:268` для корректного связывания `item_42` с `cb:item`.
5. **[P0] Коррекция списков в `ast_evaluator`**: Разграничить служебные списки истории AST от литералов Python-списков в коде бота.
6. **[P1] Очистка от чужого хардкода**: Удалить тексты «Управление звуком», «Перезагрузка ПК» из `parser.py:587-613`.
7. **[P1] Исправление режима `--strict`**: Проверять `any(i.severity == "error" for i in bot_map.issues)` в `cli.py:138`.
8. **[P1] Центрирование камеры и зум**: Использовать динамический `rootId` вместо хардкода `/start` и компенсировать координаты при зуме HUD.
9. **[P2] Декомпозиция монолита `parser.py`**: Снизить цикломатическую сложность функций с ранга F до A/B.
