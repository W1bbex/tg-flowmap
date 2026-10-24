"""Scheduler: 1..2 задач обхода на одном Telethon-клиенте (одна сессия).

- один общий GlobalLimiter и FloodGate на аккаунт; разрешение entity
  (client.get_entity) тоже проходит через общий лимитер и гейт;
- у каждого бота своя EventRouter-очередь, PerBotLimiter, TimelineWriter
  и ActionLogger (timeline.jsonl лежит в output/<bot>/);
- в EventRouter попадают ТОЛЬКО входящие сообщения бота (out=False);
- изолированное выполнение: ошибка одного бота не останавливает остальных;
- периодический компактный вывод прогресса без спама в консоль;
- полное логирование Telethon в logs/telethon.log с ротацией.
"""

from __future__ import annotations

import asyncio
import logging
import random

from .auth import create_client, ensure_authorized
from .config import Config, load_manual_answers, normalize_bot_username
from .crawler import BotCrawler
from .logging_setup import setup_logging
from .navigator import EventRouter, Navigator
from .ratelimit import FloodGate, GlobalLimiter, PerBotLimiter
from .safety import SafetyFilter
from .state import State
from .timeline_log import ActionLogger, TimelineWriter

logger = logging.getLogger(__name__)


def bot_output_dir(cfg: Config, bot: str):
    return cfg.output_dir / bot.lstrip("@")


def _feed_incoming(router: EventRouter, kind: str, message) -> None:
    if getattr(message, "out", False):
        return
    router.feed(kind, message)


def _make_event_handler(router: EventRouter, kind: str):
    async def handler(event) -> None:
        _feed_incoming(router, kind, event.message)

    return handler


async def _resolve_entity(client, bot: str, global_limiter: GlobalLimiter, flood_gate: FloodGate):
    await global_limiter.acquire()
    await flood_gate.wait_open()
    try:
        return await client.get_entity(bot)
    except Exception as e:  # noqa: BLE001
        fw = getattr(e, "seconds", None)
        if fw is not None:
            await flood_gate.pause(fw + random.uniform(1, 5))
        raise


def _dedupe_bots(bots: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in bots:
        bot = normalize_bot_username(raw or "")
        if not bot or bot in seen:
            continue
        seen.add(bot)
        out.append(bot)
    return out


async def _progress_monitor(state: State, bots: list[str], interval: float) -> None:
    """Периодически выводит компактную строку прогресса:
    bot | screens | actions | frontier | starts | errors"""
    while True:
        await asyncio.sleep(interval)
        lines = []
        for b in bots:
            screens_n = len(state.screens_all(b))
            actions_n = int(state.progress_get(b, "actions", "0"))
            frontier_n = state.frontier_active_count(b)
            starts_n = int(state.progress_get(b, "start_count", state.progress_get(b, "restarts", "0")))
            errors_n = len(state.errors_list(b))
            status = (state.bot_info(b) or {}).get("status", "running")
            lines.append(
                f"[{b}] status: {status} | screens: {screens_n} | actions: {actions_n} "
                f"| frontier: {frontier_n} | starts: {starts_n} | errors: {errors_n}"
            )
        if lines:
            print(" | ".join(lines))


async def run_scan(cfg: Config, bots: list[str], resume: bool = False) -> dict[str, str]:
    """Обходит список ботов. Возвращает {username: финальный статус}."""
    from telethon import events

    # Настройка ротации логов Telethon
    setup_logging(
        log_dir=cfg.root / "logs",
        max_mb=getattr(cfg, "telethon_log_max_mb", 5.0),
        backup_count=getattr(cfg, "telethon_log_backups", 3),
    )

    bots = _dedupe_bots(bots)
    if not bots:
        return {}

    client = await create_client(cfg)
    if not await ensure_authorized(client):
        await client.disconnect()
        raise RuntimeError(
            "Не удалось авторизоваться в Telegram. Запустите ещё раз и пройдите "
            "вход (телефон → код → 2FA)."
        )

    state = State(cfg.db_path)
    global_limiter = GlobalLimiter(cfg.global_min_interval)
    flood_gate = FloodGate()
    semaphore = asyncio.Semaphore(cfg.max_parallel_bots)
    manual_answers = load_manual_answers(cfg.root / "manual_answers.json")
    safety = SafetyFilter(cfg)

    writers: list[TimelineWriter] = []
    crawlers: dict[str, BotCrawler] = {}
    tasks: list[asyncio.Task] = []
    handlers: list = []

    # Фоновый монитор прогресса
    progress_task = asyncio.create_task(
        _progress_monitor(state, bots, getattr(cfg, "progress_interval_seconds", 3.0))
    )

    try:
        tasks: list[asyncio.Task] = []
        scheduled_bots: list[str] = []
        statuses: dict[str, str] = {}
        for username in bots:
            bot_dir = bot_output_dir(cfg, username)
            bot_dir.mkdir(parents=True, exist_ok=True)
            (bot_dir / "media").mkdir(exist_ok=True)

            try:
                entity = await _resolve_entity(client, username, global_limiter, flood_gate)
                state.register_bot(username, entity.id)
            except Exception as e:  # noqa: BLE001
                logger.error("Ошибка разрешения бота %s: %s", username, e, exc_info=True)
                state.register_bot(username)
                state.set_bot_status(username, "error", f"resolve failed: {e}")
                statuses[username] = f"error: resolve failed: {e}"
                continue

            router = EventRouter()
            writer = TimelineWriter(bot_dir / "timeline.jsonl")
            writers.append(writer)
            act_logger = ActionLogger(state, writer)

            h_new = _make_event_handler(router, "new")
            h_edit = _make_event_handler(router, "edit")
            client.add_event_handler(h_new, events.NewMessage(chats=entity))
            client.add_event_handler(h_edit, events.MessageEdited(chats=entity))
            handlers.extend([(h_new,), (h_edit,)])

            navigator = Navigator(
                client, username, entity, router, cfg, state, act_logger,
                PerBotLimiter(cfg.delay_min, cfg.delay_max),
                global_limiter, flood_gate,
            )
            crawler = BotCrawler(
                cfg, state, act_logger, safety, navigator, manual_answers, username,
                media_dir=bot_dir / "media",
            )
            crawlers[username] = crawler

            async def _runner(c: BotCrawler = crawler, uname: str = username) -> str:
                async with semaphore:
                    try:
                        return await c.run(resume=resume)
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Ошибка обходчика для %s: %s", uname, exc, exc_info=True)
                        state.set_bot_status(uname, "error", str(exc))
                        return "error"

            tasks.append(asyncio.create_task(_runner(), name=f"crawl:{username}"))
            scheduled_bots.append(username)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for bot, res in zip(scheduled_bots, results):
                if isinstance(res, BaseException):
                    statuses[bot] = f"error: {res}"
                    state.set_bot_status(bot, "error", str(res))
                else:
                    statuses[bot] = str(res)
            return statuses
        return statuses
    finally:
        progress_task.cancel()
        for crawler in crawlers.values():
            crawler.stop()
        for task in tasks:
            if not task.done():
                task.cancel()
        for (h,) in handlers:
            try:
                client.remove_event_handler(h)
            except Exception:  # noqa: BLE001
                pass
        for w in writers:
            w.close()
        state.close()
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
