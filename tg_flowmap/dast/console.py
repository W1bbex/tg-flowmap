"""Консольный интерфейс: меню 1–7 + выход."""

from __future__ import annotations

import asyncio

from .comparison import generate_comparison
from .config import Config, load_config, normalize_bot_username, save_config
from .reports import generate_reports
from .scheduler import run_scan
from .state import State

MENU = """
==============================
 Telegram Bot Explorer
==============================
 1. Add bot
 2. List bots
 3. Start scan
 4. Resume scan
 5. Generate reports
 6. Show errors
 7. Reset scan for selected bot
 0. Exit
"""


def _pick_bot(cfg: Config, state: State, prompt: str) -> str | None:
    bots = cfg.bots or [b["username"] for b in state.list_bots()]
    if not bots:
        print("Список ботов пуст. Сначала добавьте бота (пункт 1).")
        return None
    if len(bots) == 1:
        return bots[0]
    print("Боты:")
    for i, b in enumerate(bots, 1):
        print(f"  {i}. {b}")
    try:
        n = int(input(f"{prompt} (номер): ").strip())
        return bots[n - 1] if 1 <= n <= len(bots) else None
    except ValueError:
        return None


def _scan(cfg: Config, bots: list[str], resume: bool) -> None:
    if not bots:
        print("Нет ботов для обхода.")
        return
    print(f"Обход: {', '.join(bots)}  (max_parallel_bots={cfg.max_parallel_bots}, "
          f"depth={cfg.max_depth}, actions<={cfg.max_actions_per_bot})")
    print("Ctrl+C — корректная остановка с сохранением прогресса.")
    try:
        statuses = asyncio.run(run_scan(cfg, bots, resume=resume))
        for bot, status in statuses.items():
            print(f"  {bot}: {status}")
    except KeyboardInterrupt:
        print("\nОстановлено пользователем; прогресс сохранён "
              "(Resume scan продолжит обход).")
    except RuntimeError as e:
        print(f"Ошибка: {e}")


def add_bot(cfg: Config, state: State) -> None:
    username = normalize_bot_username(input("Username бота (например @shop_bot): "))
    if not username.startswith("@"):
        print("Некорректное имя бота.")
        return
    state.register_bot(username)
    if username not in cfg.bots:
        cfg.bots.append(username)
        save_config(cfg)
        print(f"Добавлен {username} (сохранено в config.json)")
    else:
        print(f"{username} уже в списке.")


def list_bots(cfg: Config, state: State) -> None:
    rows = {b["username"]: b for b in state.list_bots()}
    bots = cfg.bots or list(rows)
    if not bots:
        print("Список пуст.")
        return
    print(f"{'Бот':<24} {'Статус':<14} {'Экранов':<8} {'Действий':<9} {'Рестартов':<10} {'Ошибок'}")
    for b in bots:
        info = rows.get(b)
        if info:
            screens_n = state._query_one(
                "SELECT COUNT(*) AS c FROM screens WHERE bot=?", (b,))["c"]
            errors_n = state._query_one(
                "SELECT COUNT(*) AS c FROM errors WHERE bot=?", (b,))["c"]
            # реальные счётчики — из scan_progress (обновляет crawler)
            actions_n = int(state.progress_get(b, "actions", "0"))
            restarts_n = int(state.progress_get(b, "restarts", "0"))
            print(f"{b:<24} {info['status'] or 'new':<14} {screens_n:<8} "
                  f"{actions_n:<9} {restarts_n:<10} {errors_n}")
        else:
            print(f"{b:<24} {'new':<14} 0        0         0          0")


def start_scan(cfg: Config, state: State) -> None:
    if not cfg.bots:
        print("Список ботов пуст. Сначала добавьте бота (пункт 1).")
        return
    fresh = [b for b in cfg.bots
             if not state.screens_all(b)]
    if not fresh:
        print("Все боты уже обойдены/начаты. Используйте Resume scan или Reset.")
        return
    _scan(cfg, fresh, resume=False)


def resume_scan(cfg: Config, state: State) -> None:
    resumable = [b for b in cfg.bots
                 if state.screens_all(b)
                 and (state.bot_info(b) or {}).get("status")
                 in ("running", "paused", "error", "limit_reached")]
    if not resumable:
        print("Нет ботов для продолжения (обход завершён или не начинался).")
        return
    _scan(cfg, resumable, resume=True)


def generate_reports_menu(cfg: Config, state: State) -> None:
    bots = [b for b in cfg.bots if state.screens_all(b)]
    if not bots:
        print("Нет данных обхода. Сначала Start scan.")
        return
    for bot in bots:
        paths = generate_reports(cfg, state, bot)
        print(f"{bot}: report.md, graph.json, callbacks.json, premium_emojis.json, "
              f"timeline → {paths['report'].parent}")
    comp = generate_comparison(cfg, state, bots)
    print(f"Сравнение: {comp}")


def show_errors(cfg: Config, state: State) -> None:
    bot = _pick_bot(cfg, state, "Показать ошибки бота")
    if not bot:
        return
    errs = state.errors_list(bot, limit=30)
    if not errs:
        print("Ошибок нет.")
        return
    for e in errs:
        print(f"[{e['ts']}] {e['kind']}: {e['message']}")


def reset_scan(cfg: Config, state: State) -> None:
    bot = _pick_bot(cfg, state, "Сбросить обход бота")
    if not bot:
        return
    confirm = input(f"Удалить ВСЕ данные обхода {bot}? (yes/no): ").strip().lower()
    if confirm == "yes":
        state.reset_bot(bot)
        print(f"Обход {bot} сброшен.")
    else:
        print("Отменено.")


def main_menu(cfg: Config | None = None) -> None:
    cfg = cfg or load_config()
    state = State(cfg.db_path)
    actions = {
        "1": add_bot, "2": list_bots, "3": start_scan, "4": resume_scan,
        "5": generate_reports_menu, "6": show_errors, "7": reset_scan,
    }
    try:
        while True:
            print(MENU)
            choice = input("Выбор: ").strip()
            if choice == "0":
                print("Выход.")
                break
            action = actions.get(choice)
            if action is None:
                print("Нет такого пункта.")
                continue
            try:
                action(cfg, state)
            except KeyboardInterrupt:
                print("\n(отменено)")
            except Exception as e:  # noqa: BLE001 — меню не должно падать
                print(f"Ошибка: {e}")
    except (KeyboardInterrupt, EOFError):
        print("\nВыход.")
    finally:
        state.close()
