"""Три уровня ограничения частоты:
1. per-bot limiter — случайная задержка delay_min..delay_max между действиями бота;
2. global account limiter — минимальный интервал между ЛЮБЫМИ запросами сессии;
3. FloodGate — глобальный FloodWait-гейт: любой FloodWaitError останавливает
   ВСЕ задачи аккаунта на wait+jitter (лимиты у Telegram аккаунтовые).
"""

from __future__ import annotations

import asyncio
import random
import time


class PerBotLimiter:
    def __init__(self, delay_min: float, delay_max: float):
        self.delay_min = max(0.0, delay_min)
        self.delay_max = max(self.delay_min, delay_max)

    async def wait(self) -> None:
        await asyncio.sleep(random.uniform(self.delay_min, self.delay_max))


class GlobalLimiter:
    """Сериализует любые запросы аккаунта с минимальным интервалом."""

    def __init__(self, min_interval: float):
        self.min_interval = max(0.0, min_interval)
        self._lock = asyncio.Lock()
        self._next_time = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_time - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_time = time.monotonic() + self.min_interval


class FloodGate:
    """Глобальный гейт паузы: все задачи ждут await wait_open() перед действием."""

    def __init__(self):
        self._event = asyncio.Event()
        self._event.set()
        self._deadline = 0.0
        self._lock = asyncio.Lock()

    @property
    def paused(self) -> bool:
        return not self._event.is_set()

    async def wait_open(self) -> None:
        await self._event.wait()

    async def pause(self, seconds: float) -> None:
        seconds = max(0.0, seconds)
        async with self._lock:
            deadline = time.monotonic() + seconds
            if deadline <= self._deadline:
                return  # уже стоит более длинная пауза
            self._deadline = deadline
            self._event.clear()
        loop = asyncio.get_running_loop()
        loop.call_later(seconds + 0.05, self._check_release, deadline)

    def _check_release(self, deadline: float) -> None:
        # отпускаем только если это актуальный дедлайн (не отменён более длинным)
        if deadline >= self._deadline - 1e-9 and time.monotonic() >= deadline - 0.1:
            self._event.set()
