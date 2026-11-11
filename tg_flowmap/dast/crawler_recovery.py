from __future__ import annotations

import logging
from typing import Any

from .crawler_helpers import AbortScan, _outcome_event_type, mask_secret
from .fingerprint import match_button_instance

logger = logging.getLogger(__name__)


class CrawlerRecoveryMixin:
    """Mixin implementing recovery navigation, path replay, stale marking, and input answering."""

    async def _return_to_screen(
        self, target_screen_id: str, path: list[dict], route_id: str | None = None,
    ) -> bool:
        target = self.state.get_screen(self.bot, target_screen_id)
        if target is None:
            return False

        # 1) Быстрая попытка: локальный путь через граф
        if self._current_msg is not None and self._current_screen_id:
            local_path = self.graph.find_shortest_path(
                self._current_screen_id, target_screen_id, min_confidence=0.2
            )
            if local_path is not None and 0 < len(local_path) <= self.cfg.recovery_start_cost:
                ok = await self._execute_local_path(local_path)
                if ok and self._current_screen_id == target_screen_id:
                    self.metrics.successful_local_returns += 1
                    self.metrics.avoided_replays += 1
                    self.metrics.estimated_actions_saved += max(0, len(path) + 1 - len(local_path))
                    self.state.metric_incr(self.bot, "successful_local_returns", 1)
                    self.state.metric_incr(self.bot, "avoided_replays", 1)
                    return True

            # 2) Попытка нажать кнопку Back с текущего экрана (эвристика возврата)
            cur_buttons = self.state.buttons_for_screen(self.bot, self._current_screen_id)
            back_btn = self.safety.find_back_button(cur_buttons)
            if back_btn is not None:
                cur_instances = []
                if self._current_msg_rowid:
                    cur_instances = self.state.button_instances_for_message(self._current_msg_rowid)
                if not cur_instances:
                    cur_instances = self.state.button_instances_for_screen(self.bot, self._current_screen_id)

                matched_inst, conf, _ = match_button_instance(back_btn, cur_instances)
                if matched_inst is not None and conf >= 0.8:
                    prev_screen_id = self._current_screen_id
                    btn_to_press = self.executor._to_button_ref(matched_inst, self._current_msg.id)
                    outcome = await self.navigator.press_button(btn_to_press, self._current_msg.id)
                    self._bump_action()
                    if outcome.message is not None:
                        ref, _, rowid = await self._observe(
                            outcome.message, _outcome_event_type(outcome.kind),
                            target["depth_min"], None, [], None, None,
                            create_route=False)
                        # Регистрируем наблюдавшийся переход с каноничным action_id
                        act_candidates = self.state.actions_for_screen(self.bot, prev_screen_id)
                        matched_act = next(
                            (a for a in act_candidates if a["row"] == back_btn.row and a["col"] == back_btn.col),
                            None,
                        )
                        rec_action_id = matched_act["action_id"] if matched_act else (btn_to_press.button_fp or "act_back")
                        self.graph.record_transition(
                            prev_screen_id,
                            rec_action_id,
                            ref.screen_id,
                            outcome.kind,
                            success=True,
                        )
                        self._set_position(ref.screen_id, outcome.message, rowid)
                        if ref.fingerprint == target["fingerprint"]:
                            self.metrics.successful_local_returns += 1
                            self.metrics.avoided_replays += 1
                            self.metrics.estimated_actions_saved += max(0, len(path) + 1 - 1)
                            self.state.metric_incr(self.bot, "successful_local_returns", 1)
                            self.state.metric_incr(self.bot, "avoided_replays", 1)
                            return True

                        # Если после Back оказались на промежуточном экране (например, Catalog),
                        # проверяем, знает ли граф путь отсюда до target_screen_id
                        next_path = self.graph.find_shortest_path(ref.screen_id, target_screen_id, min_confidence=0.2)
                        if next_path is not None and 0 < len(next_path) <= self.cfg.recovery_start_cost:
                            ok_next = await self._execute_local_path(next_path)
                            if ok_next and self._current_screen_id == target_screen_id:
                                self.metrics.successful_local_returns += 1
                                self.metrics.avoided_replays += 1
                                self.state.metric_incr(self.bot, "successful_local_returns", 1)
                                self.state.metric_incr(self.bot, "avoided_replays", 1)
                                return True
                else:
                    logger.warning(
                        f"Пропуск возврата по кнопке {back_btn.label!r}: актуальный экземпляр не найден или низкая уверенность ({conf:.2f} < 0.8)"
                    )

        # 3) Полный replay: /start + путь
        self.metrics.recovery_start_count += 1
        self.state.metric_incr(self.bot, "recovery_start_count", 1)
        return await self._replay_path(target_screen_id, path, route_id)

    async def _replay_path(
        self, target_screen_id: str, path: list[dict], route_id: str | None,
    ) -> bool:
        """Возврат через /start + повтор пути с использованием актуальных button instances."""
        restarts = self.state.progress_incr(self.bot, "restarts")
        if restarts > self.cfg.max_restarts_per_bot:
            raise AbortScan("max_restarts_per_bot reached")
        action_id = await self.logger.start_action(
            self.bot, "replay", {"target": target_screen_id, "steps": len(path)})
        try:
            outcome = await self.navigator.send_start()
            self._bump_action()
            if outcome.message is None:
                await self.logger.finish_action(
                    action_id, self.bot, "error", error="нет ответа на /start")
                return False
            nav_res = await self._process_start_outcome(outcome)
            if nav_res is None:
                await self.logger.finish_action(
                    action_id, self.bot, "error", error="нет валидных сообщений на /start")
                return False
            nav_msg, nav_ref, nav_rowid = nav_res
            self._set_position(nav_ref.screen_id, nav_msg, nav_rowid)
            if not path:
                ok = nav_ref.screen_id == target_screen_id
                if ok:
                    await self.logger.finish_action(action_id, self.bot, "success")
                else:
                    await self._mark_stale(
                        route_id, action_id, "корневой экран не совпал при replay")
                return ok
            for i, step in enumerate(path):
                expected_screen = step["screen_id"]
                if self._current_screen_id == expected_screen:
                    continue
                if step.get("step_type") == "text":
                    # шаг пути — текстовый ответ (manual answer)
                    self._bump_action()
                    self.metrics.text_answers_sent += 1
                    self.state.metric_incr(self.bot, "text_answers_sent", 1)
                    outcome = await self.navigator.send_text(
                        step.get("text") or "", why="replay")
                    if outcome.message is None:
                        await self._mark_stale(
                            route_id, action_id, f"шаг {i}: нет ответа на текст")
                        return False
                    ref, _, rowid = await self._observe(
                        outcome.message, _outcome_event_type(outcome.kind),
                        i + 1, None, path[:i], step.get("action"), None,
                        create_route=False)
                    if ref.screen_id != expected_screen:
                        await self._mark_stale(
                            route_id, action_id,
                            f"шаг {i}: несовпадение экрана после текста "
                            f"({ref.screen_id} != {expected_screen})")
                        return False
                    self._set_position(ref.screen_id, outcome.message, rowid)
                    continue

                # Получаем актуальные button instances текущей версии сообщения
                cur_instances = []
                if self._current_msg_rowid:
                    cur_instances = self.state.button_instances_for_message(self._current_msg_rowid)
                if not cur_instances:
                    cur_instances = self.state.button_instances_for_screen(self.bot, self._current_screen_id)

                matched_inst, conf, _ = match_button_instance(step, cur_instances)
                btn = None
                if matched_inst is not None and conf >= 0.8:
                    btn = self.executor._to_button_ref(matched_inst, self._current_msg.id)
                else:
                    # Fallback сопоставление по метке
                    cur_buttons = self.state.buttons_for_screen(self.bot, self._current_screen_id)
                    for cand in cur_buttons:
                        if (cand.label == step.get("action") or cand.label == step.get("label")) and not cand.blocked_reason:
                            m_inst, m_conf, _ = match_button_instance(cand, cur_instances)
                            if m_inst is not None and m_conf >= 0.8:
                                btn = self.executor._to_button_ref(m_inst, self._current_msg.id)
                            else:
                                btn = cand
                            break

                if btn is None:
                    await self._mark_stale(route_id, action_id,
                                           f"кнопка шага {i} не найдена в актуальных instances сообщения")
                    return False
                self._bump_action()
                if btn.button_type == "callback":
                    self.metrics.callbacks_pressed += 1
                    self.state.metric_incr(self.bot, "callbacks_pressed", 1)
                elif btn.button_type == "reply":
                    self.metrics.reply_buttons_pressed += 1
                    self.state.metric_incr(self.bot, "reply_buttons_pressed", 1)
                outcome = await self.navigator.press_button(
                    btn, self._current_msg.id)
                if outcome.message is None:
                    await self._mark_stale(
                        route_id, action_id, f"шаг {i}: нет ответа на нажатие")
                    return False
                ref, _, rowid = await self._observe(
                    outcome.message, _outcome_event_type(outcome.kind), i + 1,
                    None, path[:i], step.get("action"), step.get("button_fp"),
                    create_route=False)
                if ref.screen_id != expected_screen:
                    await self._mark_stale(
                        route_id, action_id,
                        f"шаг {i}: несовпадение экрана ({ref.screen_id} != "
                        f"{expected_screen})")
                    return False
                self._set_position(ref.screen_id, outcome.message, rowid)
            await self.logger.finish_action(action_id, self.bot, "success")
            return True
        except AbortScan:
            await self.logger.finish_action(action_id, self.bot, "error", error="abort")
            raise

    async def _mark_stale(self, route_id: str | None, action_id: str, why: str) -> None:
        if route_id:
            self.state.mark_route_stale(self.bot, route_id)
        self.state.errors_add(self.bot, "replay_mismatch", why)
        await self.logger.finish_action(action_id, self.bot, "error", error=why)

    async def _maybe_answer_input(self, screen_id: str, item: dict | None) -> None:
        """Экран требует ввода: один ответ из manual_answers.json (без повторов)."""
        row = self.state.get_screen(self.bot, screen_id)
        if not row or not row["requires_input"]:
            return
        once_key = f"answered:{screen_id}"
        if self.state.progress_get(self.bot, once_key, "") == "1":
            return
        msg_row = self.state._query_one(
            "SELECT raw_text FROM messages WHERE bot=? AND screen_id=? "
            "ORDER BY id DESC LIMIT 1", (self.bot, screen_id))
        text = msg_row["raw_text"] if msg_row else ""
        answer = self.safety.manual_answer(self.manual_answers, self.bot, text or "")
        if not answer:
            return
        self.state.progress_set(self.bot, once_key, "1")
        route_id = (item or {}).get("route_id")
        base_path = list((item or {}).get("path") or [])
        for r in self.state.routes_all(self.bot):
            if r["screen_id"] == screen_id:
                base_path = list(r["path"])
                break
        outcome = await self.navigator.send_text(answer, why="manual_answer")
        self._bump_action()
        self.metrics.text_answers_sent += 1
        self.state.metric_incr(self.bot, "text_answers_sent", 1)
        if outcome.message is not None:
            masked = f"manual answer: {mask_secret(answer)}"
            ref, _, rowid = await self._observe(
                outcome.message, _outcome_event_type(outcome.kind),
                row["depth_min"] + 1, route_id, base_path, masked, None,
                create_route=True,
                entry_extra={"step_type": "text", "text": answer})
            self.state.add_transition(
                self.bot, screen_id, ref.screen_id, masked, "manual_answer",
                outcome.kind, None, route_id, None, rowid)
            self._set_position(ref.screen_id, outcome.message, rowid)
