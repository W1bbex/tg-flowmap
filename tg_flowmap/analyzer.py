from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from tg_flowmap.models import BotMap, Button, Edge, Issue, Keyboard, MessageNode


class GraphAnalyzer:
    def __init__(self, nodes: Dict[str, MessageNode], keyboards: Dict[str, Keyboard]):
        self.nodes = nodes
        self.keyboards = keyboards
        self.edges: List[Edge] = []
        self.issues: List[Issue] = []

    def build_map(self) -> BotMap:
        self.edges.clear()
        self.issues.clear()

        # Step 1: Resolve edges from buttons to destination nodes
        for node_id, node in self.nodes.items():
            if not node.keyboard:
                continue

            has_back_button = False
            for btn in node.keyboard.all_buttons():
                self._inspect_button_lint(btn, node)

                # URL buttons
                if btn.url:
                    self.edges.append(
                        Edge(
                            from_node_id=node_id,
                            to_node_id=f"url:{btn.url}",
                            button_text=btn.text,
                            callback_data=btn.url,
                            is_back=False,
                            status="url",
                        )
                    )
                    continue

                if not btn.callback_data:
                    continue

                cb = btn.callback_data
                is_back = any(k in btn.text.lower() for k in ("назад", "back", "«", "‹", "↩")) or cb in ("menu", "main")
                if is_back and node_id not in ("cb:menu", "cmd:/start", "cb:start"):
                    has_back_button = True

                target_node_id, status = self._resolve_target(cb)
                self.edges.append(
                    Edge(
                        from_node_id=node_id,
                        to_node_id=target_node_id,
                        button_text=btn.text,
                        callback_data=cb,
                        is_back=is_back,
                        status=status,
                    )
                )

                if status == "dead_end":
                    self.issues.append(
                        Issue(
                            severity="error",
                            issue_type="dead_end",
                            message=f"Кнопка '{btn.text}' ведёт на коллбек '{cb}', для которого нет обработчика в коде!",
                            node_id=node_id,
                            source_file=node.source_file,
                            line_number=btn.line_number or node.line_number,
                        )
                    )

            if not has_back_button and node_id not in ("cb:menu", "cmd:/start", "cb:start", "cmd:/menu"):
                self.issues.append(
                    Issue(
                        severity="warning",
                        issue_type="missing_back",
                        message=f"В экране '{node.title}' нет кнопки возврата (« Назад / В меню »). Пользователь может оказаться в тупике.",
                        node_id=node_id,
                        source_file=node.source_file,
                        line_number=node.line_number,
                    )
                )

        # Step 2: Check for dangling handlers (nodes that are never called)
        called_targets = {e.to_node_id for e in self.edges}
        for node_id, node in self.nodes.items():
            if (
                node_id not in called_targets
                and node_id not in ("cb:menu", "cmd:/start", "cb:start", "cmd:/menu", "cmd:/console")
                and not node_id.startswith("cmd:")
            ):
                self.issues.append(
                    Issue(
                        severity="info",
                        issue_type="dangling_handler",
                        message=f"Обработчик '{node.title}' определён в коде, но ни одна кнопка на него не ссылается.",
                        node_id=node_id,
                        source_file=node.source_file,
                        line_number=node.line_number,
                    )
                )

        stats = {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "total_issues": len(self.issues),
            "dead_ends": sum(1 for i in self.issues if i.issue_type == "dead_end"),
            "broken_emojis": sum(1 for i in self.issues if i.issue_type == "null_emoji"),
            "missing_backs": sum(1 for i in self.issues if i.issue_type == "missing_back"),
        }

        return BotMap(nodes=self.nodes, edges=self.edges, issues=self.issues, stats=stats)

    def _inspect_button_lint(self, btn: Button, node: MessageNode) -> None:
        """Checks for Telegram API constraints and bugs."""
        # 1. Null/invalid icon_custom_emoji_id
        if btn.icon_custom_emoji_id is not None:
            val = str(btn.icon_custom_emoji_id).strip()
            if val.lower() in ("none", "null", "") or not val.isdigit():
                self.issues.append(
                    Issue(
                        severity="error",
                        issue_type="null_emoji",
                        message=(
                            f"В кнопке '{btn.text}' поле icon_custom_emoji_id='{btn.icon_custom_emoji_id}' "
                            f"(невалидное числовое значение). Telegram API вернёт 400 Bad Request!"
                        ),
                        node_id=node.id,
                        source_file=node.source_file,
                        line_number=btn.line_number or node.line_number,
                    )
                )

        # 2. Missing action (no callback_data and no url)
        is_reply = False
        if node.keyboard and getattr(node.keyboard, "keyboard_type", "inline") == "reply":
            is_reply = True
        if not is_reply and not btn.callback_data and not btn.url:
            self.issues.append(
                Issue(
                    severity="error",
                    issue_type="invalid_button",
                    message=f"Кнопка '{btn.text}' не имеет ни callback_data, ни url. Telegram отклонит такую кнопку!",
                    node_id=node.id,
                    source_file=node.source_file,
                    line_number=btn.line_number or node.line_number,
                )
            )

        # 3. Callback data length limit (Telegram 64 bytes max)
        if btn.callback_data and len(btn.callback_data.encode("utf-8")) > 64:
            self.issues.append(
                Issue(
                    severity="error",
                    issue_type="callback_too_long",
                    message=(
                        f"Кнопка '{btn.text}' имеет callback_data длиннее 64 байт "
                        f"({len(btn.callback_data.encode('utf-8'))} байт). Telegram API вернёт 400 BUTTON_DATA_INVALID!"
                    ),
                    node_id=node.id,
                    source_file=node.source_file,
                    line_number=btn.line_number or node.line_number,
                )
            )

    def _resolve_target(self, cb: str) -> Tuple[str, str]:
        # Exact match
        exact_id = f"cb:{cb}"
        if exact_id in self.nodes:
            return exact_id, "ok"

        # Alias match
        for node_id, node in self.nodes.items():
            if hasattr(node, "aliases") and (cb in node.aliases or f"/{cb}" in node.aliases or f"cb:{cb}" in node.aliases):
                return node_id, "ok"

        # Wildcard prefix match in nodes (e.g. volume:* or player_*)
        for node_id in self.nodes:
            if node_id.startswith("cb:") and node_id.endswith("*"):
                prefix = node_id[3:-1]  # strip "cb:" and "*"
                if cb.startswith(prefix):
                    return node_id, "dynamic"

        # Prefix splitting (colon or underscore)
        if ":" in cb:
            prefix = cb.split(":", 1)[0]
            prefix_id = f"cb:{prefix}:*"
            if prefix_id in self.nodes:
                return prefix_id, "dynamic"
            prefix_raw = f"cb:{prefix}"
            if prefix_raw in self.nodes:
                return prefix_raw, "dynamic"

        # Fallback to menu / main screen
        if cb in ("menu", "main", "dashboard"):
            if "cb:menu" in self.nodes:
                return "cb:menu", "ok"
            if "cmd:/start" in self.nodes:
                return "cmd:/start", "ok"
            if "cmd:/menu" in self.nodes:
                return "cmd:/menu", "ok"

        # Dead end
        return f"unresolved:{cb}", "dead_end"
