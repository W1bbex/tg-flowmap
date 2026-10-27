"""Контекстный фильтр опасных кнопок/экранов + manual answers.

Кнопка проверяется по СВОЕМУ тексту и по КОНТЕКСТУ экрана. Каждая блокировка
возвращается с точной причиной (сохраняется в карте).
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .config import Config

WALLET_REGEXES = [
    re.compile(r"0x[0-9a-fA-F]{40}"),
    re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b", re.IGNORECASE),        # TRON / USDT TRC20
    re.compile(r"\bbc1[a-z0-9]{20,60}\b", re.IGNORECASE),               # Bitcoin bech32
    re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b", re.IGNORECASE),  # Bitcoin legacy
    re.compile(r"\b[EU]Q[0-9a-zA-Z_-]{46}\b"),                          # TON / Telegram Open Network
]
PAYMENT_INSTRUCTION_WORDS = [
    "переведите", "перевод на", "send the exact amount", "scan the qr", "отсканируй",
    "отсканируйте", "сканируйте", "oplatite в течение", "оплатите в течение",
    "payment instructions", "инструкция по оплате", "реквизиты для оплаты",
]
QUANTITY_WORDS = ["количество", "кол-во", "quantity", "штук", "шт.", "шт:"]
PASSWORD_WORDS = ["пароль", "password", "пин-код", "pin code", "пинкод"]
CANCEL_WORDS = ["cancel", "отмена", "отменить", "stop", "стоп", "прервать"]
INPUT_PROMPT_WORDS = [
    "введите", "укажите", "отправьте", "напишите", "введи", "укажи",
    "send", "enter", "type", "input", "e-mail", "email", "код", "code",
]

_EMOJI_CHARS = re.compile(
    "["
    "\U0001F000-\U0001FAFF"      # emoji main + supplementary
    "\u2600-\u27BF"              # misc symbols/dingbats
    "\u2190-\u21FF"              # arrows
    "\u2B00-\u2BFF"              # misc symbols and arrows
    "\uFE0F\u200D\u20E3"         # variation selector, ZWJ, keycap
    "\u2705\u274C\u2764\u2B50"   # часто используемые
    "]+"
)


def is_emoji_only(label: str) -> bool:
    """True, если в метке нет ни одного word-символа (буквы/цифры/underscore)."""
    rest = _EMOJI_CHARS.sub("", label or "")
    return not re.search(r"\w", rest, re.UNICODE)


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s if s is not None else "").strip()).lower()


class SafetyFilter:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.danger_words = [_norm(w) for w in cfg.danger_words if w]
        self.checkout_words = [_norm(w) for w in cfg.checkout_words if w]
        self.back_words = [_norm(w) for w in cfg.back_words if w]
        self.safe_nav_words = {_norm(w) for w in cfg.safe_nav_words if w}
        self.allowed_labels = {_norm(w) for w in cfg.allowed_button_labels if w}
        self.price_re = cfg.compiled_price()
        self.blocked_patterns = cfg.compiled_blocked()
        self.quantity_words = [_norm(w) for w in QUANTITY_WORDS]
        self.password_words = [_norm(w) for w in PASSWORD_WORDS]
        self.payment_instruction_words = [_norm(w) for w in PAYMENT_INSTRUCTION_WORDS]
        self.cancel_words = [_norm(w) for w in CANCEL_WORDS]
        self.input_prompt_words = [_norm(w) for w in INPUT_PROMPT_WORDS]

    # ------------------------------------------------------------------ экран
    def screen_context(self, screen_text: str) -> dict:
        raw_text = screen_text or ""
        t = _norm(raw_text)
        return {
            "is_checkout": any(w in t for w in self.checkout_words),
            "has_wallet": any(rx.search(raw_text) or rx.search(t) for rx in WALLET_REGEXES),
            "has_payment_instruction": any(w in t for w in self.payment_instruction_words),
            "has_price": bool(self.price_re.search(raw_text) or self.price_re.search(t)),
            "has_quantity": any(w in t for w in self.quantity_words),
            "password_required": any(w in t for w in self.password_words),
        }

    def screen_is_sensitive(self, screen_text: str) -> bool:
        ctx = self.screen_context(screen_text)
        return (
            ctx["is_checkout"]
            or ctx["has_wallet"]
            or ctx["has_payment_instruction"]
            or ctx["password_required"]
        )

    # ----------------------------------------------------------------- кнопка
    def button_verdict(
        self,
        label: str,
        button_type: str,
        screen_text: str,
        callback_data: bytes | None = None,
        requires_password: bool = False,
    ) -> tuple[bool, str | None]:
        """(can_press, reason). reason=None -> можно нажимать.

        Жёсткие блоки (requires_password, цена+действие, checkout/payment/
        password-экраны) НЕ обходятся ручным allowlist. Allowlist снимает
        только мягкие блоки по тексту кнопки (danger_word, patterns и т.п.).
        """
        lnorm = _norm(label)

        # --- жёсткие блоки: не override'ятся allowlist -----------------------
        if requires_password:
            return False, "requires_password"

        # Кнопки, которые никогда не активируем (только записываем)
        non_pressable = {"url", "switch_inline", "switch_inline_current", "game",
                         "login_url", "web_app", "user_profile", "request_poll",
                         "request_location", "request_contact", "other"}
        if button_type in non_pressable:
            return False, f"button_type:{button_type}_not_activated"

        if not lnorm:
            return False, "empty_label"

        # Цена + слово-действие в одной кнопке — самое опасное
        if self.price_re.search(lnorm) and any(
                w and w in lnorm for w in self.danger_words):
            return False, "price_with_action_word"

        ctx = self.screen_context(screen_text)
        known_purpose = (
            any(bw and bw in lnorm for bw in self.back_words)
            or lnorm in self.safe_nav_words
            or lnorm in self.allowed_labels
        )
        # Emoji-only кнопка неизвестного назначения на чувствительном экране
        if (is_emoji_only(label) and not known_purpose
                and (ctx["has_price"] or self.screen_is_sensitive(screen_text))):
            return False, "emoji_only_on_sensitive_screen"

        if ctx["is_checkout"]:
            return False, "checkout_screen"
        if ctx["has_wallet"] or ctx["has_payment_instruction"]:
            return False, "payment_screen"
        if ctx["password_required"]:
            return False, "password_required"
        # Проверка опасных действий внутри callback_data payload (проверяется ДО allowlist)
        if callback_data:
            cb_text = ""
            if isinstance(callback_data, (bytes, bytearray)):
                cb_text = callback_data.decode("utf-8", errors="ignore")
            elif isinstance(callback_data, str):
                cb_text = callback_data
            cbnorm = _norm(cb_text)
            cb_danger = next((w for w in self.danger_words if w and w in cbnorm), None)
            if cb_danger:
                return False, f"danger_callback_word:{cb_danger}"
            for pat in self.blocked_patterns:
                if pat.search(cbnorm):
                    return False, f"blocked_pattern_in_callback:{pat.pattern}"

        # --- ручной allowlist: снимает мягкие блоки по тексту кнопки ---------
        if lnorm in self.allowed_labels:
            return True, None

        # --- мягкие блоки ------------------------------------------------------
        danger_hit = next((w for w in self.danger_words if w and w in lnorm), None)
        if danger_hit:
            return False, f"danger_word:{danger_hit}"

        for pat in self.blocked_patterns:
            if pat.search(lnorm):
                return False, f"blocked_pattern:{pat.pattern}"

        if ctx["has_price"] and ctx["has_quantity"] and not known_purpose:
            return False, "quantity_total_unknown_action"

        return True, None

    def classify_buttons(self, buttons: list, screen_text: str) -> list:
        """Проставляет blocked_reason каждой кнопке (list of ButtonRef)."""
        for b in buttons:
            can, reason = self.button_verdict(
                b.label, b.button_type, screen_text, b.callback_data,
                requires_password=getattr(b, "requires_password", False),
            )
            b.blocked_reason = reason if not can else None
        return buttons

    # ------------------------------------------------------------------ misc
    def is_back(self, label: str) -> bool:
        lnorm = _norm(label)
        return any(bw and bw in lnorm for bw in self.back_words)

    def find_back_button(self, buttons: Iterable):
        """Первая pressable кнопка возврата (blocked_reason is None)."""
        for b in buttons:
            if self.is_back(b.label) and not b.blocked_reason:
                return b
        return None

    def requires_input_hint(self, text: str, has_force_reply: bool) -> bool:
        if has_force_reply:
            return True
        t = (text or "").strip()
        if not t:
            return False
        return t.endswith(("?", ":", "："))

    def screen_requires_input(
        self, text: str, has_force_reply: bool,
        pressable_labels: list[str] | None = None,
    ) -> bool:
        """Экран ожидает текстовый ввода от пользователя.

        Признаки: ForceReply; текст-вопрос с ?/:
        на конце; ИЛИ текст похож на запрос ввода (введите/send/…),
        а все доступные кнопки — только Cancel/Back (бот ждёт текст,
        предлагая лишь отмену).
        """
        labels = [_norm(l) for l in (pressable_labels or []) if _norm(l)]
        exit_like = self.back_words + self.cancel_words
        has_nav_buttons = any(not any(w and w in l for w in exit_like) for l in labels)

        # Если на экране есть реальные навигационные кнопки выбора — это не блокирующий ввод текста
        if has_nav_buttons and not has_force_reply:
            return False

        if self.requires_input_hint(text, has_force_reply):
            return True
        t = _norm(text or "")
        if not t:
            return False
        promptish = any(w in t for w in (self.input_prompt_words))
        if not promptish:
            return False
        if not labels:
            return True  # запрос ввода без кнопок
        return all(any(w and w in l for w in exit_like) for l in labels)

    # -------------------------------------------------------- manual answers
    @staticmethod
    def manual_answer(manual_answers: dict, bot: str, screen_text: str) -> str | None:
        bot_cfg = manual_answers.get(bot) or manual_answers.get(bot.lower())
        if not bot_cfg:
            return None
        for entry in bot_cfg.get("screens", []):
            m = entry.get("match", "")
            if not m:
                continue
            if entry.get("match_type") == "regex":
                try:
                    if re.search(m, screen_text or ""):
                        return entry.get("answer")
                except re.error:
                    continue
            else:
                if m.strip() == (screen_text or "").strip():
                    return entry.get("answer")
        return None
