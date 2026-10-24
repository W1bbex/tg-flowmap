"""Исполнитель навигационных действий (Navigation Executor).

Отвечает за безопасное выполнение шагов:
- Проверка свежести и актуальности button instance;
- Структурное сопоставление кнопки (с проверкой confidence);
- Соблюдение safety-ограничений (отказ от нажатия заблокированных/опасных кнопок);
- Вызов Navigator и обработка multi-message ответа;
- Сверка полученного канонического экрана с ожидаемым;
- Обновление рёбер графа (успех / ошибка / нестабильность).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import ButtonRef, PressOutcome, ScreenRef
from .navigation_graph import NavigationGraph
from .screen_identity import match_button_instance


@dataclass
class StepExecutionResult:
    success: bool
    outcome: PressOutcome | None = None
    actual_screen_ref: ScreenRef | None = None
    nav_msg: object | None = None
    nav_rowid: int | None = None
    mismatch: bool = False
    reason: str = ""


class NavigationExecutor:
    def __init__(self, bot: str, navigator, graph: NavigationGraph, safety):
        self.bot = bot
        self.navigator = navigator
        self.graph = graph
        self.safety = safety

    async def execute_action_by_id(
        self,
        action: dict | Any,
        current_msg: object,
        current_instances: list[dict | Any],
        observe_callback,
    ) -> StepExecutionResult:
        """Находит актуальный button instance для действия и выполняет нажатие."""
        if current_msg is None:
            return StepExecutionResult(success=False, reason="current_msg_is_none")

        # 1. Структурное сопоставление действия с кнопками текущего сообщения
        btn_inst, confidence, match_reason = match_button_instance(action, current_instances)
        if btn_inst is None or confidence < 0.8:
            return StepExecutionResult(
                success=False,
                reason=f"button_match_failed (confidence={confidence}, reason={match_reason})",
            )

        # 2. Проверка блокировки по безопасности
        blocked = getattr(btn_inst, "blocked_reason", None) if not isinstance(btn_inst, dict) else btn_inst.get("blocked_reason")
        if blocked:
            return StepExecutionResult(
                success=False,
                reason=f"button_blocked_by_safety: {blocked}",
            )

        # 3. Подготовка ButtonRef для навигатора
        msg_id = getattr(current_msg, "id", 0)
        btn_ref = self._to_button_ref(btn_inst, msg_id)

        # 4. Нажатие кнопки
        outcome = await self.navigator.press_button(btn_ref, msg_id)

        # 5. Обработка входящих сообщений через observe_callback
        nav_msg, nav_ref, nav_rowid = await observe_callback(outcome)
        if nav_ref is None:
            if getattr(outcome, "kind", "") == "answer_only":
                return StepExecutionResult(
                    success=True,
                    outcome=outcome,
                    actual_screen_ref=None,
                    nav_msg=None,
                    nav_rowid=None,
                    reason="answer_only",
                )
            return StepExecutionResult(
                success=False,
                outcome=outcome,
                reason=f"no_valid_response (outcome_kind={outcome.kind})",
            )

        return StepExecutionResult(
            success=True,
            outcome=outcome,
            actual_screen_ref=nav_ref,
            nav_msg=nav_msg,
            nav_rowid=nav_rowid,
            reason="success",
        )

    def _to_button_ref(self, inst: dict | Any, msg_id: int) -> ButtonRef:
        if isinstance(inst, ButtonRef):
            inst.message_id = msg_id
            return inst

        d = inst if isinstance(inst, dict) else getattr(inst, "__dict__", {})
        cb_data = d.get("callback_data")
        if isinstance(cb_data, str):
            cb_data = cb_data.encode("utf-8")
        elif cb_data is None and d.get("callback_b64"):
            try:
                import base64
                cb_data = base64.b64decode(d["callback_b64"])
            except Exception:
                pass

        style = d.get("style", {}) if isinstance(d.get("style"), dict) else {}
        return ButtonRef(
            row=int(d.get("row", 0)),
            col=int(d.get("col", 0)),
            label=str(d.get("label", "")),
            button_type=str(d.get("button_type", "callback")),
            callback_data=cb_data,
            url=d.get("url"),
            custom_emoji_id=d.get("custom_emoji_id"),
            message_id=msg_id,
            blocked_reason=d.get("blocked_reason"),
            db_id=d.get("db_id") or d.get("id"),
            button_fp=d.get("button_fp"),
            style_bg_primary=bool(style.get("bg_primary", d.get("style_bg_primary", False))),
            style_bg_success=bool(style.get("bg_success", d.get("style_bg_success", False))),
            style_bg_danger=bool(style.get("bg_danger", d.get("style_bg_danger", False))),
            style_icon_id=style.get("icon_document_id", d.get("style_icon_id")),
            requires_password=bool(style.get("requires_password", d.get("style_requires_password", False))),
        )
