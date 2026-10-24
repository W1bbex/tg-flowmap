"""Загрузка и валидация config.json + manual_answers.json."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DANGER_WORDS = [
    "buy", "purchase", "pay", "confirm", "checkout", "deposit", "top up", "topup",
    "купить", "оплатить", "подтвердить", "пополнить", "оплата", "покупка", "оформить заказ",
]

DEFAULT_CHECKOUT_WORDS = [
    "checkout", "payment", "оплата", "к оплате", "ваш заказ", "your order",
    "подтверждение заказа", "confirm order", "реквизиты", "пополнение баланса", "счёт на оплату",
]

DEFAULT_PRICE_REGEX = r"([$€£₽]\s?\d|\d+([.,]\d+)?\s?(USD|EUR|RUB|руб|₽|\$|uah|тенге))"

DEFAULT_BACK_WORDS = ["back", "назад", "⬅", "◀", "←"]

DEFAULT_VOLATILE_PATTERNS = [
    r"\d{2}[./]\d{2}[./]\d{2,4}",
    r"\d{1,2}:\d{2}(:\d{2})?",
    r"(?i)оста[лт][а-яё]*\s*[:—-]?\s*\d+",
    r"(?i)в наличии\s*[:—-]?\s*\d+",
    r"(?i)кол-во\s*[:—-]?\s*\d+",
    r"#\d+",
    r"[$€£₽]\s?\d+([.,]\d+)?",
    r"\d+([.,]\d+)?\s?(USD|RUB|руб|₽|\$)",
]

# Слова навигации: кнопка с таким текстом считается "известного назначения"
DEFAULT_SAFE_NAV_WORDS = [
    "menu", "меню", "catalog", "каталог", "home", "главная", "profile", "профиль",
    "support", "поддержка", "help", "помощь", "faq", "back", "назад", "next", "далее",
    "вперёд", "вперед", "info", "инфо", "cart", "корзина", "settings", "настройки",
    "language", "язык", "about", "о нас", "отзывы", "reviews", "rules", "правила",
]


@dataclass
class Config:
    api_id: int = 0
    api_hash: str = ""
    session_name: str = "market_research"
    bots: list[str] = field(default_factory=list)
    language: str = "ru"
    delay_min: float = 2.0
    delay_max: float = 5.0
    max_depth: int = 8
    max_actions_per_bot: int = 300
    max_parallel_bots: int = 1
    wait_response_timeout: float = 15.0
    wait_stabilization: float = 3.0
    start_cooldown: float = 20.0
    max_restarts_per_bot: int = 15
    max_consecutive_errors: int = 10
    max_same_screen_visits: int = 5
    global_min_interval: float = 1.0
    press_reply_keyboard: bool = True
    download_media: bool = True
    media_max_size_mb: float = 25.0
    export_timeline_json: bool = True
    navigation_mode: str = "graph"                 # "graph" | "legacy"
    frontier_strategy: str = "graph_locality"      # "graph_locality" | "graph_only" | "bfs" | "dfs"
    recovery_start_cost: float = 3.0
    max_replans_per_target: int = 2
    edge_confidence_threshold: float = 0.6
    progress_interval_seconds: float = 3.0
    telethon_log_max_mb: float = 5.0
    telethon_log_backups: int = 3
    danger_words: list[str] = field(default_factory=lambda: list(DEFAULT_DANGER_WORDS))
    checkout_words: list[str] = field(default_factory=lambda: list(DEFAULT_CHECKOUT_WORDS))
    price_regex: str = DEFAULT_PRICE_REGEX
    back_words: list[str] = field(default_factory=lambda: list(DEFAULT_BACK_WORDS))
    blocked_button_patterns: list[str] = field(default_factory=list)
    allowed_button_labels: list[str] = field(default_factory=list)
    volatile_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_VOLATILE_PATTERNS))
    safe_nav_words: list[str] = field(default_factory=lambda: list(DEFAULT_SAFE_NAV_WORDS))
    root: Path = field(default=PACKAGE_ROOT, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        # max_parallel_bots: default 1, максимум 2 (вручную)
        self.max_parallel_bots = min(2, max(1, int(self.max_parallel_bots)))
        self.max_depth = max(1, int(self.max_depth))
        self.max_actions_per_bot = max(1, int(self.max_actions_per_bot))
        self.delay_min = max(0.1, float(self.delay_min))
        self.delay_max = max(self.delay_min, float(self.delay_max))
        self.wait_response_timeout = max(3.0, float(self.wait_response_timeout))
        self.wait_stabilization = max(0.5, float(self.wait_stabilization))
        self.start_cooldown = max(5.0, float(self.start_cooldown))
        self.global_min_interval = max(0.0, float(self.global_min_interval))
        self.media_max_size_mb = max(0.0, float(self.media_max_size_mb))
        self.recovery_start_cost = max(1.0, float(self.recovery_start_cost))
        self.max_replans_per_target = max(1, int(self.max_replans_per_target))
        self.edge_confidence_threshold = max(0.0, min(1.0, float(self.edge_confidence_threshold)))
        self.progress_interval_seconds = max(0.5, float(self.progress_interval_seconds))
        self.telethon_log_max_mb = max(0.5, float(self.telethon_log_max_mb))
        self.telethon_log_backups = max(1, int(self.telethon_log_backups))
        self.bots = _clean_bots(self.bots)

        # Мягкая миграция и нормализация navigation_mode: "graph" (default) и "legacy"
        nav_mode = (str(self.navigation_mode) if self.navigation_mode else "graph").strip().lower()
        if nav_mode in ("legacy", "replay"):
            self.navigation_mode = "legacy"
        elif nav_mode in ("graph", "frontier_first"):
            self.navigation_mode = "graph"
        else:
            self.navigation_mode = "graph"

        # Мягкая миграция и нормализация frontier_strategy: "graph_locality" (default), "graph_only", "bfs", "dfs"
        f_strat = (str(self.frontier_strategy) if self.frontier_strategy else "graph_locality").strip().lower()
        if f_strat in ("graph_locality", "locality"):
            self.frontier_strategy = "graph_locality"
        elif f_strat in ("graph_only", "bfs", "dfs"):
            self.frontier_strategy = f_strat
        else:
            self.frontier_strategy = "graph_locality"

    # ---- пути -------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.root / "explorer.db"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def session_path(self) -> Path:
        return self.root / self.session_name

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def media_max_size_bytes(self) -> int:
        return int(self.media_max_size_mb * 1024 * 1024)

    # ---- компиляция регулярных выражений ----------------------------------
    def compiled_volatile(self) -> list[re.Pattern]:
        return [_compile_pat(p) for p in self.volatile_patterns]

    def compiled_price(self) -> re.Pattern:
        return _compile_pat(self.price_regex)

    def compiled_blocked(self) -> list[re.Pattern]:
        return [_compile_pat(p) for p in self.blocked_button_patterns]

    # ---- (де)сериализация --------------------------------------------------
    def to_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "root"}
        return d

    def save(self, path: Path | None = None) -> None:
        path = Path(path or self.config_path)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _compile_pat(p: str) -> re.Pattern:
    try:
        return re.compile(p)
    except re.error:
        return re.compile(re.escape(p))


def _clean_bots(bots) -> list[str]:
    """Валидация списка ботов: только list[str]; пустые и дубликаты удаляются,
    порядок сохраняется (обратная совместимость config.json)."""
    if bots is None:
        return []
    if not isinstance(bots, list) or not all(
            isinstance(b, str) for b in bots):
        raise ValueError("config.json: поле 'bots' должно быть списком строк "
                         "вида [\"@bot_username\", ...]")
    seen: set[str] = set()
    out: list[str] = []
    for raw in bots:
        norm = normalize_bot_username(raw)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def normalize_bot_username(username: str) -> str:
    """Приводит любое написание к '@name' (нижний регистр)."""
    u = (username or "").strip()
    if not u:
        return ""
    m = re.search(r"(?:t\.me/|@(?:))([A-Za-z0-9_]{1,64})", u)
    if m and ("t.me/" in u or u.startswith("@")):
        return "@" + m.group(1).lower()
    if re.fullmatch(r"[A-Za-z0-9_]{1,64}", u):
        return "@" + u.lower()
    return u.lower()


def load_config(path: Path | str | None = None) -> Config:
    path = Path(path) if path else PACKAGE_ROOT / "config.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise ValueError(f"Не удалось прочитать конфиг {path}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("Конфиг должен быть JSON-объектом")
    known = {f.name for f in fields(Config)}
    payload = {k: v for k, v in data.items() if k in known}
    cfg = Config(**payload)
    cfg.root = path.parent
    return cfg


def save_config(cfg: Config, path: Path | None = None) -> None:
    cfg.save(path)


def load_manual_answers(path: Path | str | None = None) -> dict:
    path = Path(path) if path else PACKAGE_ROOT / "manual_answers.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}
