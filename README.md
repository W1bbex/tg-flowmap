# 🧭 tg-flowmap

> **Unified Telegram Bot Analysis & Benchmarking Suite: Static Code AST (SAST) + Dynamic Userbot Crawler (DAST) + AI UX Benchmarking.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-brightgreen.svg)]()
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)]()
[![Tests: 205 passed](https://img.shields.io/badge/tests-205%20passed-brightgreen.svg)]()

`tg-flowmap` — комплексный инженерный инструмент для аудита, визуализации и сравнения Telegram-ботов:
1. **SAST (Static AST)**: сканирует исходный код вашего бота **без запуска**, находит тупики, битые коллбеки и нарушения спецификации Telegram Bot API за 50 мс без единой зависимости.
2. **DAST (Telethon Crawler)**: аккуратно обходит интерфейс **чужого бота-конкурента** юзерботом по графу Дейкстры (без лишних `/start` и с защитой от бана).
3. **AI UX Benchmarker**: сопоставляет вашего бота с ботом оппонента и формирует готовый промпт для ChatGPT / Claude (*«Сравни моего бота с конкурентом и дай 5 жестких UX-советов по воронке продаж»*).

---

## ⚡ Быстрый старт (Zero-Boilerplate)

Никаких сложных флагов. Все отчёты и данные автоматически сохраняются в `output/`.

### 1. Установка

```bash
# Базовый легковесный режим (SAST, 0 зависимостей):
pip install tg-flowmap

# Полный фарш (с Telethon для обхода конкурентов):
pip install "tg-flowmap[dast]"
```

### 2. Анализ своего бота (SAST)

```bash
tg-flowmap sast path/to/my_bot
```
> Выводит аудит в консоль и автоматически сохраняет Markdown-отчёт: `output/my_bot_report.md`.  
> *Хотите интерактивный холст? Просто добавьте флаг `--html`.*

### 3. Исследование чужого бота (DAST)

```bash
tg-flowmap dast @competitor_bot
```
> Обходит интерфейс конкурента, сохраняет структуру меню, карточки и отчёт в `output/@competitor_bot/`.

### 4. Ультимативное сравнение с конкурентом (AI Benchmark)

```bash
tg-flowmap compare path/to/my_bot @competitor_bot
```
> Генерирует сравнительную матрицу `output/comparison.md` и готовый к отправке в ИИ файл **`output/llm_prompt.md`**!

### 💡 Быстрый интерактивный запуск на Windows (1-Click)

Дважды кликните **`run.bat`** (или перетащите файл/папку бота прямо на иконку `run.bat`):
- Откроется понятное меню с выбором режима.
- Пункт `[4]` сразу же строит карту для встроенного демо-бота `examples/sample_bot.py` и открывает её в браузере.

---

## 📊 Пример терминального вывода (SAST)

```text
============================================================
  🧭 TG-FLOWMAP — Telegram Bot Analyzer (SAST)
============================================================
Цель:              C:\Projects\my_shop_bot
Всего экранов:     54
Всего связей:      35
Клавиатур найдено: 31
Тупиков (Dead-end):0
Ошибок эмодзи:     0
Без кнопки Назад:  2
------------------------------------------------------------

🔍 НАЙДЕННЫЕ ДЕФЕКТЫ И ПРЕДУПРЕЖДЕНИЯ:
  1. ⚠️ [MISSING_BACK] В экране 'catalog:filter' нет кнопки возврата (« Назад / В меню »).
  2. ℹ️ [DANGLING_HANDLER] Обработчик 'admin_dump' определён в коде, но ни одна кнопка на него не ссылается.

📄 Отчёт сохранён: output/my_shop_bot_report.md
📦 JSON-структура сохранена: output/my_shop_bot_data.json
```

---

## 🤖 Пример сгенерированного AI-промпта (`llm_prompt.md`)

```markdown
# Telegram Bot UX Benchmark: my_bot vs @competitor_bot

| Метрика | my_bot (Мой бот) | @competitor_bot (Конкурент) |
|---|---|---|
| Всего экранов | 14 | 32 |
| Всего кнопок | 28 | 64 |
| Тупиковые кнопки | 0 | 0 |
| Экраны без кнопки «Назад» | 0 | 2 |

[Структура экранов и кнопок обоих ботов...]

### Запрос для нейросети:
"Ты — ведущий UX/CPO архитектор Telegram-ботов. На основе структуры выше проведи
глубокий аудит: где мой бот проигрывает конкуренту по скорости оформления заказа
и какие 5 конкретных правок меню поднимут конверсию?"
```

---

## 🛠️ Архитектура модулей

- `tg_flowmap/core/`: единая модель графа (`BotMap`), движок сравнения (`comparator.py`) и генератор промптов (`llm_exporter.py`).
- `tg_flowmap/sast/`: статический двухпроходный AST-парсер, вычисление выражений без `eval()`, линтер Bot API.
- `tg_flowmap/dast/`: Telethon-краулер, навигация по Дейкстре, фильтр безопасности `safety.py`, SQLite state.
- `tg_flowmap/visualizer/`: компилятор автономных HTML5/SVG интерактивных карт (ForceAtlas2, ClearType DirectWrite).
- `tg_flowmap/cli.py`: единый CLI-интерфейс с поддержкой команд `sast`, `dast`, `compare`.

---

## 🧪 Тестирование

```bash
pytest tests -v
```
**182 passing tests** (36 SAST + 146 DAST) с полным контролем бюджета памяти и производительности.
