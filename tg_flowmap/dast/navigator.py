"""Навигатор: /start, нажатия inline/reply кнопок, ожидание результата.

Все действия проходят конвейер: safety → timeline (pending) → лимитеры
(per-bot → global → FloodGate) → запрос → timeline (финальный статус).
Внутри одного бота действия строго последовательны; атрибуция ответов —
через per-bot очередь событий (фильтр по chat_id делает scheduler).
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Optional

from .config import Config
from .models import ButtonRef, CallbackResult, PressOutcome
from .ratelimit import FloodGate, GlobalLimiter, PerBotLimiter
from .state import State
from .timeline_log import ActionLogger
from .tl_serial import clean


class EventRouter:
    """Per-bot очередь входящих new/edit событий чата."""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()

    def feed(self, kind: str, message) -> None:
        self._queue.put_nowait((kind, message))

    def drain(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:  # noqa: BLE001
                break

    async def wait_result(self, timeout: float, stabilization: float):
        """(primary(kind, message) | None, extras). После первичного события
        ждёт тишины stabilization секунд (собирая доп. сообщения в виде [(kind, msg), ...])."""
        primary = None
        extras: list = []
        start = time.monotonic()
        while primary is None:
            remain = timeout - (time.monotonic() - start)
            if remain <= 0:
                break
            try:
                kind, msg = await asyncio.wait_for(self._queue.get(), timeout=remain)
                primary = (kind, msg)
            except asyncio.TimeoutError:
                break
        if primary is None:
            return None, extras
        hard_deadline = start + timeout * 2
        while True:
            remain = min(stabilization, hard_deadline - time.monotonic())
            if remain <= 0:
                break
            try:
                kind, msg = await asyncio.wait_for(self._queue.get(), timeout=remain)
                extras.append((kind, msg))
            except asyncio.TimeoutError:
                break  # тишина stabilization секунд — стабилизировалось
        return primary, extras


class Navigator:
    def __init__(
        self,
        client,
        bot: str,
        chat,
        router: EventRouter,
        cfg: Config,
        state: State,
        logger: ActionLogger,
        per_bot_limiter: PerBotLimiter,
        global_limiter: GlobalLimiter,
        flood_gate: FloodGate,
    ):
        self.client = client
        self.bot = bot
        self.chat = chat
        self.router = router
        self.cfg = cfg
        self.state = state
        self.logger = logger
        self.per_bot = per_bot_limiter
        self.global_limiter = global_limiter
        self.flood_gate = flood_gate
        self._last_start_ts = 0.0

    # ------------------------------------------------------------- конвейер
    async def _through_limiters(self) -> None:
        """Порядок: сначала ждём снятия FloodWait (FloodGate), затем per-bot задержку
        и захват токена глобального лимитера, после чего финально убеждаемся, что гейт открыт."""
        await self.flood_gate.wait_open()
        await self.per_bot.wait()
        await self.global_limiter.acquire()
        await self.flood_gate.wait_open()

    def _flood_wait_seconds(self, exc: Exception) -> Optional[int]:
        try:
            return int(getattr(exc, "seconds", None))
        except (TypeError, ValueError):
            return None

    # -------------------------------------------------------------- экшены
    async def send_start(self) -> PressOutcome:
        # повторный /start не чаще start_cooldown
        since = time.monotonic() - self._last_start_ts
        if since < self.cfg.start_cooldown:
            await asyncio.sleep(self.cfg.start_cooldown - since)

        action_id = await self.logger.start_action(self.bot, "/start", {})
        t0 = time.monotonic()
        try:
            await self._through_limiters()
            self.router.drain()
            await self.client.send_message(self.chat, "/start")
            self._last_start_ts = time.monotonic()
            primary, extras = await self.router.wait_result(
                self.cfg.wait_response_timeout, self.cfg.wait_stabilization)
            if primary is None:
                out = PressOutcome(kind="timeout", duration_ms=int((time.monotonic() - t0) * 1000))
                status = "timeout"
            else:
                out = PressOutcome(kind=primary[0], message=primary[1],
                                   extra_messages=extras,
                                   duration_ms=int((time.monotonic() - t0) * 1000))
                status = "success"
            out.action_id = action_id
            await self.logger.finish_action(
                action_id, self.bot, status,
                duration_ms=out.duration_ms,
                payload={"result": out.kind})
            return out
        except Exception as e:  # noqa: BLE001
            fw = self._flood_wait_seconds(e)
            if fw is not None:
                await self.flood_gate.pause(fw + random.uniform(1, 5))
            await self.logger.finish_action(
                action_id, self.bot, "error",
                duration_ms=int((time.monotonic() - t0) * 1000), error=str(e))
            return PressOutcome(kind="error", error=str(e), action_id=action_id,
                                duration_ms=int((time.monotonic() - t0) * 1000))

    async def send_text(self, text: str, why: str = "manual_answer") -> PressOutcome:
        """Отправка разрешённого текста (manual_answers.json) — тот же конвейер."""
        action_id = await self.logger.start_action(
            self.bot, f"text:{why}", {"text": text})
        t0 = time.monotonic()
        try:
            await self._through_limiters()
            self.router.drain()
            await self.client.send_message(self.chat, text)
            primary, extras = await self.router.wait_result(
                self.cfg.wait_response_timeout, self.cfg.wait_stabilization)
            if primary is None:
                out = PressOutcome(kind="timeout")
                status = "timeout"
            else:
                out = PressOutcome(kind=primary[0], message=primary[1],
                                   extra_messages=extras)
                status = "success"
            out.action_id = action_id
            await self.logger.finish_action(
                action_id, self.bot, status,
                duration_ms=int((time.monotonic() - t0) * 1000),
                payload={"result": out.kind})
            out.duration_ms = int((time.monotonic() - t0) * 1000)
            return out
        except Exception as e:  # noqa: BLE001
            fw = self._flood_wait_seconds(e)
            if fw is not None:
                await self.flood_gate.pause(fw + random.uniform(1, 5))
            await self.logger.finish_action(
                action_id, self.bot, "error", error=str(e))
            return PressOutcome(kind="error", error=str(e), action_id=action_id)

    async def press_button(self, button: ButtonRef, message_id: int) -> PressOutcome:
        """Нажатие inline-callback или reply-кнопки. Полный результат
        GetBotCallbackAnswerRequest сохраняется в PressOutcome.callback.
        Заблокированная safety-фильтром кнопка не нажимается НИКОГДА,
        даже при прямом вызове."""
        payload = {
            "label": button.label, "button_type": button.button_type,
            "callback_hex": button.callback_hex, "url": button.url,
            "screen_msg_id": message_id,
        }
        action_id = await self.logger.start_action(self.bot, "press", payload)
        if button.blocked_reason or button.requires_password:
            reason = ("requires_password" if button.requires_password
                      else f"blocked:{button.blocked_reason}")
            await self.logger.finish_action(
                action_id, self.bot, "blocked", error=reason)
            return PressOutcome(kind="error", action_id=action_id, error=reason)
        t0 = time.monotonic()
        cb: CallbackResult | None = None
        err: str | None = None
        try:
            await self._through_limiters()
            self.router.drain()
            if button.button_type == "callback" and button.callback_data is not None:
                cb, err = await self._press_callback(button, message_id)
            elif button.button_type == "reply" and self.cfg.press_reply_keyboard:
                await self.client.send_message(self.chat, button.label)
            else:
                await self.logger.finish_action(
                    action_id, self.bot, "blocked",
                    error=f"unsupported button type: {button.button_type}")
                return PressOutcome(kind="error", action_id=action_id,
                                    error=f"unsupported button type: {button.button_type}")
            primary, extras = await self.router.wait_result(
                self.cfg.wait_response_timeout, self.cfg.wait_stabilization)
            duration_ms = int((time.monotonic() - t0) * 1000)
            if primary is not None:
                kind, message = primary
                status = "success"
            elif err is not None:
                kind, message, status = "error", None, "error"
            elif cb is not None and cb.exception is None:
                kind, message, status = "answer_only", None, "success"
            else:
                kind, message, status = "timeout", None, "timeout"
            if cb is not None:
                cb.duration_ms = duration_ms
            await self.logger.finish_action(
                action_id, self.bot, status, duration_ms=duration_ms, error=err,
                payload={"result": kind, "answer": cb.message if cb else None})
            return PressOutcome(
                kind=kind, message=message, callback=cb,
                duration_ms=duration_ms, extra_messages=extras, error=err,
                action_id=action_id)
        except Exception as e:  # noqa: BLE001
            fw = self._flood_wait_seconds(e)
            if fw is not None:
                await self.flood_gate.pause(fw + random.uniform(1, 5))
            duration_ms = int((time.monotonic() - t0) * 1000)
            await self.logger.finish_action(
                action_id, self.bot, "error", duration_ms=duration_ms, error=str(e))
            return PressOutcome(kind="error", error=str(e), duration_ms=duration_ms,
                                action_id=action_id)

    async def _press_callback(
        self, button: ButtonRef, message_id: int,
    ) -> tuple[CallbackResult, str | None]:
        """Raw GetBotCallbackAnswerRequest: полный разбор ответа/исключения."""
        from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

        t0 = time.monotonic()
        try:
            res = await self.client(
                GetBotCallbackAnswerRequest(
                    peer=self.chat, msg_id=int(message_id), data=button.callback_data
                )
            )
            cb = CallbackResult(
                message=getattr(res, "message", None),
                alert=bool(getattr(res, "alert", False)),
                url=getattr(res, "url", None),
                cache_time=getattr(res, "cache_time", None),
                raw=clean(res),
            )
            return cb, None
        except Exception as e:  # noqa: BLE001
            cb = CallbackResult(
                exception=f"{type(e).__name__}: {e}",
                raw=clean(e),
            )
            fw = self._flood_wait_seconds(e)
            if fw is not None:
                await self.flood_gate.pause(fw + random.uniform(1, 5))
                return cb, f"floodwait:{fw}"
            return cb, f"{type(e).__name__}: {e}"

    async def download_media(self, msg, media_dir, index: int | None = None):
        from .media import download_media

        if not self.cfg.download_media:
            return None
        return await download_media(
            self.client, msg, media_dir,
            max_size_bytes=self.cfg.media_max_size_bytes, index=index)
