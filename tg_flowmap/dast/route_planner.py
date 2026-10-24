"""Планировщик маршрутов (Route Planner).

Поддерживаемые стратегии:
- frontier_strategy:
  - "graph_locality" (по умолчанию): прямое действие -> локальный Dijkstra -> recovery /start.
  - "graph_only": перемещение исключительно по известным рёбрам графа без recovery /start.
  - "bfs": приоритет экранам с наименьшей глубиной.
  - "dfs": приоритет экранам с наибольшей глубиной.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .navigation_graph import EdgeInfo, NavigationGraph


@dataclass
class NavigationPlan:
    plan_type: str  # "direct" | "local_path" | "recovery_start" | "exhausted"
    target_screen_id: str | None = None
    target_action_id: str | None = None
    path_edges: list[EdgeInfo] = field(default_factory=list)
    recovery_path_steps: list[dict] = field(default_factory=list)
    estimated_cost: float = 0.0
    reason: str = ""


class RoutePlanner:
    def __init__(
        self,
        bot: str,
        graph: NavigationGraph,
        recovery_start_cost: float = 3.0,
        edge_confidence_threshold: float = 0.6,
        max_replans_per_target: int = 2,
        frontier_strategy: str = "graph_locality",
    ):
        self.bot = bot
        self.graph = graph
        self.recovery_start_cost = recovery_start_cost
        self.edge_confidence_threshold = edge_confidence_threshold
        self.max_replans_per_target = max_replans_per_target
        self.frontier_strategy = frontier_strategy
        self.replan_counts: dict[str, int] = {}

    def plan_next_step(
        self,
        current_screen_id: str | None,
        unexplored_actions_by_screen: dict[str, list[dict | Any]],
        known_routes: list[dict | Any] | None = None,
    ) -> NavigationPlan:
        """Выбирает следующую цель и способ её достижения с учётом настроенной стратегии."""
        screens_with_work = {
            sid: actions for sid, actions in unexplored_actions_by_screen.items()
            if actions and self.replan_counts.get(sid, 0) < self.max_replans_per_target
        }

        if not screens_with_work:
            return NavigationPlan(plan_type="exhausted", reason="все доступные действия исследованы или исчерпали лимит попыток")

        # 1. Если на текущем экране есть неисследованные действия — исследуем прямо здесь
        if current_screen_id and current_screen_id in screens_with_work:
            act = screens_with_work[current_screen_id][0]
            act_id = act.get("action_id") if isinstance(act, dict) else getattr(act, "action_id", None)
            return NavigationPlan(
                plan_type="direct",
                target_screen_id=current_screen_id,
                target_action_id=act_id,
                estimated_cost=0.0,
                reason="прямое действие на текущем экране",
            )

        # 2. Ищем ближайший экран в графе с доступной работой
        if current_screen_id:
            nearest = self.graph.find_nearest_screen_with_targets(
                current_screen_id,
                set(screens_with_work.keys()),
                min_confidence=self.edge_confidence_threshold,
            )
            if nearest:
                target_sid, path_edges, cost = nearest
                if cost <= self.recovery_start_cost or self.frontier_strategy == "graph_only":
                    act = screens_with_work[target_sid][0]
                    act_id = act.get("action_id") if isinstance(act, dict) else getattr(act, "action_id", None)
                    return NavigationPlan(
                        plan_type="local_path",
                        target_screen_id=target_sid,
                        target_action_id=act_id,
                        path_edges=path_edges,
                        estimated_cost=cost,
                        reason=f"локальный переход в графе ({len(path_edges)} шагов)",
                    )

        # 3. Если стратегия graph_only — recovery /start запрещён
        if self.frontier_strategy == "graph_only":
            return NavigationPlan(
                plan_type="exhausted",
                reason="graph_only: локальный путь до оставшихся экранов не найден",
            )

        # 4. Локальный путь не найден или превышает recovery_start_cost -> recovery через /start
        # Сортируем экраны-кандидаты в зависимости от frontier_strategy
        candidate_sids = list(screens_with_work.keys())
        route_depth_map = {}
        route_path_map = {}
        if known_routes:
            for r in known_routes:
                r_sid = r.get("screen_id") if isinstance(r, dict) else getattr(r, "screen_id", None)
                if r_sid:
                    route_depth_map[r_sid] = r.get("depth", 0) if isinstance(r, dict) else getattr(r, "depth", 0)
                    route_path_map[r_sid] = r.get("path", []) if isinstance(r, dict) else getattr(r, "path", [])

        if self.frontier_strategy == "bfs":
            candidate_sids.sort(key=lambda s: route_depth_map.get(s, 0))
        elif self.frontier_strategy == "dfs":
            candidate_sids.sort(key=lambda s: -route_depth_map.get(s, 0))

        target_sid = candidate_sids[0]
        act = screens_with_work[target_sid][0]
        act_id = act.get("action_id") if isinstance(act, dict) else getattr(act, "action_id", None)
        path_steps = route_path_map.get(target_sid, [])

        return NavigationPlan(
            plan_type="recovery_start",
            target_screen_id=target_sid,
            target_action_id=act_id,
            recovery_path_steps=path_steps or [],
            estimated_cost=self.recovery_start_cost,
            reason="восстановление позиции через /start",
        )

    def record_replan_failure(self, screen_id: str) -> int:
        """Фиксирует неудачную попытку навигации до целевого экрана."""
        self.replan_counts[screen_id] = self.replan_counts.get(screen_id, 0) + 1
        return self.replan_counts[screen_id]

    def clear_replan_failures(self, screen_id: str) -> None:
        """Сбрасывает счётчик неудачных попыток для целевого экрана при успешной навигации."""
        self.replan_counts.pop(screen_id, None)
