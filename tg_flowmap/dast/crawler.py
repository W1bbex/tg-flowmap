"""State-aware graph-first обходчик Telegram-ботов.

Ключевые принципы:
- Граф-первый подход (Graph-First Locality Navigation): исследование соседних веток
  через локальный переход (Back/Меню) по графу вместо постоянного /start с корня.
- Callback-data opaque: токены кнопок никогда не считаются семантическим маршрутом;
  каждая версия сообщения хранит собственные button instances; random hash не
  создаёт новый канонический экран.
- Безопасность: блокировка покупок, платежей, подтверждений, опасных reply-кнопок.
- Multi-message: поддержка цепочек сообщений (Processing -> Actual menu) во всех сценариях.
- Полный учёт action budget для всех типов действий.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .capture import capture_message, extract_buttons
from .config import Config
from .fingerprint import (
    button_fingerprint,
    match_button_instance,
    normalize_text,
    route_fingerprint,
    route_id_of,
    screen_fingerprint,
    screen_id_of,
    stable_action_id,
)
from .models import ButtonRef, CrawlerMetrics, PressOutcome, ScreenRef
from .navigation_executor import NavigationExecutor
from .navigation_graph import NavigationGraph
from .route_planner import RoutePlanner
from .safety import SafetyFilter
from .state import State
from .timeline_log import ActionLogger


class AbortScan(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _outcome_event_type(kind: str) -> str:
    return kind if kind in ("new", "edit") else "snapshot"


def _msg_has_buttons(msg) -> bool:
    rm = getattr(msg, "reply_markup", None)
    rows = getattr(rm, "rows", None) or []
    return any(getattr(r, "buttons", None) for r in rows)


def mask_secret(text: str) -> str:
    """Manual answers — секреты: в публичные отчёты только факт и длина."""
    return f"[скрыто, длина {len(text or '')}]"


class BotCrawler:
    def __init__(
        self,
        cfg: Config,
        state: State,
        logger: ActionLogger,
        safety: SafetyFilter,
        navigator,
        manual_answers: dict,
        bot: str,
        media_dir: Path | None = None,
    ):
        self.cfg = cfg
        self.state = state
        self.logger = logger
        self.safety = safety
        self.navigator = navigator
        self.manual_answers = manual_answers
        self.bot = bot
        self.media_dir = media_dir
        self.volatile = cfg.compiled_volatile()
        self.stopped = False
        self._current_screen_id: str | None = None
        self._current_msg = None
        self._current_msg_rowid: int | None = None
        self._consecutive_errors = 0

        # Модули новой архитектуры навигации
        self.graph = NavigationGraph(self.bot, self.state)
        self.planner = RoutePlanner(
            self.bot,
            self.graph,
            recovery_start_cost=getattr(cfg, "recovery_start_cost", 3.0),
            edge_confidence_threshold=getattr(cfg, "edge_confidence_threshold", 0.6),
            max_replans_per_target=getattr(cfg, "max_replans_per_target", 2),
            frontier_strategy=getattr(cfg, "frontier_strategy", "graph_locality"),
        )
        self.executor = NavigationExecutor(self.bot, self.navigator, self.graph, self.safety)
        self.metrics = CrawlerMetrics()
        self.action_retries: dict[str, int] = {}
        self._load_metrics()

    def _load_metrics(self) -> None:
        m = self.state.metrics_all(self.bot)
        for k, v in m.items():
            if hasattr(self.metrics, k):
                setattr(self.metrics, k, v)

    # ------------------------------------------------------------ public API
    async def run(self, resume: bool = False) -> str:
        """Запуск обхода. Возвращает финальный статус бота
        (done | limit_reached | paused | error)."""
        self.state.set_bot_status(self.bot, "running")
        status = "done"
        try:
            if resume:
                # восстановление после аварии: прерванные действия и позиции
                self.state.mark_stale_pending(self.bot)
                self.state.requeue_running_frontier(self.bot)
            has_screens = bool(self.state.screens_all(self.bot))
            if not has_screens or not resume:
                started = await self._start_conversation()
                if not started:
                    self.state.set_bot_status(self.bot, "error", "нет ответа на /start")
                    return "error"
            await self._loop()
        except AbortScan as e:
            if e.reason == "max_actions_per_bot reached":
                status = (
                    "limit_reached"
                    if (self.state.frontier_active_count(self.bot) > 0 or bool(self.state.unexplored_actions_all(self.bot)))
                    else "done"
                )
                self.state.set_bot_status(self.bot, status)
                return status
            status = "error"
            self.state.errors_add(self.bot, "abort", e.reason)
            self.state.set_bot_status(self.bot, "error", e.reason)
            return status
        except Exception as e:  # noqa: BLE001 — краш обхода не должен ронять соседнего бота
            self.state.errors_add(self.bot, "crash", f"{type(e).__name__}: {e}")
            self.state.set_bot_status(self.bot, "error", str(e))
            return "error"
        if self.stopped:
            status = "paused"
        elif status == "done" and self.state.frontier_active_count(self.bot) > 0:
            status = "paused"
        self.state.set_bot_status(self.bot, status)
        return status

    def stop(self) -> None:
        self.stopped = True

    # ------------------------------------------------------------- действия
    def _actions(self) -> int:
        return int(self.state.progress_get(self.bot, "actions", "0"))

    def _bump_action(self) -> int:
        """Считает КАЖДОЕ Telegram-действие в общем бюджете."""
        self._consecutive_errors = 0
        n = self.state.progress_incr(self.bot, "actions")
        self.metrics.telegram_actions += 1
        self.state.metric_incr(self.bot, "telegram_actions", 1)
        if n > self.cfg.max_actions_per_bot:
            raise AbortScan("max_actions_per_bot reached")
        return n

    # ------------------------------------------------------------- capture
    def _capture_and_fp(self, msg, event_type: str):
        capture = capture_message(msg, self.bot, event_type, self.state)
        buttons = extract_buttons(getattr(msg, "reply_markup", None), capture.message_id)
        self.safety.classify_buttons(buttons, capture.raw_text)
        fp = screen_fingerprint(
            capture.raw_text,
            [e.to_dict() for e in capture.entities],
            [b.to_dict() for b in buttons],
            [m.to_dict() for m in capture.media],
            self.volatile,
            has_force_reply=capture.has_force_reply,
        )
        return capture, buttons, fp

    async def _observe(
        self,
        msg,
        event_type: str,
        depth: int,
        parent_route_id: str | None,
        parent_path: list[dict],
        entry_action: str | None,
        entry_button_fp: str | None,
        create_route: bool = True,
        entry_extra: dict | None = None,
    ) -> tuple[ScreenRef, bool, int]:
        """Фиксирует экран: canonical screen (upsert) + версионное сообщение +
        button instances + стабильные действия + маршрут."""
        capture, buttons, fp = self._capture_and_fp(msg, event_type)
        screen_id = screen_id_of(fp)
        pressable = [
            b for b in buttons
            if not b.blocked_reason and b.button_type in ("callback", "reply")
        ]
        requires_input = self.safety.screen_requires_input(
            capture.raw_text, capture.has_force_reply,
            [b.label for b in pressable])
        existing = self.state.get_screen_by_fp(self.bot, fp)
        created = existing is None
        if created:
            _, created_flag = self.state.upsert_screen(
                self.bot, screen_id, fp, depth,
                normalize_text(capture.raw_text, self.volatile), requires_input)
            created = created_flag
        elif requires_input:
            self.state.set_screen_requires_input(self.bot, screen_id, True)

        # Добавляем узел в граф
        self.graph.add_node(screen_id)

        # Медиа скачиваем на версию:
        if capture.media and self.navigator is not None and self.media_dir is not None:
            primary_media = None
            for m in capture.media:
                if m.kind != "web_preview":
                    primary_media = m
                    break
            if primary_media is not None:
                primary_media.file_path = await self.navigator.download_media(
                    msg, self.media_dir)

        msg_rowid = self.state.insert_message(capture, screen_id)

        # КАЖДАЯ версия сообщения сохраняет свои button instances и регистрирует stable_actions
        self.state.insert_button_instances(self.bot, screen_id, msg_rowid, buttons)
        if created:
            fps = [button_fingerprint(b.label, b.callback_hex, b.url, b.button_type)
                   for b in buttons]
            self.state.insert_buttons(self.bot, screen_id, msg_rowid, buttons, fps)

        if create_route:
            path_steps = list(parent_path)
            if entry_action is not None:
                step = {"screen_id": screen_id, "action": entry_action,
                        "button_fp": entry_button_fp or ""}
                if entry_extra:
                    step.update(entry_extra)
                path_steps = path_steps + [step]
            rfp = route_fingerprint(fp, parent_route_id, entry_action)
            route_id = route_id_of(rfp)
            self.state.upsert_route(
                self.bot, route_id, rfp, parent_route_id, screen_id,
                path_steps, depth)
            if created and depth < self.cfg.max_depth and (pressable or requires_input):
                self.state.push_frontier(self.bot, route_id, screen_id, path_steps,
                                         depth)

        if self._current_msg is not None and getattr(msg, "id", None) == getattr(self._current_msg, "id", None):
            self._set_position(screen_id, msg, msg_rowid)

        screen_row = self.state.get_screen_by_fp(self.bot, fp)
        return ScreenRef(
            screen_id=screen_id, fingerprint=fp, depth=depth,
            requires_input=bool(screen_row["requires_input"]) if screen_row
            else requires_input,
        ), created, msg_rowid

    def _set_position(self, screen_id: str, msg, msg_rowid: int | None) -> None:
        self._current_screen_id = screen_id
        self._current_msg = msg
        self._current_msg_rowid = msg_rowid

    def _bump_errors(self) -> None:
        self._consecutive_errors += 1
        if self._consecutive_errors >= self.cfg.max_consecutive_errors:
            raise AbortScan("too many consecutive errors")

    async def _process_start_outcome(
        self, outcome,
    ) -> tuple[object, ScreenRef, int] | None:
        """Единая обработка ответа на /start (primary + extras):
        - принимает PressOutcome;
        - обрабатывает primary и все extra_messages;
        - сохраняет каждое сообщение с его реальным event_type через create_route=False;
        - выбирает навигационное сообщение как последнее сообщение с кнопками, либо последнее;
        - возвращает (nav_msg, nav_ref, nav_rowid);
        - не создаёт ложных routes/frontier."""
        if outcome.message is None:
            return None
        msgs = [(outcome.kind, outcome.message)]
        for kind, m in (getattr(outcome, "extra_messages", None) or []):
            msgs.append((kind, m))
        observed: list[tuple[object, ScreenRef, bool, int]] = []
        for i, (kind, m) in enumerate(msgs):
            entry = "/start" if i == 0 else f"/start (+{i})"
            ref, created, rowid = await self._observe(
                m, _outcome_event_type(kind), 0, None, [], entry, None,
                create_route=False)
            observed.append((m, ref, created, rowid))
        if not observed:
            return None
        # навигационное сообщение: приоритет последнему сообщению с кнопками
        nav_idx = len(observed) - 1
        for i, (m, _ref, _c, _r) in enumerate(observed):
            if _msg_has_buttons(m):
                nav_idx = i
        nav_msg, nav_ref, _created, nav_rowid = observed[nav_idx]
        return nav_msg, nav_ref, nav_rowid

    async def _observe_outcome_for_step(self, outcome, depth: int = 0) -> tuple[object, ScreenRef, int] | None:
        """Обработка multi-message ответа при переходе по графу."""
        if outcome.message is None:
            return None, None, None
        msgs = [(_outcome_event_type(outcome.kind), outcome.message)]
        for kind, m in (getattr(outcome, "extra_messages", None) or []):
            msgs.append((_outcome_event_type(kind), m))
        observed: list[tuple[object, ScreenRef, bool, int]] = []
        for i, (event_type, m) in enumerate(msgs):
            ref, created, rowid = await self._observe(
                m, event_type, depth, None, [], None, None, create_route=False,
            )
            observed.append((m, ref, created, rowid))
        if not observed:
            return None, None, None
        nav_idx = len(observed) - 1
        for i, (m, _ref, _c, _r) in enumerate(observed):
            if _msg_has_buttons(m):
                nav_idx = i
        nav_msg, nav_ref, _created, nav_rowid = observed[nav_idx]
        return nav_msg, nav_ref, nav_rowid

    # ------------------------------------------------------------- сценарий
    async def _start_conversation(self) -> bool:
        outcome = await self.navigator.send_start()
        self._bump_action()
        self.metrics.start_count += 1
        self.state.metric_incr(self.bot, "start_count", 1)
        if outcome.message is None:
            outcome = await self.navigator.send_start()
            self._bump_action()
            self.metrics.start_count += 1
            self.state.metric_incr(self.bot, "start_count", 1)
        if outcome.message is None:
            return False

        nav_res = await self._process_start_outcome(outcome)
        if nav_res is None:
            return False
        nav_msg, nav_ref, nav_rowid = nav_res

        # Создаём ровно один root route для выбранного навигационного экрана
        rfp = route_fingerprint(nav_ref.fingerprint, None, "/start")
        route_id = route_id_of(rfp)
        _, route_created = self.state.upsert_route(
            self.bot, route_id, rfp, None, nav_ref.screen_id, [], 0)

        buttons = self.state.buttons_for_screen(self.bot, nav_ref.screen_id)
        pressable = [
            b for b in buttons
            if not b.blocked_reason and b.button_type in ("callback", "reply")
        ]
        if route_created and (pressable or nav_ref.requires_input):
            self.state.push_frontier(self.bot, route_id, nav_ref.screen_id, [], 0)

        self._set_position(nav_ref.screen_id, nav_msg, nav_rowid)
        return True

    async def _loop(self) -> None:
        visits: dict[str, int] = {}
        failed_targets: set[str] = set()
        nav_mode = getattr(self.cfg, "navigation_mode", "graph")

        while not self.stopped:
            if self._actions() >= self.cfg.max_actions_per_bot:
                raise AbortScan("max_actions_per_bot reached")

            # 1. Обработка очереди frontier
            legacy_item = self.state.pop_frontier(self.bot)
            if legacy_item is not None:
                screen_id = legacy_item["screen_id"]
                visits[screen_id] = visits.get(screen_id, 0) + 1
                if visits[screen_id] > self.cfg.max_same_screen_visits:
                    self.state.finish_frontier(legacy_item["id"], "skipped")
                    continue
                try:
                    positioned = await self._ensure_position(legacy_item)
                    if positioned:
                        await self._explore(legacy_item)
                        self.state.finish_frontier(legacy_item["id"], "done")
                    else:
                        self.state.finish_frontier(legacy_item["id"], "skipped")
                        failed_targets.add(screen_id)
                        self._bump_errors()
                except AbortScan:
                    self.state.requeue_frontier(legacy_item["id"])
                    raise
                continue

            if nav_mode == "legacy":
                return

            # 2. Graph-first locality планирование для оставшихся неисследованных действий
            unexplored = self.state.unexplored_actions_all(self.bot)
            unexplored = {sid: acts for sid, acts in unexplored.items() if sid not in failed_targets}

            if not unexplored:
                return

            plan = self.planner.plan_next_step(
                self._current_screen_id,
                unexplored,
                known_routes=self.state.routes_all(self.bot),
            )

            if plan.plan_type == "exhausted":
                return

            if plan.plan_type == "direct":
                # Действие на текущем экране
                await self._execute_direct_action(plan.target_screen_id, plan.target_action_id)
            elif plan.plan_type == "local_path":
                # Локальный возврат по графу
                ok = await self._execute_local_path(plan.path_edges)
                if ok and self._current_screen_id == plan.target_screen_id:
                    self.planner.clear_replan_failures(plan.target_screen_id)
                    self.metrics.successful_local_returns += 1
                    self.metrics.avoided_replays += 1
                    self.metrics.estimated_actions_saved += max(0, 3 - len(plan.path_edges))
                    self.state.metric_incr(self.bot, "successful_local_returns", 1)
                    self.state.metric_incr(self.bot, "avoided_replays", 1)
                    await self._execute_direct_action(plan.target_screen_id, plan.target_action_id)
                else:
                    fails = self.planner.record_replan_failure(plan.target_screen_id)
                    self.metrics.replans += 1
                    self.state.metric_incr(self.bot, "replans", 1)
                    if fails >= self.cfg.max_replans_per_target:
                        failed_targets.add(plan.target_screen_id)
                        self.state.errors_add(
                            self.bot, "local_path_exhausted",
                            f"локальный переход до экрана {plan.target_screen_id} исчерпал {fails} попыток",
                        )
            elif plan.plan_type == "recovery_start":
                # Recovery через /start
                self.metrics.recovery_start_count += 1
                self.state.metric_incr(self.bot, "recovery_start_count", 1)
                ok = await self._replay_path(plan.target_screen_id, plan.recovery_path_steps, None)
                if ok:
                    self.planner.clear_replan_failures(plan.target_screen_id)
                    await self._execute_direct_action(plan.target_screen_id, plan.target_action_id)
                else:
                    fails = self.planner.record_replan_failure(plan.target_screen_id)
                    self._bump_errors()
                    if fails >= self.cfg.max_replans_per_target:
                        failed_targets.add(plan.target_screen_id)
                        self.state.errors_add(
                            self.bot, "recovery_exhausted",
                            f"целевой экран {plan.target_screen_id} исчерпал {fails} попыток восстановления",
                        )
                    else:
                        self.state.errors_add(
                            self.bot, "transient_recovery_error",
                            f"целевой экран {plan.target_screen_id} попытка восстановления {fails}/{self.cfg.max_replans_per_target}",
                        )

    async def _execute_direct_action(self, screen_id: str, action_id: str | None) -> None:
        """Прямое выполнение действия на текущем экране."""
        if not action_id or self._current_msg is None:
            return

        actions = self.state.actions_for_screen(self.bot, screen_id)
        act = next((a for a in actions if a["action_id"] == action_id), None)
        if not act:
            self.state.mark_action_explored(self.bot, action_id)
            return

        instances = []
        if self._current_msg_rowid:
            instances = self.state.button_instances_for_message(self._current_msg_rowid)
        if not instances:
            instances = self.state.button_instances_for_screen(self.bot, screen_id)

        target_screen_obj = self.state.get_screen(self.bot, screen_id)
        depth = target_screen_obj["depth_min"] if target_screen_obj else 0
        from_rowid = self._current_msg_rowid

        # Выполняем через NavigationExecutor
        exec_res = await self.executor.execute_action_by_id(
            act,
            self._current_msg,
            instances,
            lambda out: self._observe_outcome_for_step(out, depth=depth + 1),
        )

        if not exec_res.success:
            if "blocked" in exec_res.reason:
                self.state.mark_action_explored(self.bot, action_id)
                self.action_retries.pop(action_id, None)
                return

            retries = self.action_retries.get(action_id, 0) + 1
            self.action_retries[action_id] = retries
            self._bump_errors()

            if retries >= self.cfg.max_replans_per_target:
                self.state.mark_action_explored(self.bot, action_id)
                self.planner.record_replan_failure(screen_id)
                self.state.errors_add(
                    self.bot, "action_exhausted",
                    f"действие {action_id} на {screen_id} исчерпало лимит {retries} попыток: {exec_res.reason}",
                )
            else:
                self.state.errors_add(
                    self.bot, "transient_action_error",
                    f"действие {action_id} на {screen_id} попытка {retries}/{self.cfg.max_replans_per_target}: {exec_res.reason}",
                )
            return

        # Успешное выполнение
        self.action_retries.pop(action_id, None)
        self._bump_action()
        if act.get("button_type") == "callback":
            self.metrics.callbacks_pressed += 1
            self.state.metric_incr(self.bot, "callbacks_pressed", 1)
        elif act.get("button_type") == "reply":
            self.metrics.reply_buttons_pressed += 1
            self.state.metric_incr(self.bot, "reply_buttons_pressed", 1)

        dest_sid = exec_res.actual_screen_ref.screen_id if exec_res.actual_screen_ref else screen_id

        # Регистрируем ребро в графе
        self.graph.record_transition(
            source_screen_id=screen_id,
            action_id=action_id,
            destination_screen_id=dest_sid,
            result_type=exec_res.outcome.kind if exec_res.outcome else "edit",
            success=True,
        )

        # Сохраняем в таблицы transitions и callbacks
        b_row = self.state._query_one(
            "SELECT id FROM buttons WHERE bot=? AND screen_id=? AND row=? AND col=?",
            (self.bot, screen_id, act.get("row"), act.get("col"))
        )
        b_db_id = b_row["id"] if b_row else None
        self.state.add_transition(
            self.bot, screen_id, dest_sid, act.get("label", ""), act.get("button_type", ""),
            exec_res.outcome.kind if exec_res.outcome else "edit", b_db_id, None,
            from_rowid, exec_res.nav_rowid,
        )
        if exec_res.outcome and exec_res.outcome.callback is not None and b_db_id is not None:
            self.state.add_callback(
                self.bot, b_db_id, getattr(exec_res.outcome, "action_id", None),
                exec_res.outcome.callback,
            )

        # Сохраняем маршрут для восстановления через recovery/replay
        if dest_sid != screen_id:
            known = [r for r in self.state.routes_all(self.bot) if r.get("screen_id") == screen_id and r.get("status") != "stale"]
            parent_path = known[0]["path"] if known else []
            parent_route_id = known[0]["route_id"] if known else None
            step = {
                "screen_id": dest_sid,
                "action": act.get("label", "") or action_id,
                "button_fp": act.get("button_fp", "") or action_id,
                "step_type": act.get("button_type", "callback"),
                "row": act.get("row"),
                "col": act.get("col"),
                "label": act.get("label", ""),
                "action_id": action_id,
            }
            new_path = parent_path + [step]
            dest_screen = self.state.get_screen(self.bot, dest_sid)
            dest_fp = dest_screen["fingerprint"] if dest_screen else dest_sid
            rfp = route_fingerprint(dest_fp, parent_route_id, action_id)
            new_route_id = route_id_of(rfp)
            self.state.upsert_route(
                self.bot, new_route_id, rfp, parent_route_id, dest_sid,
                new_path, depth + 1,
            )

        self.state.mark_action_explored(self.bot, action_id)
        next_msg = exec_res.nav_msg if exec_res.nav_msg is not None else self._current_msg
        next_rowid = exec_res.nav_rowid if exec_res.nav_rowid is not None else self._current_msg_rowid
        self._set_position(dest_sid, next_msg, next_rowid)

    async def _execute_local_path(self, path_edges: list[Any]) -> bool:
        """Пошаговое прохождение маршрута в графе переходов."""
        for edge in path_edges:
            if self._current_screen_id != edge.source_screen_id or self._current_msg is None:
                return False

            actions = self.state.actions_for_screen(self.bot, edge.source_screen_id)
            act = next((a for a in actions if a["action_id"] == edge.action_id), None)
            if not act:
                # Fallback: поиск по совпадению хэша button_fp или кнопки "Назад"
                act = next(
                    (a for a in actions if edge.action_id in (a.get("action_id", ""), a.get("button_fp", ""))
                     or (edge.action_id == "act_back" and a.get("label", "").lower() in ("назад", "back", "⬅", "◀", "←"))),
                    None,
                )
            if not act:
                self.graph.mark_edge_unstable(edge.source_screen_id, edge.action_id)
                self.metrics.unstable_edges += 1
                self.state.metric_incr(self.bot, "unstable_edges", 1)
                return False

            instances = []
            if self._current_msg_rowid:
                instances = self.state.button_instances_for_message(self._current_msg_rowid)
            if not instances:
                instances = self.state.button_instances_for_screen(self.bot, edge.source_screen_id)

            res = await self.executor.execute_action_by_id(
                act,
                self._current_msg,
                instances,
                lambda out: self._observe_outcome_for_step(out, depth=0),
            )

            if not res.success or (res.actual_screen_ref is None and res.reason != "answer_only"):
                self.graph.mark_edge_unstable(edge.source_screen_id, edge.action_id)
                self.metrics.unstable_edges += 1
                self.state.metric_incr(self.bot, "unstable_edges", 1)
                return False

            self._bump_action()
            next_sid = res.actual_screen_ref.screen_id if res.actual_screen_ref else edge.destination_screen_id
            next_msg = res.nav_msg if res.nav_msg is not None else self._current_msg
            next_rowid = res.nav_rowid if res.nav_rowid is not None else self._current_msg_rowid
            self._set_position(next_sid, next_msg, next_rowid)

            # Проверяем совпадение полученного экрана с ожидаемым
            if next_sid != edge.destination_screen_id:
                self.graph.mark_edge_unstable(edge.source_screen_id, edge.action_id)
                self.metrics.unstable_edges += 1
                self.state.metric_incr(self.bot, "unstable_edges", 1)
                return False

        return True

    async def _ensure_position(self, item: dict) -> bool:
        if self._current_screen_id == item["screen_id"] and self._current_msg is not None:
            return True
        return await self._return_to_screen(item["screen_id"], item["path"],
                                            item.get("route_id"))

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
                btn_to_press = back_btn
                if matched_inst is not None and conf >= 0.8:
                    btn_to_press = self.executor._to_button_ref(matched_inst, self._current_msg.id)

                outcome = await self.navigator.press_button(btn_to_press, self._current_msg.id)
                self._bump_action()
                if outcome.message is not None:
                    ref, _, rowid = await self._observe(
                        outcome.message, _outcome_event_type(outcome.kind),
                        target["depth_min"], None, [], None, None,
                        create_route=False)
                    # Регистрируем наблюдавшийся переход с каноничным action_id
                    act_candidates = self.state.actions_for_screen(self.bot, self._current_screen_id)
                    matched_act = next(
                        (a for a in act_candidates if a["row"] == back_btn.row and a["col"] == back_btn.col),
                        None,
                    )
                    rec_action_id = matched_act["action_id"] if matched_act else (btn_to_press.button_fp or "act_back")
                    self.graph.record_transition(
                        self._current_screen_id,
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

        # 3) Полный replay: /start + путь
        self.metrics.recovery_start_count += 1
        self.state.metric_incr(self.bot, "recovery_start_count", 1)
        return await self._replay_path(target_screen_id, path, route_id)

    async def _explore(self, item: dict) -> None:
        screen_id = item["screen_id"]
        path = item["path"]
        depth = item["depth"]
        buttons = self.state.buttons_for_screen(self.bot, screen_id)
        pressable = [b for b in buttons
                     if not b.blocked_reason and b.button_type in ("callback", "reply")]
        for b in pressable:
            if self.stopped:
                return
            if self.state.button_explored(self.bot, b.db_id):
                continue
            if self._actions() >= self.cfg.max_actions_per_bot:
                raise AbortScan("max_actions_per_bot reached")
            if self._current_screen_id != screen_id or self._current_msg is None:
                ok = await self._return_to_screen(screen_id, path, item.get("route_id"))
                if not ok:
                    self.state.errors_add(
                        self.bot, "replay_failed",
                        f"не удалось вернуться на экран {screen_id} "
                        f"для кнопки {b.label!r}")
                    self._bump_errors()
                    return

            # Получаем актуальные button instances текущей версии сообщения
            cur_instances = []
            if self._current_msg_rowid:
                cur_instances = self.state.button_instances_for_message(self._current_msg_rowid)
            if not cur_instances:
                cur_instances = self.state.button_instances_for_screen(self.bot, screen_id)

            matched_inst, conf, _ = match_button_instance(b, cur_instances)
            btn_to_press = b
            if matched_inst is not None and conf >= 0.8:
                btn_to_press = self.executor._to_button_ref(matched_inst, self._current_msg.id)
                btn_to_press.db_id = b.db_id

            outcome = await self.navigator.press_button(btn_to_press, self._current_msg.id)
            await self._record_press(btn_to_press, item, outcome, depth)
            if outcome.kind == "error":
                self._bump_errors()
            elif outcome.kind in ("edit", "new", "answer_only"):
                self._consecutive_errors = 0
        await self._maybe_answer_input(screen_id, item)

    async def _record_press(self, b: ButtonRef, item: dict, outcome, depth: int) -> None:
        self._bump_action()
        if b.button_type == "callback":
            self.metrics.callbacks_pressed += 1
            self.state.metric_incr(self.bot, "callbacks_pressed", 1)
        elif b.button_type == "reply":
            self.metrics.reply_buttons_pressed += 1
            self.state.metric_incr(self.bot, "reply_buttons_pressed", 1)

        from_rowid = self._current_msg_rowid
        route_id = item.get("route_id")
        path = item["path"]
        act_id = stable_action_id(
            source_screen_id=item["screen_id"],
            row=b.row,
            col=b.col,
            label=b.label,
            button_type=b.button_type,
            style_icon_id=b.style_icon_id,
            requires_password=b.requires_password,
            url=b.url,
        )

        # ВСЕ сообщения ответа (primary + extras) — полноценный capture
        msgs: list[tuple[str, object]] = []
        if outcome.message is not None:
            msgs.append((_outcome_event_type(outcome.kind), outcome.message))
        for kind, m in (getattr(outcome, "extra_messages", None) or []):
            msgs.append((_outcome_event_type(kind), m))

        observed: list[tuple[object, ScreenRef, bool, int]] = []
        for i, (event_type, m) in enumerate(msgs):
            entry = b.label if i == 0 else f"{b.label} (+{i})"
            extra = {
                "step_type": "button",
                "action_id": act_id,
                "row": b.row,
                "col": b.col,
                "label": b.label,
                "button_type": b.button_type,
            } if i == 0 else None
            ref, created, rowid = await self._observe(
                m, event_type, depth + 1, route_id, path,
                entry, act_id if i == 0 else None,
                create_route=True, entry_extra=extra)
            observed.append((m, ref, created, rowid))

        # навигационное сообщение: последнее С кнопками, иначе последнее
        to_screen_id: str | None = None
        to_rowid: int | None = None
        nav_created = False
        if observed:
            nav_idx = len(observed) - 1
            for i, (m, _ref, _c, _r) in enumerate(observed):
                if _msg_has_buttons(m):
                    nav_idx = i
            nav_msg, nav_ref, nav_created, to_rowid = observed[nav_idx]
            to_screen_id = nav_ref.screen_id
            self._set_position(to_screen_id, nav_msg, to_rowid)
        else:
            self._current_msg_rowid = from_rowid

        self.state.add_transition(
            self.bot, item["screen_id"], to_screen_id, b.label, b.button_type,
            outcome.kind, b.db_id, route_id, from_rowid, to_rowid)
        if outcome.callback is not None:
            self.state.add_callback(
                self.bot, b.db_id, getattr(outcome, "action_id", None),
                outcome.callback)

        # Синхронизируем graph edge и mark_action_explored
        if to_screen_id:
            self.graph.record_transition(
                source_screen_id=item["screen_id"],
                action_id=act_id,
                destination_screen_id=to_screen_id,
                result_type=outcome.kind,
                success=(outcome.kind in ("edit", "new", "answer_only")),
            )
        self.state.mark_action_explored(self.bot, act_id)

        if nav_created and to_screen_id:
            await self._maybe_answer_input(to_screen_id, item)

    # ---------------------------------------------------------------- replay
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

    # ---------------------------------------------------------- input-экраны
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
