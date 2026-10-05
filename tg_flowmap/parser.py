from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from tg_flowmap.models import Button, Keyboard, MessageNode


def _ast_to_value(
    node: ast.AST,
    local_vars: Optional[Dict[str, Any]] = None,
    global_vars: Optional[Dict[str, Any]] = None,
) -> Any:
    """Best-effort extraction of literal values or string representations from AST nodes."""
    if local_vars is None:
        local_vars = {}
    if global_vars is None:
        global_vars = {}

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.BinOp):
        left = _ast_to_value(node.left, local_vars, global_vars)
        right = _ast_to_value(node.right, local_vars, global_vars)
        if isinstance(node.op, ast.Mult) and isinstance(left, str) and isinstance(right, int):
            return left * right
        if isinstance(node.op, ast.Add) and isinstance(left, str) and isinstance(right, str):
            return left + right

    if isinstance(node, ast.JoinedStr):
        parts = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                parts.append(str(part.value))
            elif isinstance(part, ast.FormattedValue):
                var_name = getattr(part.value, "id", None) or getattr(part.value, "attr", "*")
                parts.append(f"{{{var_name}}}")
            else:
                parts.append("*")
        return "".join(parts)

    if isinstance(node, ast.Name):
        if node.id in local_vars:
            val = local_vars[node.id]
            if isinstance(val, ast.AST):
                return _ast_to_value(val, local_vars, global_vars)
            return val
        if node.id in global_vars:
            val = global_vars[node.id]
            if isinstance(val, ast.AST):
                return _ast_to_value(val, local_vars, global_vars)
            return val
        return f"${node.id}"

    if isinstance(node, ast.Attribute):
        return f"${node.attr}"

    if isinstance(node, ast.Call):
        # Support dict.get(key, default) lookup (e.g. ICONS.get("sound"))
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            dict_obj = _ast_to_value(node.func.value, local_vars, global_vars)
            if isinstance(dict_obj, dict) and node.args:
                key = _ast_to_value(node.args[0], local_vars, global_vars)
                default = None
                if len(node.args) > 1:
                    default = _ast_to_value(node.args[1], local_vars, global_vars)
                for kw in node.keywords:
                    if kw.arg == "default":
                        default = _ast_to_value(kw.value, local_vars, global_vars)
                return dict_obj.get(key, default)

        # Support dict(other_dict)
        if isinstance(node.func, ast.Name) and node.func.id == "dict" and node.args:
            arg_val = _ast_to_value(node.args[0], local_vars, global_vars)
            if isinstance(arg_val, dict):
                return dict(arg_val)

        return None

    if isinstance(node, ast.Dict):
        d = {}
        for k, v in zip(node.keys, node.values):
            if k is not None:
                key_val = _ast_to_value(k, local_vars, global_vars)
                if key_val is not None:
                    d[str(key_val)] = _ast_to_value(v, local_vars, global_vars)
        return d

    return None


class AstParser:
    def __init__(self):
        self.keyboards: Dict[str, Keyboard] = {}
        self.nodes: Dict[str, MessageNode] = {}
        self.raw_files: Dict[str, str] = {}
        self.keyboard_aliases: Dict[str, str] = {}
        self.global_constants: Dict[str, Any] = {}

    def parse_dir(self, dirpath: Path, recursive: bool = True) -> None:
        """Parses all python files in a directory, ignoring heavy/system and test folders."""
        ignored_dirs = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
            "tests",
            ".pytest_cache",
            ".idea",
            ".vscode",
        }

        # Look for icons.json in project
        for candidate in [
            dirpath / "resources" / "icons.json",
            dirpath / "icons.json",
            dirpath.parent / "resources" / "icons.json",
        ]:
            if candidate.exists():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        self.global_constants["ICONS"] = data
                        self.global_constants["CANONICAL_ICONS"] = data
                        break
                except Exception:
                    pass

        py_files: List[Path] = []
        for root, dirs, files in os.walk(dirpath):
            dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
            for file in files:
                # Exclude tests and mocks from production bot mapping
                if file.endswith(".py") and not file.startswith("test_") and not file.endswith("_test.py"):
                    py_files.append(Path(root) / file)

        # Pass 1: Parse AST and collect module-level constants and keyboards
        parsed_trees: List[Tuple[Path, ast.AST]] = []
        for filepath in py_files:
            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
                self.raw_files[str(filepath)] = content
                tree = ast.parse(content, filename=str(filepath))
                parsed_trees.append((filepath, tree))
                self._extract_global_constants(tree)
            except (SyntaxError, UnicodeDecodeError):
                continue

        for filepath, tree in parsed_trees:
            self._extract_keyboards(tree, filepath)

        # Resolve keyboard aliases
        for alias, target in self.keyboard_aliases.items():
            if target in self.keyboards and alias not in self.keyboards:
                self.keyboards[alias] = self.keyboards[target]

        # Pass 2: Extract message nodes and routes across all parsed files
        for filepath, tree in parsed_trees:
            self._extract_handlers(tree, filepath)

    def parse_file(self, filepath: Path) -> None:
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        self.raw_files[str(filepath)] = content
        try:
            tree = ast.parse(content, filename=str(filepath))
        except SyntaxError:
            return

        self._extract_global_constants(tree)
        self._extract_keyboards(tree, filepath)
        for alias, target in self.keyboard_aliases.items():
            if target in self.keyboards and alias not in self.keyboards:
                self.keyboards[alias] = self.keyboards[target]
        self._extract_handlers(tree, filepath)

    def _extract_global_constants(self, tree: ast.AST) -> None:
        """Collects top-level module constants like CANONICAL_ICONS, EMOJI_BTN_*, etc."""
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        val = _ast_to_value(stmt.value, {}, self.global_constants)
                        if val is not None:
                            self.global_constants[target.id] = val

    def _extract_keyboards(self, tree: ast.AST, filepath: Path) -> None:
        """Finds functions, class methods, or module assignments constructing Telegram keyboards."""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                kb = self._parse_keyboard_function(node, filepath)
                if kb and kb.rows:
                    self.keyboards[node.name] = kb
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name_lower = target.id.lower()
                        if "markup" in name_lower or "keyboard" in name_lower or "buttons" in name_lower:
                            kb = self._parse_keyboard_expr(node.value, target.id, filepath, getattr(node, "lineno", 0), {})
                            if kb and kb.rows:
                                self.keyboards[target.id] = kb

    def _parse_keyboard_function(self, func_node: ast.FunctionDef, filepath: Path) -> Optional[Keyboard]:
        kb_name = func_node.name

        # Scope analysis: collect local assignments and list mutations
        local_vars: Dict[str, List[ast.AST]] = {}
        list_mutations: Dict[str, List[ast.AST]] = {}

        for stmt in ast.walk(func_node):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        local_vars.setdefault(target.id, []).append(stmt.value)
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
                    var_name = call.func.value.id
                    method = call.func.attr
                    if method in ("append", "extend") and call.args:
                        list_mutations.setdefault(var_name, []).append(call.args[0])

        # Look for return statements
        for stmt in ast.walk(func_node):
            if isinstance(stmt, ast.Return) and stmt.value:
                # Check for delegation / alias: e.g. return self.ui.main_menu_markup(...)
                if isinstance(stmt.value, ast.Call):
                    delegated_name = getattr(stmt.value.func, "attr", None) or getattr(stmt.value.func, "id", None)
                    if delegated_name and delegated_name != kb_name:
                        self.keyboard_aliases[kb_name] = delegated_name

                kb = self._parse_keyboard_expr(
                    stmt.value,
                    kb_name,
                    filepath,
                    stmt.lineno,
                    local_vars,
                    list_mutations,
                )
                if kb and kb.rows:
                    return kb
        return None

    def _parse_keyboard_expr(
        self,
        expr_node: ast.AST,
        name: str,
        filepath: Path,
        lineno: int,
        local_vars: Dict[str, List[ast.AST]],
        list_mutations: Optional[Dict[str, List[ast.AST]]] = None,
    ) -> Optional[Keyboard]:
        rows: List[List[Button]] = []
        if list_mutations is None:
            list_mutations = {}

        # Resolve variable reference if expr_node is a Name
        candidate_exprs = [expr_node]
        if isinstance(expr_node, ast.Name) and expr_node.id in local_vars:
            candidate_exprs = local_vars[expr_node.id]

        for expr in candidate_exprs:
            # Case 1: Dict with "inline_keyboard": [ ... ]
            if isinstance(expr, ast.Dict):
                for k, v in zip(expr.keys, expr.values):
                    if isinstance(k, ast.Constant) and k.value == "inline_keyboard":
                        candidate_vals = [v]
                        var_id = None
                        if isinstance(v, ast.Name):
                            var_id = v.id
                            if var_id in local_vars:
                                candidate_vals = local_vars[var_id]

                        for val_node in candidate_vals:
                            if isinstance(val_node, ast.List):
                                for row_node in val_node.elts:
                                    row = self._parse_button_row(row_node, local_vars)
                                    if row:
                                        rows.append(row)

                        # Also append any mutations tracked for this variable
                        if var_id and var_id in list_mutations:
                            for mutated in list_mutations[var_id]:
                                row = self._parse_button_row(mutated, local_vars)
                                if row:
                                    rows.append(row)

                if rows:
                    return Keyboard(name=name, rows=rows, source_file=str(filepath), line_number=lineno)

            # Case 2: Direct list of rows [ [ {...} ], [ {...} ] ]
            if isinstance(expr, ast.List):
                for row_node in expr.elts:
                    row = self._parse_button_row(row_node, local_vars)
                    if row:
                        rows.append(row)
                if rows:
                    return Keyboard(name=name, rows=rows, source_file=str(filepath), line_number=lineno)

        return None

    def _parse_button_row(self, row_node: ast.AST, local_vars: Dict[str, List[ast.AST]]) -> List[Button]:
        row: List[Button] = []

        candidate_rows = [row_node]
        if isinstance(row_node, ast.Name) and row_node.id in local_vars:
            candidate_rows = local_vars[row_node.id]

        for candidate in candidate_rows:
            if isinstance(candidate, ast.List):
                for elt in candidate.elts:
                    candidate_elts = [elt]
                    if isinstance(elt, ast.Name) and elt.id in local_vars:
                        candidate_elts = local_vars[elt.id]
                    for c_elt in candidate_elts:
                        btn = self._parse_button_element(c_elt, local_vars)
                        if btn:
                            row.append(btn)
            elif isinstance(candidate, ast.Call):
                btn = self._parse_helper_call(candidate)
                if btn:
                    row.append(btn)
            elif isinstance(candidate, ast.Dict):
                btn = self._parse_button_element(candidate, local_vars)
                if btn:
                    row.append(btn)

        return row

    def _parse_helper_call(self, call_node: ast.Call) -> Optional[Button]:
        func_name = getattr(call_node.func, "attr", None) or getattr(call_node.func, "id", "")
        if "back" in func_name.lower():
            target = "menu"
            if call_node.args:
                val = _ast_to_value(call_node.args[0], {}, self.global_constants)
                if val:
                    target = str(val).strip("'\"")
            return Button(text="« Назад", callback_data=target, line_number=getattr(call_node, "lineno", None))
        return None

    def _parse_button_element(self, elt_node: ast.AST, local_vars: Optional[Dict[str, Any]] = None) -> Optional[Button]:
        # Dictionary literal: {"text": "...", "callback_data": "..."}
        if isinstance(elt_node, ast.Dict):
            d: Dict[str, Any] = {}
            for k, v in zip(elt_node.keys, elt_node.values):
                if isinstance(k, ast.Constant):
                    val = _ast_to_value(v, local_vars or {}, self.global_constants)
                    d[str(k.value)] = val
            text = str(d.get("text", "") or "Button")
            cb = str(d.get("callback_data", "") or "") or None
            url = str(d.get("url", "") or "") or None
            icon_emoji = d.get("icon_custom_emoji_id")
            style = d.get("style")
            return Button(
                text=text,
                callback_data=cb,
                url=url,
                icon_custom_emoji_id=str(icon_emoji) if icon_emoji is not None else None,
                style=str(style) if style else None,
                line_number=getattr(elt_node, "lineno", None),
            )

        # Call: InlineKeyboardButton(text="...", callback_data="...")
        if isinstance(elt_node, ast.Call):
            kwargs: Dict[str, Any] = {}
            for kw in elt_node.keywords:
                kwargs[kw.arg] = _ast_to_value(kw.value, local_vars or {}, self.global_constants)
            text = str(kwargs.get("text", "") or "Button")
            cb = str(kwargs.get("callback_data", "") or "") or None
            return Button(
                text=text,
                callback_data=cb,
                url=str(kwargs.get("url", "")) if "url" in kwargs else None,
                line_number=getattr(elt_node, "lineno", None),
            )

        return None

    def _extract_handlers(self, tree: ast.AST, filepath: Path) -> None:
        """Finds if-else blocks, match-case, or decorators handling callback_data or commands."""
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                self._inspect_if_route(node, filepath)
            elif hasattr(ast, "Match") and isinstance(node, ast.Match):
                self._inspect_match_route(node, filepath)
            elif isinstance(node, ast.FunctionDef):
                self._inspect_decorated_handler(node, filepath)

    def _inspect_match_route(self, match_node: Any, filepath: Path) -> None:
        """Handles Python 3.10+ match ... case statements."""
        subject = getattr(match_node, "subject", None)
        sub_name = getattr(subject, "id", "") or getattr(subject, "attr", "")
        if sub_name not in ("data", "call_data", "callback_data"):
            return

        for case in getattr(match_node, "cases", []):
            pattern = case.pattern
            route_val = None
            if hasattr(ast, "MatchValue") and isinstance(pattern, ast.MatchValue):
                val = _ast_to_value(pattern.value, {}, self.global_constants)
                if val:
                    route_val = str(val)

            if route_val:
                text_template, kb_ref = self._find_message_dispatch(case.body)
                self._add_node(
                    node_id=f"cb:{route_val}",
                    title=route_val,
                    text_template=text_template or f"Экран {route_val}",
                    source_file=filepath,
                    lineno=case.pattern.lineno,
                    trigger_type="callback",
                    trigger_pattern=route_val,
                    kb_ref=kb_ref,
                )

    def _inspect_if_route(self, if_node: ast.If, filepath: Path) -> None:
        route_keys = self._extract_route_conditions(if_node.test)
        if not route_keys:
            return

        text_template, kb_ref = self._find_message_dispatch(if_node.body)

        for route_key, trigger_type in route_keys:
            prefix = "cmd:" if trigger_type == "command" else "cb:"
            node_id = f"{prefix}{route_key}"
            self._add_node(
                node_id=node_id,
                title=route_key,
                text_template=text_template or f"Экран {route_key}",
                source_file=filepath,
                lineno=if_node.lineno,
                trigger_type=trigger_type,
                trigger_pattern=route_key,
                kb_ref=kb_ref,
            )

    def _add_node(
        self,
        node_id: str,
        title: str,
        text_template: str,
        source_file: Path,
        lineno: int,
        trigger_type: str,
        trigger_pattern: str,
        kb_ref: Optional[str],
    ) -> None:
        node = MessageNode(
            id=node_id,
            title=title,
            text_template=text_template,
            source_file=str(source_file),
            line_number=lineno,
            trigger_type=trigger_type,
            trigger_pattern=trigger_pattern,
        )

        # Resolve keyboard reference (including aliases and leading underscore fallbacks)
        if kb_ref:
            resolved_kb = (
                self.keyboards.get(kb_ref)
                or self.keyboards.get(self.keyboard_aliases.get(kb_ref, ""))
                or self.keyboards.get(kb_ref.lstrip("_"))
            )
            if resolved_kb:
                node.keyboard = resolved_kb

        self.nodes[node_id] = node

    def _extract_route_conditions(self, test_node: ast.AST) -> List[Tuple[str, str]]:
        routes: List[Tuple[str, str]] = []

        # Case 1: data == "val" or text == "/start"
        if isinstance(test_node, ast.Compare):
            left_id = getattr(test_node.left, "id", "") or getattr(test_node.left, "attr", "")
            for op, comp in zip(test_node.ops, test_node.comparators):
                if isinstance(op, ast.Eq):
                    val = _ast_to_value(comp, {}, self.global_constants)
                    if val:
                        val_str = str(val).strip("'\"")
                        if left_id in ("data", "call_data", "callback_data"):
                            routes.append((val_str, "callback"))
                        elif left_id in ("text", "lower_text", "cmd", "command"):
                            routes.append((val_str, "command"))

                # Case 2: data in {"menu", "settings"} or text in {"/start", "меню"}
                elif isinstance(op, ast.In):
                    if isinstance(comp, (ast.Set, ast.List, ast.Tuple)):
                        for elt in comp.elts:
                            val = _ast_to_value(elt, {}, self.global_constants)
                            if val:
                                val_str = str(val).strip("'\"")
                                if left_id in ("data", "call_data", "callback_data"):
                                    routes.append((val_str, "callback"))
                                elif left_id in ("text", "lower_text", "cmd", "command"):
                                    routes.append((val_str, "command"))

        # Case 3: data.startswith("volume:") or text.startswith("/start")
        if isinstance(test_node, ast.Call) and isinstance(test_node.func, ast.Attribute):
            if test_node.func.attr == "startswith":
                val_node = test_node.func.value
                val_id = getattr(val_node, "id", "") or getattr(val_node, "attr", "")
                if test_node.args:
                    val = _ast_to_value(test_node.args[0], {}, self.global_constants)
                    if val:
                        val_str = str(val).strip("'\"")
                        if val_id in ("data", "call_data", "callback_data"):
                            routes.append((f"{val_str}*", "callback"))
                        elif val_id in ("text", "lower_text", "cmd", "command"):
                            routes.append((val_str, "command"))

        return routes

    def _find_message_dispatch(self, body: List[ast.stmt]) -> Tuple[str, Optional[str]]:
        text_str = ""
        kb_name = None

        for stmt in body:
            for subnode in ast.walk(stmt):
                if isinstance(subnode, ast.Call):
                    func_name = getattr(subnode.func, "attr", None) or getattr(subnode.func, "id", "")
                    if any(k in func_name.lower() for k in ("send_message", "edit_message", "sendphoto", "answer", "send_player_card")):
                        for arg in subnode.args:
                            val = _ast_to_value(arg, {}, self.global_constants)
                            if isinstance(val, str) and len(val) > 2 and not text_str and not val.startswith("$"):
                                text_str = val
                        for kw in subnode.keywords:
                            if kw.arg in ("text", "caption"):
                                val = _ast_to_value(kw.value, {}, self.global_constants)
                                if isinstance(val, str) and val:
                                    text_str = val
                            elif kw.arg == "reply_markup":
                                if isinstance(kw.value, ast.Call):
                                    kb_name = getattr(kw.value.func, "attr", None) or getattr(kw.value.func, "id", "")
                                elif isinstance(kw.value, ast.Name):
                                    kb_name = kw.value.id

        return text_str, kb_name

    def _inspect_decorated_handler(self, func_node: ast.FunctionDef, filepath: Path) -> None:
        """aiogram / telebot decorators: @dp.callback_query(...) or @dp.message(Command('start'))"""
        for dec in func_node.decorator_list:
            dec_str = ast.unparse(dec) if hasattr(ast, "unparse") else ""
            if "callback" in dec_str.lower():
                route_name = func_node.name
                match = re.search(r'["\']([\w:-]+)["\']', dec_str)
                if match:
                    route_name = match.group(1)

                text_template, kb_ref = self._find_message_dispatch(func_node.body)
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
                )
            elif "message" in dec_str.lower() and "start" in dec_str.lower():
                text_template, kb_ref = self._find_message_dispatch(func_node.body)
                node_id = "cmd:/start"
                self._add_node(
                    node_id=node_id,
                    title="/start",
                    text_template=text_template or f"Command {func_node.name}",
                    source_file=filepath,
                    lineno=func_node.lineno,
                    trigger_type="command",
                    trigger_pattern="/start",
                    kb_ref=kb_ref,
                )
