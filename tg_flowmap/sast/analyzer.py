from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from tg_flowmap.core.models import BotMap, Button, Edge, Issue, Keyboard, MessageNode


class GraphAnalyzer:
    def __init__(
        self,
        nodes: Dict[str, MessageNode],
        keyboards: Dict[str, Keyboard],
        screen_aliases: Optional[Dict[str, str]] = None,
        hub_return_nodes: Optional[Set[str]] = None,
    ):
        self.nodes = nodes
        self.keyboards = keyboards
        self.screen_aliases = screen_aliases or {}
        self.hub_return_nodes = hub_return_nodes or set()
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
                    # Reply keyboard text button routing
                    if node.keyboard and getattr(node.keyboard, "keyboard_type", "inline") == "reply" and btn.text:
                        btn_text_low = btn.text.lower()
                        btn_is_back = any(k in btn_text_low for k in ("назад", "back", "«", "‹", "↩"))
                        if btn_is_back and node_id not in ("cb:menu", "cmd:/start", "cb:start"):
                            has_back_button = True

                        text_target = btn.text.strip()
                        cmd_candidate = f"cmd:/{text_target.lstrip('/')}"
                        matched_id = None
                        if cmd_candidate in self.nodes:
                            matched_id = cmd_candidate
                        else:
                            for nid, n in self.nodes.items():
                                if hasattr(n, "aliases") and text_target in n.aliases:
                                    matched_id = nid
                                    break
                        if matched_id:
                            self.edges.append(
                                Edge(
                                    from_node_id=node_id,
                                    to_node_id=matched_id,
                                    button_text=btn.text,
                                    callback_data=btn.text,
                                    is_back=btn_is_back,
                                    status="ok",
                                )
                            )
                    continue

                cb = btn.callback_data
                btn_text = btn.text or ""
                is_back = (any(k in btn_text.lower() for k in ("назад", "back", "«", "‹", "↩")) if btn_text else False) or cb in ("menu", "main")
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

        # Step 1.5: Connect hub return nodes (e.g. console_close returning to cb:menu)
        hub_target = "cb:menu" if "cb:menu" in self.nodes else "cmd:/start"
        for ret_id in self.hub_return_nodes:
            if ret_id in self.nodes and hub_target in self.nodes:
                self.edges.append(
                    Edge(
                        from_node_id=ret_id,
                        to_node_id=hub_target,
                        button_text="В меню",
                        callback_data="menu",
                        is_back=True,
                        status="ok",
                    )
                )

        # Step 2: Check for dangling handlers (nodes that are never called)
        called_targets = {e.to_node_id for e in self.edges}
        for node_id, node in self.nodes.items():
            if (
                node_id not in called_targets
                and node_id not in ("cb:menu", "cmd:/start", "cb:start", "cmd:/menu")
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

        # Step 3: Check for duplicate screens & redundant flows (O(N) grouping)
        kb_groups: Dict[str, List[MessageNode]] = defaultdict(list)
        for n in self.nodes.values():
            if not n.keyboard or not n.keyboard.rows or not n.keyboard.name:
                continue
            total_btns = len(n.keyboard.all_buttons())
            kb_name_lower = n.keyboard.name.lower()
            is_generic_back = any(k in kb_name_lower for k in ("back", "cancel", "close", "nav", "назад", "отмена"))
            if is_generic_back and total_btns <= 1:
                continue
            kb_groups[n.keyboard.name].append(n)

        for kb_name, group_nodes in kb_groups.items():
            if len(group_nodes) > 1:
                first = group_nodes[0]
                others = ", ".join(f"'{n.title}'" for n in group_nodes[1:4])
                if len(group_nodes) > 4:
                    others += f" и ещё {len(group_nodes) - 4}"
                self.issues.append(
                    Issue(
                        severity="warning",
                        issue_type="duplicate_screen",
                        message=f"Экраны '{first.title}' и {others} используют одинаковую клавиатуру '{kb_name}'. Рекомендуется объединить обработчики или сделать редирект.",
                        node_id=first.id,
                        source_file=first.source_file,
                        line_number=first.line_number,
                    )
                )

        stats = {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "total_issues": len(self.issues),
            "dead_ends": sum(1 for i in self.issues if i.issue_type == "dead_end"),
            "broken_emojis": sum(1 for i in self.issues if i.issue_type == "null_emoji"),
            "missing_backs": sum(1 for i in self.issues if i.issue_type == "missing_back"),
            "duplicate_screens": sum(1 for i in self.issues if i.issue_type == "duplicate_screen"),
        }

        return BotMap(nodes=self.nodes, edges=self.edges, issues=self.issues, stats=stats)

    def _inspect_button_lint(self, btn: Button, node: MessageNode) -> None:
        """Checks for Telegram API constraints and bugs."""
        # 1. Null/invalid icon_custom_emoji_id
        if btn.icon_custom_emoji_id is not None:
            val = str(btn.icon_custom_emoji_id).strip()
            # If value is a dynamic AST reference (starts with $), do not fail strict validation
            if not val.startswith("$") and (val.lower() in ("none", "null", "") or not val.isdigit()):
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

        # 2. Missing action (no callback_data, url, web_app, etc.)
        is_reply = False
        if node.keyboard and getattr(node.keyboard, "keyboard_type", "inline") == "reply":
            is_reply = True
        has_action = bool(
            btn.callback_data
            or btn.url
            or getattr(btn, "web_app", None)
            or getattr(btn, "switch_inline_query", None)
            or getattr(btn, "pay", None)
        )
        if not is_reply and not has_action:
            self.issues.append(
                Issue(
                    severity="error",
                    issue_type="invalid_button",
                    message=f"Кнопка '{btn.text}' не имеет ни callback_data, ни url, ни web_app. Telegram отклонит такую кнопку!",
                    node_id=node.id,
                    source_file=node.source_file,
                    line_number=btn.line_number or node.line_number,
                )
            )

        # 3. Callback data length limit (Telegram 64 bytes max)
        cb_str = str(btn.callback_data) if btn.callback_data is not None else ""
        if cb_str and len(cb_str.encode("utf-8")) > 64:
            self.issues.append(
                Issue(
                    severity="error",
                    issue_type="callback_too_long",
                    message=(
                        f"Кнопка '{btn.text}' имеет callback_data длиннее 64 байт "
                        f"({len(cb_str.encode('utf-8'))} байт). Telegram API вернёт 400 BUTTON_DATA_INVALID!"
                    ),
                    node_id=node.id,
                    source_file=node.source_file,
                    line_number=btn.line_number or node.line_number,
                )
            )

    def _resolve_target(self, cb: str) -> Tuple[str, str]:
        cb = str(cb) if cb is not None else ""
        # Exact match
        exact_id = f"cb:{cb}"
        if exact_id in self.nodes:
            return exact_id, "ok"

        # Screen aliases check
        if cb in self.screen_aliases:
            return self.screen_aliases[cb], "ok"
        if f"cmd:/{cb}" in self.screen_aliases:
            return self.screen_aliases[f"cmd:/{cb}"], "ok"
        if f"cb:{cb}" in self.screen_aliases:
            return self.screen_aliases[f"cb:{cb}"], "ok"

        # Alias match
        for node_id, node in self.nodes.items():
            if hasattr(node, "aliases") and (cb in node.aliases or f"/{cb}" in node.aliases or f"cb:{cb}" in node.aliases):
                return node_id, "ok"

        # Wildcard prefix match in nodes (e.g. volume:* or player_*)
        for node_id in self.nodes:
            if node_id.startswith("cb:") and node_id.endswith("*"):
                prefix = node_id[3:-1]  # strip "cb:" and "*"
                if prefix and cb.startswith(prefix):
                    return node_id, "dynamic"

        # Prefix splitting (colon or underscore)
        for sep in (":", "_"):
            if sep in cb:
                prefix = cb.split(sep, 1)[0]
                candidates = (
                    f"cb:{prefix}:*",
                    f"cb:{prefix}{sep}*",
                    f"cb:{prefix}_*",
                    f"cb:{prefix}",
                )
                for cand in candidates:
                    if cand in self.nodes:
                        return cand, "dynamic"

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
