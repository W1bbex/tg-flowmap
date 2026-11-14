from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from tg_flowmap.sast.evaluator import _ast_to_value


def _unwrap_operand(node: ast.AST) -> ast.AST:
    """Unwraps string normalization calls (.lower(), .strip(), .casefold(), etc.)."""
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in ("lower", "strip", "lstrip", "rstrip", "casefold", "capitalize"):
            node = node.func.value
        else:
            break
    return node


def _classify_operand_source(node: ast.AST) -> Optional[str]:
    """Classifies AST operand as data/callback ('callback') or message text/command ('command')."""
    node = _unwrap_operand(node)

    # 1. Variable name
    if isinstance(node, ast.Name):
        name = node.id.lower()
        if name in ("data", "call_data", "callback_data", "cb_data", "query_data"):
            return "callback"
        if name in (
            "text", "lower_text", "msg_text", "message_text",
            "cmd", "command", "user_msg", "user_text", "raw_text", "input_text",
        ):
            return "command"

    # 2. Attribute access: message.text, call.data, query.data, update.message.text
    elif isinstance(node, ast.Attribute):
        attr = node.attr.lower()
        if attr in ("data", "callback_data"):
            return "callback"
        if attr in ("text", "caption"):
            return "command"

    return None


class RouteExtractorMixin:
    """Mixin inspecting if-routes, match-routes, and aiogram/telebot decorated handlers."""

    def _extract_handlers(self, tree: ast.AST, filepath: Path) -> None:
        """Finds if-else blocks, match-case, or decorators handling callback_data or commands."""
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                self._inspect_if_route(node, filepath)
            elif hasattr(ast, "Match") and isinstance(node, ast.Match):
                self._inspect_match_route(node, filepath)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._inspect_decorated_handler(node, filepath)

    def _inspect_match_route(self, match_node: Any, filepath: Path) -> None:
        """Handles Python 3.10+ match ... case statements."""
        subject = getattr(match_node, "subject", None)
        sub_name = getattr(subject, "id", "") or getattr(subject, "attr", "")
        if sub_name not in ("data", "call_data", "callback_data"):
            return

        for case in getattr(match_node, "cases", []):
            pattern = case.pattern
            route_vals = []
            patterns = pattern.patterns if hasattr(ast, "MatchOr") and isinstance(pattern, ast.MatchOr) else [pattern]
            for p in patterns:
                if hasattr(ast, "MatchValue") and isinstance(p, ast.MatchValue):
                    val = _ast_to_value(p.value, {}, self.global_constants)
                    if val:
                        route_vals.append(str(val))

            if route_vals:
                text_template, kb_ref, inline_kb = self._find_message_dispatch(case.body, filepath)
                for route_val in route_vals:
                    self._add_node(
                        node_id=f"cb:{route_val}",
                        title=route_val,
                        text_template=text_template or f"Экран {route_val}",
                        source_file=filepath,
                        lineno=getattr(case.pattern, "lineno", 0),
                        trigger_type="callback",
                        trigger_pattern=route_val,
                        kb_ref=kb_ref,
                        inline_kb=inline_kb,
                    )

    def _inspect_if_route(self, if_node: ast.If, filepath: Path) -> None:
        route_keys = self._extract_route_conditions(if_node.test)
        if not route_keys:
            return

        text_template, kb_ref, inline_kb = self._find_message_dispatch(if_node.body, filepath)

        # Pick the canonical trigger (prefer commands starting with '/' or canonical names like 'menu')
        canonical_key, trigger_type = route_keys[0]
        for k, t in route_keys:
            if k.startswith("/") or k in ("start", "menu", "exit", "quit"):
                canonical_key, trigger_type = k, t
                break

        if trigger_type == "command":
            c_clean = canonical_key.lstrip("/")
            node_id = f"cmd:/{c_clean}"
            title_str = f"/{c_clean}" if canonical_key.startswith("/") else canonical_key
            trigger_pattern = f"/{c_clean}"
        else:
            node_id = f"cb:{canonical_key}"
            title_str = canonical_key
            trigger_pattern = canonical_key

        aliases = [k for k, _ in route_keys if k != canonical_key]
        if trigger_type == "command" and not canonical_key.startswith("/"):
            if canonical_key not in aliases:
                aliases.append(canonical_key)

        if aliases:
            title_str = f"{title_str} ({', '.join(aliases[:2])})"

        self._add_node(
            node_id=node_id,
            title=title_str,
            text_template=text_template or f"Экран {canonical_key}",
            source_file=filepath,
            lineno=if_node.lineno,
            trigger_type=trigger_type,
            trigger_pattern=trigger_pattern,
            kb_ref=kb_ref,
            inline_kb=inline_kb,
            aliases=aliases,
        )

    def _extract_route_conditions(self, test_node: ast.AST) -> List[Tuple[str, str]]:
        routes: List[Tuple[str, str]] = []
        active_constants = self._get_constants_for_file()

        # Handle boolean combinations: if data == "a" or data == "b":
        if isinstance(test_node, ast.BoolOp):
            for val_sub in test_node.values:
                routes.extend(self._extract_route_conditions(val_sub))
            return routes

        # Case 1: Comparisons (==, in)
        if isinstance(test_node, ast.Compare):
            left_kind = _classify_operand_source(test_node.left)
            left_val = _ast_to_value(test_node.left, {}, active_constants)

            for op, comp in zip(test_node.ops, test_node.comparators):
                comp_kind = _classify_operand_source(comp)
                comp_val = _ast_to_value(comp, {}, active_constants)

                if isinstance(op, ast.Eq):
                    # Direct: target == "value"
                    if left_kind and comp_val is not None:
                        val_str = str(comp_val).strip("'\"")
                        routes.append((val_str, left_kind))
                    # Symmetric reverse: "value" == target
                    elif comp_kind and left_val is not None:
                        val_str = str(left_val).strip("'\"")
                        routes.append((val_str, comp_kind))

                elif isinstance(op, ast.In):
                    # Direct: target in {"a", "b"}
                    if left_kind:
                        if isinstance(comp, (ast.Set, ast.List, ast.Tuple)):
                            for elt in comp.elts:
                                val = _ast_to_value(elt, {}, active_constants)
                                if val is not None:
                                    routes.append((str(val).strip("'\""), left_kind))
                        elif isinstance(comp_val, (set, list, tuple)):
                            for item in comp_val:
                                if item is not None:
                                    routes.append((str(item).strip("'\""), left_kind))
                    # Reverse: "a" in target
                    elif comp_kind and left_val is not None:
                        routes.append((str(left_val).strip("'\""), comp_kind))

        # Case 2: Method calls like data.startswith("volume:") or message.text.startswith(("/stealth", "скрытность"))
        if isinstance(test_node, ast.Call) and isinstance(test_node.func, ast.Attribute):
            if test_node.func.attr == "startswith":
                val_node = test_node.func.value
                val_kind = _classify_operand_source(val_node)
                if val_kind and test_node.args:
                    val = _ast_to_value(test_node.args[0], {}, active_constants)
                    if val is not None:
                        val_items = list(val) if isinstance(val, (tuple, list, set)) else [val]
                        for item in val_items:
                            if item is None:
                                continue
                            val_str = str(item).strip("'\"")
                            if val_kind == "callback":
                                routes.append((f"{val_str}*", "callback"))
                            else:
                                routes.append((val_str, "command"))

        return routes

    def _inspect_decorated_handler(self, func_node: ast.FunctionDef, filepath: Path) -> None:
        """aiogram / telebot decorators: @dp.callback_query(...) or @dp.message(Command(...))"""
        for dec in func_node.decorator_list:
            dec_str = ast.unparse(dec) if hasattr(ast, "unparse") else ""
            dec_low = dec_str.lower()

            # 1. Callback query handlers
            if "callback" in dec_low:
                routes: List[str] = []
                for m in re.finditer(r'F\.data\s*==\s*["\']([^"\']+)["\']', dec_str):
                    routes.append(m.group(1))
                for m in re.finditer(r'F\.data\.startswith\(\s*["\']([^"\']+)["\']', dec_str):
                    routes.append(f"{m.group(1)}*")
                for m in re.finditer(r'F\.data\.in_\(\s*\[([^\]]+)\]\s*\)', dec_str):
                    for item in re.finditer(r'["\']([\w:-]+)["\']', m.group(1)):
                        routes.append(item.group(1))
                for m in re.finditer(r'(\w+Callback\w*)\.filter\(([^)]*)\)', dec_str):
                    factory_name = m.group(1)
                    filter_body = m.group(2)
                    act_m = re.search(r'action\s*==\s*["\']([\w:-]+)["\']', filter_body)
                    if act_m:
                        routes.append(f"{factory_name}:{act_m.group(1)}")
                    else:
                        routes.append(f"{factory_name}:*")
                if not routes:
                    for m in re.finditer(r'["\']([\w:-]+)["\']', dec_str):
                        val = m.group(1)
                        if val not in ("callback_query", "callback", "data", "text", "state"):
                            routes.append(val)
                            break
                if not routes:
                    routes = [func_node.name]

                text_template, kb_ref, inline_kb = self._find_message_dispatch(func_node.body, filepath)
                for route_name in routes:
                    node_id = f"cb:{route_name}"
                    self._add_node(
                        node_id=node_id,
                        title=route_name,
                        text_template=text_template or f"Handler {func_node.name}",
                        source_file=filepath,
                        lineno=func_node.lineno,
                        trigger_type="callback",
                        trigger_pattern=route_name,
                        kb_ref=kb_ref,
                        inline_kb=inline_kb,
                    )

            # 2. Message / Command handlers
            elif "message" in dec_low or "command" in dec_low:
                commands: List[str] = []
                for m in re.finditer(r'Command\(\s*["\']([\w-]+)["\']', dec_str):
                    commands.append(m.group(1))
                for m in re.finditer(r'commands\s*=\s*\[([^\]]+)\]', dec_str):
                    for item in re.finditer(r'["\']([\w-]+)["\']', m.group(1)):
                        commands.append(item.group(1))
                if re.search(r'\bCommandStart\b', dec_str):
                    commands.append("start")
                for m in re.finditer(r'["\']/([\w-]+)["\']', dec_str):
                    if any(k in dec_str for k in ("==", "in", "equals")):
                        commands.append(m.group(1))
                if not commands and (func_node.name.startswith("cmd_") or func_node.name.startswith("command_")):
                    commands.append(func_node.name.split("_", 1)[1])
                elif not commands and func_node.name in ("start", "start_handler", "start_command"):
                    commands.append("start")

                if commands:
                    text_template, kb_ref, inline_kb = self._find_message_dispatch(func_node.body, filepath)
                    for cmd in commands:
                        c_clean = cmd.lstrip("/")
                        node_id = f"cmd:/{c_clean}"
                        self._add_node(
                            node_id=node_id,
                            title=f"/{c_clean}",
                            text_template=text_template or f"Command /{c_clean}",
                            source_file=filepath,
                            lineno=func_node.lineno,
                            trigger_type="command",
                            trigger_pattern=f"/{c_clean}",
                            kb_ref=kb_ref,
                            inline_kb=inline_kb,
                        )
