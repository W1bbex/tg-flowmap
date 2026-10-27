from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from tg_flowmap.core.models import Button, Keyboard, MessageNode
from tg_flowmap.sast.evaluator import _ast_to_value, extract_module_constants


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
            "cmd", "command", "user_msg", "user_text", "raw_text", "input_text"
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


class AstParser:
    def __init__(self):
        self.reset()

    def reset(self) -> None:
        """Resets all parsed state containers before analysis."""
        self.keyboards: Dict[str, Keyboard] = {}
        self.keyboard_param_defaults: Dict[str, List[Tuple[str, Optional[str]]]] = {}
        self.nodes: Dict[str, MessageNode] = {}
        self.keyboard_aliases: Dict[str, str] = {}
        self.screen_aliases: Dict[str, str] = {}
        self.hub_return_nodes: Set[str] = set()
        self.global_constants: Dict[str, Any] = {}
        self.custom_emoji_ids: Set[str] = set()
        self.registered_menu_commands: Set[str] = set()
        self.has_set_my_commands: bool = False

    def parse_dir(self, dirpath: Path, recursive: bool = True) -> None:
        """Parses all python files in a directory, ignoring heavy/system and test folders."""
        self.reset()
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
            if not recursive:
                dirs.clear()
            for file in files:
                # Exclude tests and mocks from production bot mapping
                if file.endswith(".py") and not file.startswith("test_") and not file.endswith("_test.py"):
                    py_files.append(Path(root) / file)

        # Pass 1: Parse AST and collect module-level constants and keyboards
        parsed_trees: List[Tuple[Path, ast.AST]] = []
        for filepath in py_files:
            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=str(filepath))
                parsed_trees.append((filepath, tree))
                self._extract_global_constants(tree)
            except (SyntaxError, UnicodeDecodeError):
                continue

        for filepath, tree in parsed_trees:
            self._extract_keyboards(tree, filepath)
            self._extract_set_my_commands(tree, filepath)

        # Resolve keyboard aliases
        for alias, target in self.keyboard_aliases.items():
            if target in self.keyboards and alias not in self.keyboards:
                self.keyboards[alias] = self.keyboards[target]

        # Pass 2: Extract message nodes and routes across all parsed files
        for filepath, tree in parsed_trees:
            self._extract_handlers(tree, filepath)

        self._consolidate_duplicate_screens()

    def parse_file(self, filepath: Path, reset: bool = True) -> None:
        if reset:
            self.reset()
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        try:
            tree = ast.parse(content, filename=str(filepath))
        except SyntaxError:
            return

        self._extract_global_constants(tree)
        self._extract_keyboards(tree, filepath)
        self._extract_set_my_commands(tree, filepath)
        for alias, target in self.keyboard_aliases.items():
            if target in self.keyboards and alias not in self.keyboards:
                self.keyboards[alias] = self.keyboards[target]
        self._extract_handlers(tree, filepath)
        self._consolidate_duplicate_screens()

    def _consolidate_duplicate_screens(self) -> None:
        """Merges duplicate screens (e.g. /led command with led_menu callback)
        and converts pseudo-screens that just return to hub (like console_close)
        into actions transitioning to the hub.
        """
        to_remove = set()

        # Pass A: Merge commands that open existing callback screens
        for node_id, node in list(self.nodes.items()):
            if node_id.startswith("cmd:") and node_id not in ("cmd:/start", "cmd:/help"):
                cmd_clean = node_id.split("cmd:/", 1)[-1] if "cmd:/" in node_id else node_id.split("cmd:", 1)[-1]
                cmd_clean = cmd_clean.strip().lstrip("/")
                if not node.keyboard:
                    continue

                target_screen = None
                for other_id, other_node in self.nodes.items():
                    if other_id == node_id or not other_id.startswith("cb:"):
                        continue
                    other_clean = other_id.split("cb:", 1)[-1]
                    name_matches = (
                        other_clean in (f"{cmd_clean}_menu", f"{cmd_clean}_open", cmd_clean, f"open_{cmd_clean}")
                        or other_clean.startswith(f"{cmd_clean}_")
                    )
                    kb_matches = bool(other_node.keyboard and other_node.keyboard.name == node.keyboard.name)
                    if name_matches and kb_matches:
                        target_screen = other_node
                        break
                    if other_clean in (f"{cmd_clean}_menu", f"{cmd_clean}_open", cmd_clean, f"open_{cmd_clean}") and not other_node.keyboard:
                        target_screen = other_node
                        break

                if target_screen:
                    cmd_alias = f"/{cmd_clean}"
                    if cmd_alias not in target_screen.aliases:
                        target_screen.aliases.append(cmd_alias)
                    self.screen_aliases[node_id] = target_screen.id
                    to_remove.add(node_id)

        # Pass B: Convert handlers that just re-send hub keyboard (only if explicitly named *_close, *_cancel, *_exit, *_back)
        hub_id = "cb:menu"
        hub_node = self.nodes.get(hub_id)
        if hub_node and hub_node.keyboard and getattr(hub_node.keyboard, "name", None):
            hub_kb_name = hub_node.keyboard.name
            for node_id, node in list(self.nodes.items()):
                if node_id in (hub_id, "cmd:/start") or node_id in to_remove:
                    continue

                node_clean = node_id.split(":", 1)[-1].lower()
                is_return_intent = any(node_clean.endswith(k) for k in ("_close", "_cancel", "_exit", "_back"))
                if is_return_intent and node.keyboard and node.keyboard.name == hub_kb_name:
                    node.node_type = "callback"
                    node.keyboard = None
                    self.hub_return_nodes.add(node_id)

        for rid in to_remove:
            self.nodes.pop(rid, None)

    def _extract_global_constants(self, tree: ast.AST) -> None:
        """Collects top-level module constants like CANONICAL_ICONS, EMOJI_BTN_*, etc."""
        constants = extract_module_constants(tree)
        self.global_constants.update(constants)

    def _extract_keyboards(self, tree: ast.AST, filepath: Path) -> None:
        """Finds functions, class methods, or module assignments constructing Telegram keyboards."""
        for node in getattr(tree, "body", []):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kb = self._parse_keyboard_function(node, filepath)
                if kb and kb.rows:
                    self.keyboards[node.name] = kb
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        kb = self._parse_keyboard_function(item, filepath)
                        if kb and kb.rows:
                            self.keyboards[item.name] = kb
                            self.keyboards[f"{node.name}.{item.name}"] = kb
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                name_lower = target.id.lower()
                                if any(k in name_lower for k in ("markup", "keyboard", "buttons", "menu", "kb")):
                                    kb = self._parse_keyboard_expr(item.value, target.id, filepath, getattr(item, "lineno", 0), {})
                                    if kb and kb.rows:
                                        self.keyboards[target.id] = kb
                                        self.keyboards[f"{node.name}.{target.id}"] = kb
                    elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        name_lower = item.target.id.lower()
                        if any(k in name_lower for k in ("markup", "keyboard", "buttons", "menu", "kb")):
                            if item.value:
                                kb = self._parse_keyboard_expr(item.value, item.target.id, filepath, getattr(item, "lineno", 0), {})
                                if kb and kb.rows:
                                    self.keyboards[item.target.id] = kb
                                    self.keyboards[f"{node.name}.{item.target.id}"] = kb

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name_lower = target.id.lower()
                        if any(k in name_lower for k in ("markup", "keyboard", "buttons", "menu", "kb")):
                            kb = self._parse_keyboard_expr(node.value, target.id, filepath, getattr(node, "lineno", 0), {})
                            if kb and kb.rows:
                                self.keyboards[target.id] = kb

            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name_lower = node.target.id.lower()
                if any(k in name_lower for k in ("markup", "keyboard", "buttons", "menu", "kb")):
                    if node.value:
                        kb = self._parse_keyboard_expr(node.value, node.target.id, filepath, getattr(node, "lineno", 0), {})
                        if kb and kb.rows:
                            self.keyboards[node.target.id] = kb

    def _parse_keyboard_function(self, func_node: ast.FunctionDef, filepath: Path) -> Optional[Keyboard]:
        kb_name = func_node.name

        # Scope analysis: collect function signature default arguments, local assignments, and list mutations
        local_vars: Dict[str, List[ast.AST]] = {}
        list_mutations: Dict[str, List[ast.AST]] = {}
        builders: Dict[str, List[Button]] = {}
        builder_types: Dict[str, str] = {}
        builder_adjust: Dict[str, int] = {}

        if hasattr(func_node, "args") and func_node.args:
            pos_args = [a.arg for a in getattr(func_node.args, "args", [])]
            defaults = list(getattr(func_node.args, "defaults", []))
            default_offset = len(pos_args) - len(defaults)
            param_info: List[Tuple[str, Optional[str]]] = []
            for idx, arg_name in enumerate(pos_args):
                def_str: Optional[str] = None
                if idx >= default_offset:
                    def_node = defaults[idx - default_offset]
                    local_vars.setdefault(arg_name, []).append(def_node)
                    val = _ast_to_value(def_node, {}, self.global_constants)
                    if isinstance(val, str) and val:
                        def_str = val
                if arg_name not in ("self", "cls"):
                    param_info.append((arg_name, def_str))

            kw_args = getattr(func_node.args, "kwonlyargs", [])
            kw_defs = getattr(func_node.args, "kw_defaults", [])
            for kw_arg, kw_def in zip(kw_args, kw_defs):
                def_str = None
                if kw_def is not None:
                    local_vars.setdefault(kw_arg.arg, []).append(kw_def)
                    val = _ast_to_value(kw_def, {}, self.global_constants)
                    if isinstance(val, str) and val:
                        def_str = val
                param_info.append((kw_arg.arg, def_str))

            if param_info:
                self.keyboard_param_defaults[kb_name] = param_info

        for stmt in ast.walk(func_node):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        local_vars.setdefault(target.id, []).append(stmt.value)
                        if isinstance(stmt.value, ast.Call):
                            call_name = getattr(stmt.value.func, "id", "") or getattr(stmt.value.func, "attr", "")
                            if "reply" in call_name.lower():
                                builder_types[target.id] = "reply"
                            elif "inline" in call_name.lower():
                                builder_types[target.id] = "inline"
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
                    var_name = call.func.value.id
                    method = call.func.attr
                    if method in ("append", "extend") and call.args:
                        list_mutations.setdefault(var_name, []).append(call.args[0])
                    elif method in ("add", "button", "row"):
                        builders.setdefault(var_name, [])
                        if method == "button":
                            btn = self._parse_button_element(call, local_vars)
                            if btn:
                                builders[var_name].append(btn)
                        else:
                            for arg in call.args:
                                btn = self._parse_button_element(arg, local_vars)
                                if btn:
                                    builders[var_name].append(btn)
                    elif method == "adjust" and call.args:
                        adj_val = _ast_to_value(call.args[0], local_vars, self.global_constants)
                        if isinstance(adj_val, int) and adj_val > 0:
                            builder_adjust[var_name] = adj_val

        # Check return statements
        for stmt in ast.walk(func_node):
            if isinstance(stmt, ast.Return) and stmt.value:
                # Check for delegation / alias: e.g. return self.ui.main_menu_markup(...)
                if isinstance(stmt.value, ast.Call):
                    delegated_name = getattr(stmt.value.func, "attr", None) or getattr(stmt.value.func, "id", None)
                    if delegated_name and delegated_name != kb_name and delegated_name != "as_markup":
                        self.keyboard_aliases[kb_name] = delegated_name

                    # Check if returning builder.as_markup()
                    if getattr(stmt.value.func, "attr", "") == "as_markup":
                        b_obj = getattr(stmt.value.func, "value", None)
                        b_name = getattr(b_obj, "id", "")
                        if b_name in builders and builders[b_name]:
                            btn_list = builders[b_name]
                            adj = builder_adjust.get(b_name, len(btn_list))
                            rows = [btn_list[i : i + adj] for i in range(0, len(btn_list), adj)]
                            if rows:
                                b_type = builder_types.get(b_name, "inline")
                                return Keyboard(name=kb_name, rows=rows, keyboard_type=b_type, source_file=str(filepath), line_number=stmt.lineno)

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

        # If no explicit return, check if builder was created in function
        for b_name, btn_list in builders.items():
            if btn_list:
                adj = builder_adjust.get(b_name, len(btn_list))
                rows = [btn_list[i : i + adj] for i in range(0, len(btn_list), adj)]
                if rows:
                    b_type = builder_types.get(b_name, "inline")
                    return Keyboard(name=kb_name, rows=rows, keyboard_type=b_type, source_file=str(filepath), line_number=func_node.lineno)

        return None

    @staticmethod
    def _deduplicate_rows(rows: List[List[Button]]) -> List[List[Button]]:
        seen: Set[Tuple[Optional[str], Optional[str], Optional[str]]] = set()
        deduped: List[List[Button]] = []
        for row in rows:
            clean_row: List[Button] = []
            for btn in row:
                key = (btn.text, btn.callback_data, btn.url)
                if key not in seen:
                    seen.add(key)
                    clean_row.append(btn)
            if clean_row:
                deduped.append(clean_row)
        return deduped

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
                kb_type = "inline"
                for k, v in zip(expr.keys, expr.values):
                    if isinstance(k, ast.Constant) and k.value in ("inline_keyboard", "keyboard"):
                        if k.value == "keyboard":
                            kb_type = "reply"
                        candidate_vals = [v]
                        var_id = None
                        if isinstance(v, ast.Name):
                            var_id = v.id
                            if var_id in local_vars:
                                candidate_vals = local_vars[var_id]

                        for val_node in candidate_vals:
                            if isinstance(val_node, ast.List):
                                for row_node in val_node.elts:
                                    row = self._parse_button_row(row_node, local_vars, list_mutations)
                                    if row:
                                        rows.append(row)

                        # Also append any mutations tracked for this variable
                        if var_id and var_id in list_mutations:
                            for mutated in list_mutations[var_id]:
                                row = self._parse_button_row(mutated, local_vars, list_mutations)
                                if row:
                                    rows.append(row)

                rows = self._deduplicate_rows(rows)
                if rows:
                    return Keyboard(name=name, rows=rows, keyboard_type=kb_type, source_file=str(filepath), line_number=lineno)

            # Case 2: Direct list of rows [ [ {...} ], [ {...} ] ]
            if isinstance(expr, ast.List):
                for row_node in expr.elts:
                    row = self._parse_button_row(row_node, local_vars, list_mutations)
                    if row:
                        rows.append(row)
                rows = self._deduplicate_rows(rows)
                if rows:
                    return Keyboard(name=name, rows=rows, keyboard_type="inline", source_file=str(filepath), line_number=lineno)

            # Case 3: Call InlineKeyboardMarkup(...) / ReplyKeyboardMarkup(...)
            if isinstance(expr, ast.Call):
                func_name = getattr(expr.func, "attr", None) or getattr(expr.func, "id", "")
                if any(k in func_name.lower() for k in ("markup", "keyboard")):
                    kb_type = "reply" if "reply" in func_name.lower() else "inline"
                    candidate_kw = None
                    for kw in expr.keywords:
                        if kw.arg in ("inline_keyboard", "keyboard"):
                            candidate_kw = kw.value
                            break
                    if not candidate_kw and expr.args:
                        candidate_kw = expr.args[0]

                    if candidate_kw:
                        candidate_vals = [candidate_kw]
                        if isinstance(candidate_kw, ast.Name) and candidate_kw.id in local_vars:
                            candidate_vals = local_vars[candidate_kw.id]
                        for val_node in candidate_vals:
                            if isinstance(val_node, ast.List):
                                for row_node in val_node.elts:
                                    row = self._parse_button_row(row_node, local_vars, list_mutations)
                                    if row:
                                        rows.append(row)
                        rows = self._deduplicate_rows(rows)
                        if rows:
                            return Keyboard(name=name, rows=rows, keyboard_type=kb_type, source_file=str(filepath), line_number=lineno)


    def _parse_button_row(
        self,
        row_node: ast.AST,
        local_vars: Dict[str, List[ast.AST]],
        list_mutations: Optional[Dict[str, List[ast.AST]]] = None,
    ) -> List[Button]:
        row: List[Button] = []
        if list_mutations is None:
            list_mutations = {}

        candidate_rows = [row_node]
        row_var_id: Optional[str] = None
        if isinstance(row_node, ast.Name):
            row_var_id = row_node.id
            if row_var_id in local_vars:
                candidate_rows = local_vars[row_var_id]

        for candidate in candidate_rows:
            if isinstance(candidate, ast.ListComp):
                # e.g. [KeyboardButton(text=item) for item in items]
                elt_btn = self._parse_button_element(candidate.elt, local_vars)
                if elt_btn:
                    # Try resolving generator iterable if known
                    iter_resolved = False
                    if candidate.generators:
                        iter_obj = getattr(candidate.generators[0], "iter", None)
                        if isinstance(iter_obj, ast.Name):
                            iter_name = iter_obj.id
                            items_val = self.global_constants.get(iter_name)
                            if isinstance(items_val, list):
                                iter_resolved = True
                                for item_str in items_val:
                                    row.append(
                                        Button(
                                            text=str(item_str),
                                            callback_data=elt_btn.callback_data,
                                            url=elt_btn.url,
                                            icon_custom_emoji_id=elt_btn.icon_custom_emoji_id,
                                            style=elt_btn.style,
                                        )
                                    )
                    if not iter_resolved:
                        row.append(elt_btn)
            elif isinstance(candidate, ast.List):
                for elt in candidate.elts:
                    candidate_elts = [elt]
                    if isinstance(elt, ast.Name) and elt.id in local_vars:
                        vars_list = local_vars[elt.id]
                        if isinstance(vars_list, list) and vars_list:
                            candidate_elts = list(vars_list)
                        elif vars_list is not None:
                            candidate_elts = [vars_list]
                    for c_elt in candidate_elts:
                        sub_elts = [c_elt.body, c_elt.orelse] if isinstance(c_elt, ast.IfExp) else [c_elt]
                        for s_elt in sub_elts:
                            btn = self._parse_button_element(s_elt, local_vars)
                            if btn:
                                row.append(btn)
            elif isinstance(candidate, ast.Call):
                btn = self._parse_helper_call(candidate)
                if not btn:
                    btn = self._parse_button_element(candidate, local_vars)
                if btn:
                    row.append(btn)
            elif isinstance(candidate, ast.Dict):
                btn = self._parse_button_element(candidate, local_vars)
                if btn:
                    row.append(btn)

        # Include buttons dynamically appended to this row variable (e.g. action_row.append(cancel_btn))
        if row_var_id and row_var_id in list_mutations:
            for mut_elt in list_mutations[row_var_id]:
                candidate_elts = [mut_elt]
                if isinstance(mut_elt, ast.Name) and mut_elt.id in local_vars:
                    vars_list = local_vars[mut_elt.id]
                    if isinstance(vars_list, list) and vars_list:
                        candidate_elts = list(vars_list)
                    elif vars_list is not None:
                        candidate_elts = [vars_list]
                for c_elt in candidate_elts:
                    sub_elts = [c_elt.body, c_elt.orelse] if isinstance(c_elt, ast.IfExp) else [c_elt]
                    for s_elt in sub_elts:
                        btn = self._parse_button_element(s_elt, local_vars)
                        if btn:
                            row.append(btn)

        return row

    def _parse_helper_call(self, call_node: ast.Call) -> Optional[Button]:
        func_name = getattr(call_node.func, "attr", None) or getattr(call_node.func, "id", "")
        f_lower = func_name.lower()
        is_back = (
            f_lower.startswith("back")
            or f_lower.endswith(("_back", "_back_btn", "_back_button"))
            or f_lower in ("back", "back_button", "back_btn", "btn_back", "get_back_button")
        )
        if is_back:
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
            if icon_emoji:
                self.custom_emoji_ids.add(str(icon_emoji))
            style = d.get("style")
            return Button(
                text=text,
                callback_data=cb,
                url=url,
                icon_custom_emoji_id=str(icon_emoji) if icon_emoji is not None else None,
                style=str(style) if style else None,
                line_number=getattr(elt_node, "lineno", None),
            )

        # Call: InlineKeyboardButton(text="...", callback_data="...") or KeyboardButton(...)
        if isinstance(elt_node, ast.Call):
            kwargs: Dict[str, Any] = {}
            for kw in elt_node.keywords:
                val = _ast_to_value(kw.value, local_vars or {}, self.global_constants)
                if val is None and isinstance(kw.value, ast.Call):
                    # CallbackData factory call, e.g. NumbersCallbackFactory(action="change", value=-2)
                    # or aiogram 3: NumbersCallbackFactory(action="change", value=-2).pack()
                    call_node = kw.value
                    if isinstance(call_node.func, ast.Attribute) and call_node.func.attr == "pack":
                        if isinstance(call_node.func.value, ast.Call):
                            call_node = call_node.func.value
                    call_name = getattr(call_node.func, "attr", None) or getattr(call_node.func, "id", "")
                    if call_name and call_name not in ("str", "int", "float", "len", "bool", "range", "pack"):
                        action_val = ""
                        for inner_kw in call_node.keywords:
                            if inner_kw.arg in ("action", "act", "type"):
                                inner_v = _ast_to_value(inner_kw.value, local_vars or {}, self.global_constants)
                                action_val = f":{inner_v}" if inner_v else ""
                        val = f"{call_name}{action_val}"
                kwargs[kw.arg] = val

            text_val = kwargs.get("text")
            if not text_val and elt_node.args:
                text_val = _ast_to_value(elt_node.args[0], local_vars or {}, self.global_constants)

            cb_val = kwargs.get("callback_data")
            if not cb_val and len(elt_node.args) > 1:
                cb_val = _ast_to_value(elt_node.args[1], local_vars or {}, self.global_constants)

            icon_emoji = kwargs.get("icon_custom_emoji_id")
            if icon_emoji:
                self.custom_emoji_ids.add(str(icon_emoji))
            style_val = kwargs.get("style")

            text = str(text_val or "Button")
            cb = str(cb_val) if cb_val is not None else None
            return Button(
                text=text,
                callback_data=cb,
                url=str(kwargs.get("url", "")) if kwargs.get("url") else None,
                icon_custom_emoji_id=str(icon_emoji) if icon_emoji is not None else None,
                style=str(style_val) if style_val else None,
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
        inline_kb: Optional[Keyboard] = None,
        aliases: Optional[List[str]] = None,
    ) -> None:
        node = MessageNode(
            id=node_id,
            title=title,
            text_template=text_template,
            source_file=str(source_file),
            line_number=lineno,
            trigger_type=trigger_type,
            trigger_pattern=trigger_pattern,
            aliases=aliases or [],
        )

        if text_template:
            for match in re.finditer(r'<tg-emoji[^>]*emoji-id=[\'"](\d+)[\'"]', text_template):
                self.custom_emoji_ids.add(match.group(1))

        # Attach resolved keyboard reference first, falling back to local inline keyboard
        resolved_kb = None
        if kb_ref:
            resolved_kb = (
                self.keyboards.get(kb_ref)
                or self.keyboards.get(self.keyboard_aliases.get(kb_ref, ""))
                or self.keyboards.get(kb_ref.split(".")[-1])
                or self.keyboards.get(kb_ref.lstrip("_"))
            )
        if resolved_kb:
            node.keyboard = resolved_kb
        elif inline_kb and inline_kb.rows:
            node.keyboard = inline_kb

        # Classify node_type
        if node_id.startswith("cmd:") or trigger_type == "command":
            node.node_type = "command"
        elif node.keyboard and node.keyboard.rows and len(node.keyboard.rows) > 0:
            node.node_type = "message"
        elif any(k in node_id.lower() for k in ("cancel", "retry", "noop", "close")):
            node.node_type = "popup"
            node.is_alert = True
        else:
            node.node_type = "callback"

        self.nodes[node_id] = node

    def _extract_route_conditions(self, test_node: ast.AST) -> List[Tuple[str, str]]:
        routes: List[Tuple[str, str]] = []

        # Handle boolean combinations: if data == "a" or data == "b":
        if isinstance(test_node, ast.BoolOp):
            for val_sub in test_node.values:
                routes.extend(self._extract_route_conditions(val_sub))
            return routes

        # Case 1: Comparisons (==, in)
        if isinstance(test_node, ast.Compare):
            left_kind = _classify_operand_source(test_node.left)
            left_val = _ast_to_value(test_node.left, {}, self.global_constants)

            for op, comp in zip(test_node.ops, test_node.comparators):
                comp_kind = _classify_operand_source(comp)
                comp_val = _ast_to_value(comp, {}, self.global_constants)

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
                                val = _ast_to_value(elt, {}, self.global_constants)
                                if val is not None:
                                    routes.append((str(val).strip("'\""), left_kind))
                    # Reverse: "a" in target
                    elif comp_kind and left_val is not None:
                        routes.append((str(left_val).strip("'\""), comp_kind))

        # Case 2: Method calls like data.startswith("volume:") or message.text.startswith(("/stealth", "скрытность"))
        if isinstance(test_node, ast.Call) and isinstance(test_node.func, ast.Attribute):
            if test_node.func.attr == "startswith":
                val_node = test_node.func.value
                val_kind = _classify_operand_source(val_node)
                if val_kind and test_node.args:
                    val = _ast_to_value(test_node.args[0], {}, self.global_constants)
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

    def _specialize_keyboard_call(
        self, call_node: ast.Call, kb_name: str, local_body_vars: Dict[str, Any]
    ) -> str:
        """If a parameterized keyboard function is called with custom string prefix arguments,
        clone the keyboard with the substituted callback_data prefix.
        """
        base_kb = (
            self.keyboards.get(kb_name)
            or self.keyboards.get(self.keyboard_aliases.get(kb_name, ""))
            or self.keyboards.get(kb_name.split(".")[-1])
            or self.keyboards.get(kb_name.lstrip("_"))
        )
        if not base_kb:
            return kb_name

        param_info = self.keyboard_param_defaults.get(base_kb.name)
        if not param_info:
            return kb_name

        substitutions: Dict[str, str] = {}
        for idx, arg_node in enumerate(call_node.args):
            if idx < len(param_info):
                p_name, def_str = param_info[idx]
                if def_str:
                    passed = _ast_to_value(arg_node, local_body_vars, self.global_constants)
                    if isinstance(passed, str) and passed and not passed.startswith("$") and passed != def_str:
                        substitutions[def_str] = passed

        param_dict = dict(param_info)
        for kw in call_node.keywords:
            if kw.arg and kw.arg in param_dict and param_dict[kw.arg]:
                def_str = param_dict[kw.arg]
                passed = _ast_to_value(kw.value, local_body_vars, self.global_constants)
                if def_str and isinstance(passed, str) and passed and not passed.startswith("$") and passed != def_str:
                    substitutions[def_str] = passed

        if not substitutions:
            return kb_name

        suffix = "_".join(substitutions.values())
        spec_name = f"{base_kb.name}:{suffix}"
        if spec_name in self.keyboards:
            return spec_name

        new_rows: List[List[Button]] = []
        changed = False
        for row in base_kb.rows:
            new_row: List[Button] = []
            for btn in row:
                new_cb = btn.callback_data
                if new_cb:
                    for old_s, new_s in substitutions.items():
                        if old_s in new_cb:
                            new_cb = new_cb.replace(old_s, new_s)
                            changed = True
                new_row.append(
                    Button(
                        text=btn.text,
                        callback_data=new_cb,
                        url=btn.url,
                        icon_custom_emoji_id=btn.icon_custom_emoji_id,
                        style=btn.style,
                        line_number=btn.line_number,
                    )
                )
            new_rows.append(new_row)

        if not changed:
            return kb_name

        spec_kb = Keyboard(
            name=spec_name,
            rows=new_rows,
            keyboard_type=base_kb.keyboard_type,
            source_file=base_kb.source_file,
            line_number=base_kb.line_number,
        )
        self.keyboards[spec_name] = spec_kb
        return spec_name

    def _find_message_dispatch(
        self, body: List[ast.stmt], filepath: Path
    ) -> Tuple[str, Optional[str], Optional[Keyboard]]:
        text_str = ""
        kb_name = None
        inline_kb: Optional[Keyboard] = None

        local_body_vars: Dict[str, Any] = {}
        local_body_nodes: Dict[str, List[ast.AST]] = {}
        builders: Dict[str, List[Button]] = {}
        builder_types: Dict[str, str] = {}
        builder_adjust: Dict[str, int] = {}

        for stmt in body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Assign):
                    for target in sub.targets:
                        if isinstance(target, ast.Name):
                            local_body_nodes.setdefault(target.id, []).append(sub.value)
                            val = _ast_to_value(sub.value, local_body_vars, self.global_constants)
                            if val is not None and target.id not in local_body_vars:
                                local_body_vars[target.id] = val
                            if isinstance(sub.value, ast.Call):
                                call_fn = getattr(sub.value.func, "id", "") or getattr(sub.value.func, "attr", "")
                                if "reply" in call_fn.lower():
                                    builder_types[target.id] = "reply"
                                elif "inline" in call_fn.lower():
                                    builder_types[target.id] = "inline"
                elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and isinstance(sub.func.value, ast.Name):
                    var_name = sub.func.value.id
                    method = sub.func.attr
                    if method in ("add", "button", "row"):
                        builders.setdefault(var_name, [])
                        if method == "button":
                            btn = self._parse_button_element(sub, local_body_vars)
                            if btn:
                                builders[var_name].append(btn)
                        else:
                            for arg in sub.args:
                                btn = self._parse_button_element(arg, local_body_vars)
                                if btn:
                                    builders[var_name].append(btn)
                    elif method == "adjust" and sub.args:
                        adj_val = _ast_to_value(sub.args[0], local_body_vars, self.global_constants)
                        if isinstance(adj_val, int) and adj_val > 0:
                            builder_adjust[var_name] = adj_val

        fallback_toast: Optional[str] = None
        for stmt in body:
            for subnode in ast.walk(stmt):
                if isinstance(subnode, ast.Call):
                    func_name = getattr(subnode.func, "attr", None) or getattr(subnode.func, "id", "")
                    func_low = func_name.lower()
                    if any(k in func_low for k in ("send_message", "edit_message", "edit_text", "edit_caption", "send_photo", "sendphoto", "answer", "send_player_card")):
                        caller_id = ""
                        if isinstance(subnode.func, ast.Attribute) and isinstance(subnode.func.value, ast.Name):
                            caller_id = subnode.func.value.id.lower()
                        has_markup = any(kw.arg == "reply_markup" for kw in subnode.keywords)
                        has_alert = any(kw.arg in ("show_alert", "cache_time") for kw in subnode.keywords)

                        if "callback" in func_low or "callbackquery" in func_low or has_alert:
                            is_toast = True
                        elif func_low == "answer":
                            is_toast = caller_id in ("call", "callback", "callback_query", "query", "cb") and not has_markup
                        else:
                            is_toast = False
                        for arg in subnode.args:
                            val = _ast_to_value(arg, local_body_vars, self.global_constants)
                            if isinstance(val, str) and len(val) > 2 and not val.startswith("$"):
                                if not is_toast and not text_str:
                                    text_str = val
                                elif not text_str and not fallback_toast:
                                    fallback_toast = val
                        for kw in subnode.keywords:
                            if kw.arg in ("text", "caption"):
                                val = _ast_to_value(kw.value, local_body_vars, self.global_constants)
                                if isinstance(val, str) and val:
                                    if not is_toast and not text_str:
                                        text_str = val
                                    elif not text_str and not fallback_toast:
                                        fallback_toast = val
                            elif kw.arg == "reply_markup":
                                lineno = getattr(kw.value, "lineno", getattr(subnode, "lineno", 0))
                                if isinstance(kw.value, ast.Dict):
                                    parsed_inline = self._parse_keyboard_expr(
                                        kw.value,
                                        f"inline_{lineno}",
                                        filepath,
                                        lineno,
                                        local_body_nodes,
                                    )
                                    if parsed_inline and not inline_kb:
                                        inline_kb = parsed_inline
                                elif isinstance(kw.value, ast.Name):
                                    var_id = kw.value.id
                                    if var_id in local_body_nodes:
                                        for node_val in local_body_nodes[var_id]:
                                            if isinstance(node_val, ast.Call):
                                                c_func = getattr(node_val.func, "attr", None) or getattr(node_val.func, "id", "")
                                                if c_func == "as_markup":
                                                    b_obj = getattr(node_val.func, "value", None)
                                                    b_name = getattr(b_obj, "id", "")
                                                    if b_name in builders and builders[b_name]:
                                                        btn_list = builders[b_name]
                                                        adj = builder_adjust.get(b_name, len(btn_list))
                                                        rows = [btn_list[i : i + adj] for i in range(0, len(btn_list), adj)]
                                                        if rows and not inline_kb:
                                                            b_type = builder_types.get(b_name, "inline")
                                                            inline_kb = Keyboard(name=f"inline_{lineno}", rows=rows, keyboard_type=b_type, source_file=str(filepath), line_number=lineno)
                                                if c_func in self.keyboards or any(k.endswith(f".{c_func}") for k in self.keyboards) or c_func.lstrip("_") in self.keyboards:
                                                    if not kb_name:
                                                        kb_name = self._specialize_keyboard_call(node_val, c_func, local_body_vars)
                                                elif any(k in c_func.lower() for k in ("markup", "keyboard")):
                                                    parsed_inline = self._parse_keyboard_expr(
                                                        node_val,
                                                        f"{var_id}_{lineno}",
                                                        filepath,
                                                        lineno,
                                                        local_body_nodes,
                                                    )
                                                    if parsed_inline and not inline_kb:
                                                        inline_kb = parsed_inline
                                                    elif not kb_name:
                                                        kb_name = self._specialize_keyboard_call(node_val, c_func, local_body_vars)
                                                elif not kb_name:
                                                    kb_name = self._specialize_keyboard_call(node_val, c_func, local_body_vars)
                                            else:
                                                parsed_inline = self._parse_keyboard_expr(
                                                    node_val,
                                                    f"{var_id}_{lineno}",
                                                    filepath,
                                                    lineno,
                                                    local_body_nodes,
                                                )
                                                if parsed_inline and not inline_kb:
                                                    inline_kb = parsed_inline
                                    elif not kb_name:
                                        kb_name = var_id
                                elif isinstance(kw.value, ast.Attribute):
                                    attr_name = kw.value.attr
                                    val_obj = getattr(kw.value.value, "id", "")
                                    full_name = f"{val_obj}.{attr_name}" if val_obj else attr_name
                                    if full_name in self.keyboards:
                                        kb_name = kb_name or full_name
                                    else:
                                        kb_name = kb_name or attr_name
                                elif isinstance(kw.value, ast.Call):
                                    c_func = getattr(kw.value.func, "attr", None) or getattr(kw.value.func, "id", "")
                                    if c_func == "as_markup":
                                        b_obj = getattr(kw.value.func, "value", None)
                                        b_name = getattr(b_obj, "id", "")
                                        if b_name in builders and builders[b_name]:
                                            btn_list = builders[b_name]
                                            adj = builder_adjust.get(b_name, len(btn_list))
                                            rows = [btn_list[i : i + adj] for i in range(0, len(btn_list), adj)]
                                            if rows and not inline_kb:
                                                b_type = builder_types.get(b_name, "inline")
                                                inline_kb = Keyboard(name=f"inline_{lineno}", rows=rows, keyboard_type=b_type, source_file=str(filepath), line_number=lineno)
                                    elif c_func in self.keyboards or c_func.lstrip("_") in self.keyboards:
                                        if not kb_name:
                                            kb_name = self._specialize_keyboard_call(kw.value, c_func, local_body_vars)
                                    elif any(k in c_func for k in ("InlineKeyboardMarkup", "ReplyKeyboardMarkup")):
                                        parsed_inline = self._parse_keyboard_expr(
                                            kw.value,
                                            f"inline_{lineno}",
                                            filepath,
                                            lineno,
                                            local_body_nodes,
                                        )
                                        if parsed_inline and not inline_kb:
                                            inline_kb = parsed_inline
                                    elif not kb_name:
                                        kb_name = self._specialize_keyboard_call(kw.value, c_func, local_body_vars)

        if not text_str and fallback_toast:
            text_str = fallback_toast

        return text_str, kb_name, inline_kb

    def _inspect_decorated_handler(self, func_node: ast.FunctionDef, filepath: Path) -> None:
        """aiogram / telebot decorators: @dp.callback_query(...) or @dp.message(Command(...))"""
        for dec in func_node.decorator_list:
            dec_str = ast.unparse(dec) if hasattr(ast, "unparse") else ""
            dec_low = dec_str.lower()

            # 1. Callback query handlers
            if "callback" in dec_low:
                routes: List[str] = []
                for m in re.finditer(r'F\.data\s*==\s*["\']([\w:-]+)["\']', dec_str):
                    routes.append(m.group(1))
                for m in re.finditer(r'F\.data\.startswith\(\s*["\']([\w:-]+)["\']', dec_str):
                    routes.append(f"{m.group(1)}*")
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


    def _extract_set_my_commands(self, tree: ast.AST, filepath: Path) -> None:
        """Extracts bot commands registered in set_my_commands / setMyCommands calls."""
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func_name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            if func_name not in ("set_my_commands", "setMyCommands"):
                continue

            self.has_set_my_commands = True
            commands_node = None

            for kw in node.keywords:
                if kw.arg in ("commands", "custom_commands"):
                    commands_node = kw.value
                    break

            if commands_node is None and node.args:
                commands_node = node.args[0]

            if commands_node is None:
                continue

            self._parse_commands_list(commands_node, tree)

    def _parse_commands_list(self, node: ast.AST, tree: Optional[ast.AST] = None) -> None:
        """Parses a list/tuple of BotCommand objects or variable reference."""
        if isinstance(node, (ast.List, ast.Tuple)):
            for elt in node.elts:
                cmd_name = self._extract_single_bot_command(elt)
                if cmd_name:
                    self.registered_menu_commands.add(str(cmd_name).strip().lstrip("/"))
        elif isinstance(node, ast.Name):
            var_val = self.global_constants.get(node.id)
            if isinstance(var_val, list):
                for item in var_val:
                    if isinstance(item, str):
                        self.registered_menu_commands.add(item.strip().lstrip("/"))
                    elif isinstance(item, dict) and "command" in item:
                        self.registered_menu_commands.add(str(item["command"]).strip().lstrip("/"))
            elif tree is not None:
                for n in ast.walk(tree):
                    if isinstance(n, (ast.Assign, ast.AnnAssign)):
                        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                        for t in targets:
                            if isinstance(t, ast.Name) and t.id == node.id and n.value:
                                self._parse_commands_list(n.value, tree)
                                return

    def _extract_single_bot_command(self, elt: ast.AST) -> Optional[str]:
        """Extracts command name from BotCommand call, dict, tuple or constant."""
        if isinstance(elt, ast.Call):
            for kw in elt.keywords:
                if kw.arg in ("command", "cmd"):
                    val = _ast_to_value(kw.value, {}, self.global_constants)
                    if val is not None:
                        return str(val)
            if elt.args:
                val = _ast_to_value(elt.args[0], {}, self.global_constants)
                if val is not None:
                    return str(val)
        elif isinstance(elt, ast.Dict):
            for k, v in zip(elt.keys, elt.values):
                if isinstance(k, ast.Constant) and k.value in ("command", "cmd"):
                    val = _ast_to_value(v, {}, self.global_constants)
                    if val is not None:
                        return str(val)
        elif isinstance(elt, (ast.Tuple, ast.List)) and elt.elts:
            val = _ast_to_value(elt.elts[0], {}, self.global_constants)
            if val is not None:
                return str(val)
        elif isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            return elt.value
        return None
