from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def _format_screen_buttons(raw_buttons: Any) -> str:
    if not raw_buttons or not isinstance(raw_buttons, (list, tuple)):
        return "нет кнопок"
    formatted = []
    for b in raw_buttons:
        if isinstance(b, str):
            formatted.append(b)
        elif isinstance(b, dict):
            formatted.append(str(b.get("label") or b.get("text") or "кнопка"))
        else:
            formatted.append(str(getattr(b, "label", getattr(b, "text", "кнопка"))))
    return ", ".join(formatted) or "нет кнопок"


def generate_llm_benchmark_prompt(
    bot_a_name: str,
    bot_a_metrics: Dict[str, Any],
    bot_b_name: str,
    bot_b_metrics: Dict[str, Any],
    bot_a_screens: Optional[list] = None,
    bot_b_screens: Optional[list] = None,
) -> str:
    """
    Generates a prompt-ready markdown string tailored for LLMs (Claude, ChatGPT, Gemini)
    to perform a rigorous, actionable UX and conversion-rate optimization (CRO) benchmark.
    """
    a_screens_count = bot_a_metrics.get("screens_count", 0)
    b_screens_count = bot_b_metrics.get("screens_count", 0)
    a_buttons_count = bot_a_metrics.get("buttons_count", 0)
    b_buttons_count = bot_b_metrics.get("buttons_count", 0)
    a_dead_ends = bot_a_metrics.get("dead_ends", 0)
    b_dead_ends = bot_b_metrics.get("dead_ends", 0)
    a_missing_back = bot_a_metrics.get("missing_back", 0)
    b_missing_back = bot_b_metrics.get("missing_back", 0)
    a_max_depth = bot_a_metrics.get("max_depth", "N/A")
    b_max_depth = bot_b_metrics.get("max_depth", "N/A")

    lines = [
        f"# 🤖 Telegram Bot UX Benchmark: {bot_a_name} vs {bot_b_name}",
        "",
        "> Автоматически сгенерировано [tg-flowmap](https://github.com/w1bbex/tg-flowmap).",
        "> Скопируйте текст ниже и отправьте в Claude, ChatGPT или Gemini для глубокого продуктового аудита.",
        "",
        "---",
        "",
        "## 📋 Сводная таблица метрик интерфейса",
        "",
        f"| Метрика | {bot_a_name} (Мой бот) | {bot_b_name} (Конкурент / Оппонент) |",
        "|---|---|---|",
        f"| **Всего экранов** | {a_screens_count} | {b_screens_count} |",
        f"| **Всего кнопок / действий** | {a_buttons_count} | {b_buttons_count} |",
        f"| **Макс. глубина навигации** | {a_max_depth} | {b_max_depth} |",
        f"| **Тупиковые кнопки (Dead-ends)** | {a_dead_ends} | {b_dead_ends} |",
        f"| **Экраны без кнопки возврата («Назад»)** | {a_missing_back} | {b_missing_back} |",
        "",
    ]

    if bot_a_screens:
        lines.append(f"### 🗺️ Структура экранов: {bot_a_name}")
        lines.append("```text")
        for s in bot_a_screens[:30]:
            name = s.get("title") or s.get("screen_id") or "screen"
            btns = _format_screen_buttons(s.get("buttons"))
            lines.append(f"- [{name}]: кнопки -> [{btns}]")
        if len(bot_a_screens) > 30:
            lines.append(f"... и ещё {len(bot_a_screens) - 30} экранов")
        lines.append("```")
        lines.append("")

    if bot_b_screens:
        lines.append(f"### 🗺️ Структура экранов: {bot_b_name}")
        lines.append("```text")
        for s in bot_b_screens[:30]:
            name = s.get("title") or s.get("screen_id") or "screen"
            btns = _format_screen_buttons(s.get("buttons"))
            lines.append(f"- [{name}]: кнопки -> [{btns}]")
        if len(bot_b_screens) > 30:
            lines.append(f"... и ещё {len(bot_b_screens) - 30} экранов")
        lines.append("```")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 🎯 Задача для ИИ (Промпт)",
        "",
        "```markdown",
        "Ты — ведущий UX/CPO архитектор Telegram-ботов и эксперт по продуктовой конверсии.",
        f"Перед тобой реальный срез двух Telegram-ботов: Мой бот ({bot_a_name}) и Бот конкурента ({bot_b_name}).",
        "",
        "На основе представленной структуры и метрик проведи беспощадный, аргументированный аудит:",
        f"1. **Анализ воронки и путей пользователя (Customer Journey Map)**: где мой бот ({bot_a_name}) перегружен лишними кликами по сравнению с конкурентом?",
        "2. **Тупики и точки оттока (Drop-off points)**: на каких шагах пользователь с наибольшей вероятностью бросит диалог с ботом?",
        "3. **Психология кнопок и CTA**: какие формулировки или расположение кнопок у конкурента работают эффективнее?",
        "4. **Топ-5 конкретных изменений в меню**: что конкретно переделать в архитектуре моего бота уже сегодня, чтобы превзойти оппонента по удобству и скорости целевого действия (покупка/заказ)?",
        "```",
        "",
    ])

    return "\n".join(lines)
