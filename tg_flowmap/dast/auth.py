"""Telethon-клиент и интерактивная авторизация пользовательской сессии."""

from __future__ import annotations

from .config import Config


async def create_client(cfg: Config):
    """Создаёт TelegramClient (session-файл в папке проекта)."""
    import os
    from telethon import TelegramClient

    api_id = cfg.api_id or os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID")
    api_hash = cfg.api_hash or os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH")

    if not api_id or not api_hash or "PUT_YOUR" in str(api_hash):
        raise RuntimeError(
            "API credentials не настроены: укажите api_id и api_hash в config.json "
            "или через переменные окружения TELEGRAM_API_ID / TELEGRAM_API_HASH "
            "(получить на my.telegram.org → API development tools). "
            "См. README.md."
        )
    return TelegramClient(str(cfg.session_path), int(api_id), str(api_hash))


async def ensure_authorized(client) -> bool:
    """Подключается и при первом запуске проводит интерактивный вход
    (телефон → код из Telegram → 2FA-пароль, если задан)."""
    await client.connect()
    if await client.is_user_authorized():
        return True
    await client.start()  # интерактивные prompt-ы Telethon в консоли
    return await client.is_user_authorized()
