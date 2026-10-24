"""Настройка логирования: запись детальных логов Telethon в logs/telethon.log
с ротацией файлов и предотвращение засорения консоли.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
    log_dir: Path | str = "logs",
    max_mb: float = 5.0,
    backup_count: int = 3,
) -> None:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "telethon.log"

    max_bytes = int(max_mb * 1024 * 1024)

    # 1. File Handler для Telethon и общих логов (детальный)
    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)

    # 2. Настройка логгера Telethon
    telethon_logger = logging.getLogger("telethon")
    telethon_logger.setLevel(logging.DEBUG)
    telethon_logger.addHandler(file_handler)
    # Не пропускаем детальный telethon спам в root консоль
    telethon_logger.propagate = False

    # 3. Настройка корневого логгера
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if file_handler not in root_logger.handlers:
        root_logger.addHandler(file_handler)
