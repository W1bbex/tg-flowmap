"""Граф переходов между каноническими экранами (Navigation Graph).

- Узлы: Canonical Screens (screen_id);
- Рёбра: (source_screen_id, stable_action_id) -> destination_screen_id;
- Поддержка динамических/нестабильных рёбер (разные outcomes на одно действие);
- Алгоритм Дейкстры для поиска кратчайшего и самого надежного маршрута;
- Вычисление confidence для каждого ребра.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EdgeInfo:
    source_screen_id: str
    action_id: str
    destination_screen_id: str
    result_type: str = "edit"
    observations_count: int = 1
    success_count: int = 1
    failure_count: int = 0
    confidence: float = 1.0
    is_stable: bool = True
    first_observed_at: str = field(default_factory=_utcnow)
    last_observed_at: str = field(default_factory=_utcnow)
    last_success_at: str | None = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        return {
            "source_screen_id": self.source_screen_id,
            "action_id": self.action_id,
            "destination_screen_id": self.destination_screen_id,
            "result_type": self.result_type,
            "observations_count": self.observations_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "confidence": self.confidence,
            "is_stable": self.is_stable,
            "first_observed_at": self.first_observed_at,
            "last_observed_at": self.last_observed_at,
            "last_success_at": self.last_success_at,
        }


class NavigationGraph:
    """Управляет структурой графа экранов и переходов для одного бота."""

    def __init__(self, bot: str, state=None):
        self.bot = bot
        self.state = state
        self.nodes: set[str] = set()
        # (src, action_id, dst) -> EdgeInfo
        self.edges: dict[tuple[str, str, str], EdgeInfo] = {}
        # src -> list[EdgeInfo]
        self.outgoing: dict[str, list[EdgeInfo]] = {}
        # dst -> list[EdgeInfo]
        self.incoming: dict[str, list[EdgeInfo]] = {}

        if self.state is not None:
            self._load_from_state()

    def _load_from_state(self) -> None:
        """Загружает сохранённый граф из базы данных."""
        if not self.state:
            return
        screens = self.state.screens_all(self.bot)
        for s in screens:
            self.nodes.add(s["screen_id"])
        
        edges_data = self.state.graph_edges_all(self.bot)
        for e in edges_data:
            edge = EdgeInfo(
                source_screen_id=e["source_screen_id"],
                action_id=e["action_id"],
                destination_screen_id=e["destination_screen_id"],
                result_type=e.get("result_type", "edit"),
                observations_count=int(e.get("observations_count", 1)),
                success_count=int(e.get("success_count", 1)),
                failure_count=int(e.get("failure_count", 0)),
                confidence=float(e.get("confidence", 1.0)),
                is_stable=bool(e.get("is_stable", 1)),
                first_observed_at=e.get("first_observed_at", _utcnow()),
                last_observed_at=e.get("last_observed_at", _utcnow()),
                last_success_at=e.get("last_success_at"),
            )
            key = (edge.source_screen_id, edge.action_id, edge.destination_screen_id)
            self.edges[key] = edge
            self.outgoing.setdefault(edge.source_screen_id, []).append(edge)
            self.incoming.setdefault(edge.destination_screen_id, []).append(edge)
            self.nodes.add(edge.source_screen_id)
            self.nodes.add(edge.destination_screen_id)

    def add_node(self, screen_id: str) -> None:
        self.nodes.add(screen_id)

    def record_transition(
        self,
        source_screen_id: str,
        action_id: str,
        destination_screen_id: str,
        result_type: str = "edit",
        success: bool = True,
    ) -> EdgeInfo:
        """Регистрирует наблюдавшийся переход и обновляет граф."""
        self.add_node(source_screen_id)
        self.add_node(destination_screen_id)
        now = _utcnow()

        # Проверяем, наблюдались ли другие destinations для этой же пары (source, action)
        existing_for_action = [
            e for (src, act, _dst), e in self.edges.items()
            if src == source_screen_id and act == action_id
        ]

        key = (source_screen_id, action_id, destination_screen_id)
        if key in self.edges:
            edge = self.edges[key]
            edge.observations_count += 1
            edge.last_observed_at = now
            if success:
                edge.success_count += 1
                edge.last_success_at = now
            else:
                edge.failure_count += 1
            edge.confidence = max(0.0, min(1.0, edge.success_count / max(1, edge.observations_count)))
            edge.result_type = result_type
        else:
            edge = EdgeInfo(
                source_screen_id=source_screen_id,
                action_id=action_id,
                destination_screen_id=destination_screen_id,
                result_type=result_type,
                observations_count=1,
                success_count=1 if success else 0,
                failure_count=0 if success else 1,
                confidence=1.0 if success else 0.0,
                is_stable=True,
                first_observed_at=now,
                last_observed_at=now,
                last_success_at=now if success else None,
            )
            self.edges[key] = edge
            self.outgoing.setdefault(source_screen_id, []).append(edge)
            self.incoming.setdefault(destination_screen_id, []).append(edge)

        # Если для этого действия уже были другие destinations -> помечаем как нестабильное
        if any(e.destination_screen_id != destination_screen_id for e in existing_for_action):
            for e in existing_for_action:
                e.is_stable = False
                e.confidence = min(e.confidence, 0.5)
            edge.is_stable = False
            edge.confidence = min(edge.confidence, 0.5)

        if self.state is not None:
            self.state.upsert_graph_edge(self.bot, edge.to_dict())

        return edge

    def mark_edge_unstable(self, source_screen_id: str, action_id: str) -> None:
        """Понижает confidence ребра при неудачной попытке навигации."""
        for (src, act, dst), edge in self.edges.items():
            if src == source_screen_id and act == action_id:
                edge.is_stable = False
                edge.failure_count += 1
                edge.observations_count += 1
                edge.confidence = max(0.05, edge.success_count / max(1, edge.observations_count))
                if self.state is not None:
                    self.state.upsert_graph_edge(self.bot, edge.to_dict())

    def get_outgoing(self, screen_id: str) -> list[EdgeInfo]:
        return self.outgoing.get(screen_id, [])

    def find_shortest_path(
        self,
        start_screen_id: str,
        target_screen_id: str,
        min_confidence: float = 0.2,
    ) -> list[EdgeInfo] | None:
        """Находит кратчайший надёжный путь в графе от start до target с помощью Дейкстры."""
        if start_screen_id == target_screen_id:
            return []
        if start_screen_id not in self.nodes or target_screen_id not in self.nodes:
            return None

        # Очередь с приоритетом: (total_cost, current_sid, path_edges)
        pq: list[tuple[float, str, list[EdgeInfo]]] = [(0.0, start_screen_id, [])]
        visited_costs: dict[str, float] = {start_screen_id: 0.0}

        while pq:
            cost, current_sid, path = heapq.heappop(pq)
            if current_sid == target_screen_id:
                return path

            if cost > visited_costs.get(current_sid, float("inf")):
                continue

            for edge in self.outgoing.get(current_sid, []):
                if edge.confidence < min_confidence:
                    continue
                
                # Стоимость шага: базовая 1.0 + штраф за нестабильность и низкий confidence
                step_cost = 1.0 + (1.0 - edge.confidence) * 2.0
                if not edge.is_stable:
                    step_cost += 2.0
                
                next_sid = edge.destination_screen_id
                next_cost = cost + step_cost
                if next_cost < visited_costs.get(next_sid, float("inf")):
                    visited_costs[next_sid] = next_cost
                    heapq.heappush(pq, (next_cost, next_sid, path + [edge]))

        return None

    def find_nearest_screen_with_targets(
        self,
        start_screen_id: str,
        target_screen_ids: set[str],
        min_confidence: float = 0.2,
    ) -> tuple[str, list[EdgeInfo], float] | None:
        """Находит ближайший экран из target_screen_ids и путь к нему."""
        if not target_screen_ids:
            return None
        if start_screen_id in target_screen_ids:
            return start_screen_id, [], 0.0

        pq: list[tuple[float, str, list[EdgeInfo]]] = [(0.0, start_screen_id, [])]
        visited_costs: dict[str, float] = {start_screen_id: 0.0}

        best_target: str | None = None
        best_path: list[EdgeInfo] | None = None
        best_cost = float("inf")

        while pq:
            cost, current_sid, path = heapq.heappop(pq)
            if current_sid in target_screen_ids:
                return current_sid, path, cost

            if cost > visited_costs.get(current_sid, float("inf")):
                continue

            for edge in self.outgoing.get(current_sid, []):
                if edge.confidence < min_confidence:
                    continue

                step_cost = 1.0 + (1.0 - edge.confidence) * 2.0
                if not edge.is_stable:
                    step_cost += 2.0

                next_sid = edge.destination_screen_id
                next_cost = cost + step_cost
                if next_cost < visited_costs.get(next_sid, float("inf")):
                    visited_costs[next_sid] = next_cost
                    heapq.heappush(pq, (next_cost, next_sid, path + [edge]))

        return None
