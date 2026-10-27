"""Скачивание медиа в output/<bot>/media/.

- Одно физическое скачивание основного media сообщения (client.download_media);
- file_path присваивается только primary non-web_preview MediaInfo;
- web_preview и вспомогательные элементы остаются метаданными с file_path=None;
- max_size_bytes проверяется ДО скачивания по размеру документа
  (заведомо большой файл не качаем совсем);
- имена файлов формируются с безопасным расширением: msg<id>_<kind>_<tgid>.<ext>;
- при ошибке частично скачанный файл удаляется;
- ошибки скачивания не прерывают обход.
"""

from __future__ import annotations

import re
from pathlib import Path

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe(s: str) -> str:
    return _SAFE.sub("_", str(s))[:48] or "x"


def _ext_for(msg, doc) -> str:
    mime = (getattr(doc, "mime_type", None) or "") if doc is not None else ""
    if "/" in mime:
        sub = mime.split("/")[-1].split("+")[0].split(";")[0][:8]
        clean_sub = _SAFE.sub("", sub)
        if clean_sub:
            return "." + clean_sub
    if getattr(msg, "photo", None) is not None:
        return ".jpg"
    return ".bin"


def media_file_name(msg, kind: str, tg_id: str | None = None, doc: object = None, index: int | None = None) -> str:
    mid = getattr(msg, "id", 0)
    ext = _ext_for(msg, doc)
    idx_part = f"_{index}" if index is not None else ""
    return f"msg{mid}{idx_part}_{_safe(kind)}_{_safe(tg_id or '')}{ext}"


async def download_media(
    client, msg, media_dir: Path,
    max_size_bytes: int | None = None, index: int | None = None,
) -> str | None:
    """Скачивает основное медиа сообщения; возвращает путь или None.
    - Заведомо большой файл (size > max_size_bytes) не качаем вообще;
    - При ошибке частично скачанный файл удаляется;
    - Ошибки не прерывают обход (возвращается None)."""
    try:
        doc = getattr(msg, "document", None)
        size = getattr(doc, "size", None) if doc is not None else None
        if (max_size_bytes is not None and isinstance(size, int)
                and size > max_size_bytes):
            return None  # слишком большой — не качаем

        photo = getattr(msg, "photo", None)
        has_media = photo is not None or doc is not None or any(
            getattr(msg, attr, None) is not None
            for attr in ("video", "animation", "audio", "voice", "sticker")
        )
        if not has_media:
            return None

        media_dir = Path(media_dir)
        media_dir.mkdir(parents=True, exist_ok=True)
        kind = "photo" if photo is not None else ("document" if doc is not None else "media")
        tg_id = getattr(photo, "id", None) or getattr(doc, "id", None) or ""
        fname = media_file_name(msg, kind, str(tg_id) if tg_id else None, doc=doc, index=index)
        target = media_dir / fname
        if target.exists() and target.stat().st_size > 0:
            return str(target)
        try:
            result = await client.download_media(msg, file=str(target))
        except BaseException:
            if target.exists():
                try:
                    target.unlink()  # не оставляем частичный файл при отмене или ошибке
                except OSError:
                    pass
            raise
        if not result:
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
            return None
        return str(result)
    except Exception:  # noqa: BLE001 — медиа не критично для обхода
        return None
