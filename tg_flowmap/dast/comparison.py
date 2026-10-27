"""comparison.md — сравнительный анализ всех обойдённых ботов (эвристики).

Анализ честно помечен как эвристический: выводы строятся по ключевым словам,
regex цен, статистике переходов и заблокированным кнопкам.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from .config import Config
from .reports import _find_prices, _screen_texts
from .state import State

SECTION_SYNONYMS = {
    "каталог": "Каталог/товары", "catalog": "Каталог/товары", "shop": "Каталог/товары",
    "магазин": "Каталог/товары", "товары": "Каталог/товары", "products": "Каталог/товары",
    "профиль": "Профиль", "profile": "Профиль", "кабинет": "Профиль", "my account": "Профиль",
    "поддержка": "Поддержка", "support": "Поддержка", "help": "Поддержка", "помощь": "Поддержка",
    "корзина": "Корзина", "cart": "Корзина", "checkout": "Оформление заказа",
    "отзывы": "Отзывы", "reviews": "Отзывы", "rules": "Правила", "правила": "Правила",
    "баланс": "Баланс/кошелёк", "balance": "Баланс/кошелёк", "wallet": "Баланс/кошелёк",
    "пополнить": "Баланс/кошелёк", "FAQ": "FAQ", "faq": "FAQ", "инфо": "Инфо", "about": "Инфо",
}
NO_STOCK_PHRASES = ["нет в наличии", "out of stock", "закончились", "распродано",
                    "недоступен", "not available", "sold out"]
PRODUCT_WORDS = ("аккаунт", "account", "карта", "card", "gift", "ключ", "key", "товар")


def _classify_section(label: str) -> str | None:
    l = (label or "").strip().lower()
    for key, section in SECTION_SYNONYMS.items():
        if key in l:
            return section
    return None


def collect_bot_stats(cfg: Config, state: State, bot: str) -> dict:
    price_re = cfg.compiled_price()
    screens = state.screens_all(bot)
    transitions = state.transitions_all(bot)
    buttons = state.buttons_all(bot)
    texts = _screen_texts(state, bot)
    result_counts = Counter(t["result_type"] or "?" for t in transitions)
    blocked = Counter(
        (b["blocked_reason"] or "").split(":")[0]
        for b in buttons if b["blocked_reason"])

    # разделы главного меню (кнопки корневых экранов)
    root_ids = {s["screen_id"] for s in screens if s["depth_min"] == 0}
    root_sections: list[str] = []
    for b in buttons:
        if b["screen_id"] in root_ids:
            root_sections.append(b["label"])

    # сколько экранов похожи на карточку товара (цена + слово-товар + медиа)
    product_screens = 0
    photo_product_screens = 0
    price_examples: list[str] = []
    no_stock_hits = 0
    checkout_zone_screens: list[str] = []

    # Предзагрузка медиа и группировка кнопок для исключения N+1 и O(S*B)
    screens_with_media = {
        row["screen_id"]
        for row in state._query(
            "SELECT DISTINCT msg.screen_id FROM media m JOIN messages msg ON msg.id=m.message_rowid WHERE msg.bot=?",
            (bot,),
        )
    }
    buttons_by_screen: dict[str, list[dict]] = {}
    for b in buttons:
        buttons_by_screen.setdefault(b["screen_id"], []).append(b)

    for s in screens:
        sid = s["screen_id"]
        text = (texts.get(sid) or "").lower()
        prices = _find_prices(texts.get(sid) or "", price_re)
        if prices:
            price_examples.extend(prices[:3])
        is_product = bool(prices) and any(w in text for w in PRODUCT_WORDS)
        has_media = sid in screens_with_media
        if is_product:
            product_screens += 1
            if has_media:
                photo_product_screens += 1
        if any(p in text for p in NO_STOCK_PHRASES):
            no_stock_hits += 1
        s_btns = buttons_by_screen.get(sid, [])
        if any((b["blocked_reason"] or "").startswith(("checkout", "payment", "price_with")) for b in s_btns):
            checkout_zone_screens.append(sid)

    catalog_depth = max((s["depth_min"] for s in screens), default=0)
    timeouts = result_counts.get("timeout", 0) + result_counts.get("error", 0)
    metrics = state.metrics_all(bot)
    return {
        "bot": bot,
        "screens": len(screens),
        "transitions": len(transitions),
        "buttons": len(buttons),
        "blocked_buttons": sum(1 for b in buttons if b["blocked_reason"]),
        "blocked_reasons": dict(blocked),
        "result_counts": dict(result_counts),
        "root_sections": root_sections,
        "product_screens": product_screens,
        "photo_product_screens": photo_product_screens,
        "price_examples": price_examples[:10],
        "no_stock_hits": no_stock_hits,
        "checkout_zone_screens": checkout_zone_screens,
        "max_depth": catalog_depth,
        "timeouts_errors": timeouts,
        "metrics": metrics,
    }


def generate_comparison(cfg: Config, state: State, bots: list[str]) -> Path:
    stats = [collect_bot_stats(cfg, state, b) for b in bots]
    stats = [s for s in stats if s["screens"] > 0]
    lines: list[str] = []
    lines.append("# Сравнение ботов (эвристический анализ)")
    lines.append("")
    lines.append("> Выводы построены на ключевых словах, regex цен, статистике "
                 "переходов и заблокированным кнопкам — это эвристики, не гарантии.")
    lines.append("")
    if not stats:
        lines.append("Нет данных: сначала выполните обход.")
        path = cfg.output_dir / "comparison.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # сводная таблица
    lines.append("## Факты (собранные данные)")
    lines.append("")
    lines.append("| Бот | Экранов | Кнопок | Заблок. | Карточек товара | "
                 "С фото | Макс. глубина | Таймауты/ошибки |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for s in stats:
        lines.append(
            f"| {s['bot']} | {s['screens']} | {s['buttons']} | {s['blocked_buttons']} "
            f"| {s['product_screens']} | {s['photo_product_screens']} "
            f"| {s['max_depth']} | {s['timeouts_errors']} |")
    lines.append("")

    # Эффективность Graph-First планировщика
    lines.append("## Эффективность Graph-First планировщика")
    lines.append("")
    lines.append("| Бот | Действий | /start | Recovery /start | Локальных возвратов | Предотвращено replay | Сэкономлено действий |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in stats:
        m = s.get("metrics", {})
        act = m.get("telegram_actions", s["transitions"])
        st = m.get("start_count", 1)
        rst = m.get("recovery_start_count", 0)
        lr = m.get("successful_local_returns", 0)
        av = m.get("avoided_replays", 0)
        sav = m.get("estimated_actions_saved", 0)
        lines.append(f"| {s['bot']} | {act} | {st} | {rst} | {lr} | {av} | ~{sav} |")
    lines.append("")

    # частые разделы
    section_counter: Counter = Counter()
    for s in stats:
        for label in s["root_sections"]:
            section = _classify_section(label)
            if section:
                section_counter[section] += 1
    lines.append("## Часто встречающиеся разделы главного меню")
    lines.append("")
    if section_counter:
        total = len(stats)
        for section, cnt in section_counter.most_common():
            lines.append(f"- **{section}** — у {cnt} из {total} ботов")
    else:
        lines.append("- Разделы не распознаны по словарю (см. отчёты по ботам)")
    lines.append("")

    # структура каталога
    lines.append("## Типовая структура каталога (эвристика по глубине)")
    lines.append("")
    for s in stats:
        edit = s["result_counts"].get("edit", 0)
        new = s["result_counts"].get("new", 0)
        total_msg = edit + new
        edit_share = (edit / total_msg * 100) if total_msg else 0
        lines.append(
            f"- **{s['bot']}**: глубина до {s['max_depth']}, карточек товара "
            f"~{s['product_screens']} (с фото {s['photo_product_screens']}); "
            f"edit_message {edit_share:.0f}% vs новые сообщения {100 - edit_share:.0f}%")
    lines.append("")

    # карточки товара и цены
    lines.append("## Оформление карточек товара и цены")
    lines.append("")
    for s in stats:
        prices = ", ".join(s["price_examples"][:6]) if s["price_examples"] else "не найдены"
        lines.append(
            f"- **{s['bot']}**: примеры цен: {prices}; экранов с «нет в наличии»: "
            f"{s['no_stock_hits']}")
    lines.append("")

    # checkout
    lines.append("## Зона checkout")
    lines.append("")
    lines.append("Кнопки покупки/оплаты не нажимались (политика безопасности) — "
                 "зона checkout определена по заблокированным кнопкам:")
    lines.append("")
    any_checkout = False
    for s in stats:
        reasons = {k: v for k, v in s["blocked_reasons"].items()
                   if k in ("danger_word", "price_with_action_word", "checkout_screen",
                            "payment_screen")}
        if reasons or s["checkout_zone_screens"]:
            any_checkout = True
            lines.append(
                f"- **{s['bot']}**: экранов в зоне оплаты ~{len(s['checkout_zone_screens'])}; "
                f"заблокировано: {reasons or 'есть'}")
    if not any_checkout:
        lines.append("- Явных признаков checkout не встретилось (либо каталог "
                     "защищён вводом)")
    lines.append("")

    # edit vs new
    lines.append("## edit_message против новых сообщений")
    lines.append("")
    for s in stats:
        rc = s["result_counts"]
        lines.append(
            f"- **{s['bot']}**: edit={rc.get('edit', 0)}, new={rc.get('new', 0)}, "
            f"answer_only (callback без смены экрана)={rc.get('answer_only', 0)}, "
            f"timeout={rc.get('timeout', 0)}, error={rc.get('error', 0)}")
    lines.append("")

    # лучшие/худшие
    lines.append("## Наблюдения (эвристики)")
    lines.append("")
    ranked = sorted(stats, key=lambda s: (-s["screens"], s["timeouts_errors"]))
    if ranked:
        best = ranked[0]
        lines.append(
            f"- Самый подробный интерфейс: **{best['bot']}** "
            f"({best['screens']} экранов, {best['buttons']} кнопок)")
    broken = [s for s in stats if s["timeouts_errors"] > 0]
    if broken:
        lines.append("- Возможные проблемы (таймауты/ошибки): "
                     + ", ".join(f"{s['bot']} ({s['timeouts_errors']})" for s in broken))
    photo_users = [s["bot"] for s in stats if s["photo_product_screens"] > 0]
    if photo_users:
        lines.append("- Фото в карточках товара используют: " + ", ".join(photo_users))
    lines.append("")

    # рекомендация
    lines.append("## Рекомендации (шаблон — не факты, проверяйте по report.md)")
    lines.append("")
    use_edit = any(
        (s["result_counts"].get("edit", 0) >= s["result_counts"].get("new", 0))
        for s in stats)
    # иерархия каталога — только если данные её действительно показывают
    hierarchy_seen = any(s["max_depth"] >= 2 and s["product_screens"] > 0
                         for s in stats)
    catalog_line = (
        "Каталог: у обойдённых ботов встречается иерархия уровней "
        "(категории → подкатегории → карточка товара) — судя по глубине и "
        "карточкам в данных."
        if hierarchy_seen else
        "Каталог: иерархия глубже 2 уровней НЕ подтверждена собранными "
        "данными; безопасный старт — плоский список разделов с карточками.")
    lines.append("1. Главное меню: " + (
        ", ".join(f"{sec}" for sec, _ in section_counter.most_common(6))
        if section_counter else "Каталог, Профиль, Поддержка") + ".")
    lines.append(f"2. {catalog_line} "
                 "В карточке: фото + название + цена + кнопки «В корзину»/«Назад».")
    lines.append("3. Навигация: " + (
        "переключение экранов через edit_message — не плодит ленту сообщений"
        if use_edit else
        "новые сообщения на каждый экран (проще для пользователя вернуться назад), "
        "но лучше комбинировать с edit"))
    lines.append("4. Кнопка «Назад» на каждом экране каталога; возврат в главное "
                 "меню не глубже 2 нажатий.")
    lines.append("5. Отсутствие товара показывать прямо в карточке "
                 "(«нет в наличии» + скрыть кнопку покупки), не отдельным тупиком.")
    lines.append("")
    lines.append("_Сформировано автоматически; проверьте выводы по report.md каждого бота._")

    path = cfg.output_dir / "comparison.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
