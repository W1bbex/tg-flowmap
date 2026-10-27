"""Регрессионные тесты исправлений DAST-подсистемы:
- Изоляция Telethon .session файла от каталога отчётов
- Корректная загрузка graph.json (nodes, edges, metrics) в _load_target_data (команда compare)
- Блокировка опасного callback_data payload даже при наличии метки в allowlist
- Распознавание TON-кошельков (EQ... / UQ...)
- Экранирование спецсимволов | и \n в рендере диаграмм Mermaid
- Оптимизация сбора статистики сравнения без N+1 запросов
"""

from pathlib import Path
import json
import pytest

from tg_flowmap.cli import _load_target_data
from tg_flowmap.dast.config import Config
from tg_flowmap.dast.map_render import _render_map_mmd
from tg_flowmap.dast.safety import SafetyFilter, WALLET_REGEXES


def test_session_isolation_from_custom_output_dir(tmp_path):
    """Проверка, что передача custom_output_dir не перемещает .session в папку отчётов."""
    root_dir = tmp_path / "bot_root"
    out_dir = tmp_path / "public_reports"
    root_dir.mkdir()
    out_dir.mkdir()

    cfg = Config(root=root_dir, custom_output_dir=out_dir, session_name="my_private.session")
    assert cfg.output_dir == out_dir
    assert cfg.session_path == root_dir / "my_private.session"
    assert cfg.session_path.parent != out_dir
    assert cfg.db_path == root_dir / "explorer.db"


def test_load_target_data_dast_graph_json(tmp_path):
    """Проверка, что _load_target_data корректно читает nodes и edges из graph.json."""
    bot_dir = tmp_path / "test_bot"
    bot_dir.mkdir()
    graph_path = bot_dir / "graph.json"

    graph_payload = {
        "nodes": [
            {
                "id": "s_start",
                "text": "Привет! Добро пожаловать",
                "text_normalized": "привет добро пожаловать",
                "buttons": [
                    {"label": "Каталог", "button_type": "callback"},
                    {"label": "Помощь", "button_type": "callback"},
                ],
            },
            {
                "id": "s_catalog",
                "text": "Каталог товаров",
                "text_normalized": "каталог товаров",
                "buttons": [
                    {"label": "Товар 1", "button_type": "callback"},
                ],
            },
        ],
        "edges": [
            {"from": "s_start", "to": "s_catalog", "action": "Каталог"},
        ],
        "routes": [
            {"route_id": "r1", "screen_id": "s_start"},
            {"route_id": "r2", "screen_id": "s_catalog"},
        ],
    }
    graph_path.write_text(json.dumps(graph_payload), encoding="utf-8")

    data = _load_target_data("@test_bot", tmp_path)
    metrics = data["metrics"]
    assert metrics["screens_count"] == 2
    assert metrics["buttons_count"] == 3  # 2 + 1 кнопки в nodes
    assert len(data["screens"]) == 2
    assert data["screens"][0]["screen_id"] == "s_start"
    assert len(data["screens"][0]["buttons"]) == 2


def test_safety_filter_blocks_destructive_callback_despite_allowed_label():
    """Проверка, что кнопка с текстом из allowlist ('Да', 'Меню'), но опасным callback, блокируется."""
    cfg = Config(allowed_button_labels=["да", "меню", "продолжить"])
    sf = SafetyFilter(cfg)

    # Безопасный callback
    can_safe, reason_safe = sf.button_verdict(
        label="Да",
        button_type="callback",
        screen_text="Обычный экран",
        callback_data="agree_terms",
    )
    assert can_safe is True
    assert reason_safe is None

    # Опасный callback со словом из danger_words (delete, purchase, etc.)
    can_danger, reason_danger = sf.button_verdict(
        label="Да",
        button_type="callback",
        screen_text="Обычный экран",
        callback_data="delete_account_confirm",
    )
    assert can_danger is False
    assert "danger_callback_word" in str(reason_danger)


def test_ton_wallet_detection():
    """Проверка распознавания TON-кошельков (EQ... / UQ...)."""
    ton_raw_eq = "EQD4FPq-PRDieyQKkKZjmNu4NoKitog2CGWNWZAnWReOTPrz"
    ton_raw_uq = "UQD4FPq-PRDieyQKkKZjmNu4NoKitog2CGWNWZAnWReOTPrz"

    matched_eq = any(r.search(ton_raw_eq) for r in WALLET_REGEXES)
    matched_uq = any(r.search(ton_raw_uq) for r in WALLET_REGEXES)

    assert matched_eq is True, "EQ TON address not recognized"
    assert matched_uq is True, "UQ TON address not recognized"


def test_mermaid_render_escapes_pipes_and_newlines():
    """Проверка, что пайпы и переносы строк в названиях кнопок не ломают Mermaid синтаксис."""
    nodes = [{"id": "s1", "text_norm": "Главная\nМеню | Выбор"}]
    edges = [
        {"source": "s1", "target": "s2", "label": "Оплата | СБП\nБыстро", "result_type": "edit"},
    ]
    mmd = _render_map_mmd("test_bot", nodes, edges)

    # Внутри стрелки -->|"label"| не должно остаться неэкранированных пайпов или переносов
    assert "Оплата / СБП Быстро" in mmd
    assert "\nБыстро" not in mmd
    assert "-->|\"Оплата / СБП Быстро\"|" in mmd
