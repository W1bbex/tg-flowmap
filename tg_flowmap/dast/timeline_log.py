"""Append-only timeline.jsonl + ActionLogger.

Правила (по ТЗ):
- старые строки pending НЕ обновляются: у одного действия несколько событий
  с общим action_id (pending → success/timeout/blocked/error/interrupted);
- запись через общий asyncio.Lock — параллельные боты не перемешивают байты;
- каждая строка — один atomic write + flush; читатель игнорирует оборванную
  последнюю строку после аварии;
- timeline.json — только опциональный итоговый экспорт из SQLite.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from .tl_serial import clean


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TimelineWriter:
    """Единый writer на файл: строки добавляются атомарно под asyncio.Lock."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._fh = open(self.path, "a", encoding="utf-8", newline="\n")

    async def write(self, event: dict) -> None:
        line = json.dumps(clean(event), ensure_ascii=False)
        async with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass


def read_valid_lines(path: Path | str) -> tuple[list[dict], int]:
    """Читает JSONL, игнорируя ОБОРВАННУЮ последнюю строку (после аварии).
    Возвращает (валидные события, число пропущенных строк)."""
    path = Path(path)
    if not path.exists():
        return [], 0
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    valid: list[dict] = []
    skipped = 0
    for i, line in enumerate(raw_lines):
        s = line.strip()
        if not s:
            continue
        try:
            valid.append(json.loads(s))
        except json.JSONDecodeError:
            # последняя строка может быть оборвана аварийным завершением —
            # это ожидаемо; битая строка в середине журнала тоже пропускается
            skipped += 1
    return valid, skipped


class ActionLogger:
    """pending до действия → финальный статус после. SQLite-строка обновляется,
    в JSONL каждое событие добавляется НОВОЙ строкой с тем же action_id."""

    def __init__(self, state, writer: TimelineWriter):
        self.state = state
        self.writer = writer

    async def start_action(self, bot: str, action: str, payload: dict | None = None) -> str:
        import uuid
        action_id = uuid.uuid4().hex
        payload = payload or {}
        self.state.timeline_create(action_id, bot, action, payload)
        await self.writer.write({
            "action_id": action_id, "bot": bot, "ts": utcnow(), "action": action,
            "status": "pending", "payload": payload,
        })
        return action_id

    async def finish_action(
        self, action_id: str, bot: str, status: str,
        duration_ms: int | None = None, error: str | None = None,
        payload: dict | None = None,
    ) -> None:
        self.state.timeline_update(action_id, status, duration_ms=duration_ms, error=error)
        event = {
            "action_id": action_id, "bot": bot, "ts": utcnow(), "status": status,
            "duration_ms": duration_ms, "error": error,
        }
        if payload:
            event["payload"] = payload
        await self.writer.write(event)
