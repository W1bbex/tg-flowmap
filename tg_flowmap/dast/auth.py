"""Telethon-клиент и интерактивная авторизация пользовательской сессии."""

from __future__ import annotations

from .config import Config


async def create_client(cfg: Config):
    """Создаёт TelegramClient (session-файл в папке проекта)."""
    from telethon import TelegramClient

    if not cfg.api_id or not cfg.api_hash or "PUT_YOUR" in cfg.api_hash:
        raise RuntimeError(
            "config.json не настроен: заполните api_id и api_hash "
            "(получить на my.telegram.org → API development tools). "
            "См. README.md."
        )
    return TelegramClient(str(cfg.session_path), cfg.api_id, cfg.api_hash)


async def ensure_authorized(client) -> bool:
    """Подключается и при первом запуске проводит интерактивный вход
    (телефон → код из Telegram → 2FA-пароль, если задан)."""
    await client.connect()
    if await client.is_user_authorized():
        return True
    await client.start()  # интерактивные prompt-ы Telethon в консоли
    return await client.is_user_authorized()
