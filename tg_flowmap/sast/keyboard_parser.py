from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from tg_flowmap.core.models import Button, Keyboard
from tg_flowmap.sast.evaluator import _ast_to_value


class KeyboardStore(dict):
    """Dictionary-compatible container that dynamically resolves module-scoped keyboards."""
    def __init__(self, parser_ref: Any):
        super().__init__()
        self._parser = parser_ref

    def __getitem__(self, key: str) -> Keyboard:
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        kb = self._parser.get_keyboard(key)
        if kb is not None:
            return kb
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        if dict.__contains__(self, key):
            return True
        if isinstance(key, str) and self._parser.get_keyboard(key) is not None:
            return True
        return False

    def get(self, key: str, default: Any = None) -> Any:
        if dict.__contains__(self, key):
            return dict.get(self, key, default)
        kb = self._parser.get_keyboard(key)
        if kb is not None:
            return kb
        return default


class KeyboardParserMixin:
    """Mixin extracting, resolving, and specializing Telegram keyboards from AST."""

    def _extract_keyboards(self, tree: ast.AST, filepath: Path) -> None:
        """Finds functions, class methods, or module assignments constructing Telegram keyboards."""
        self._current_filepath = filepath
        stem = filepath.stem
        file_str = str(filepath)
        mod_dict = self.module_keyboards.setdefault(stem, {})
        file_dict = self.module_keyboards.setdefault(file_str, {})

        def _register_kb(name: str, kb: Keyboard, class_name: Optional[str] = None):
            mod_dict[name] = kb
            file_dict[name] = kb
            if class_name:
                mod_dict[f"{class_name}.{name}"] = kb
                file_dict[f"{class_name}.{name}"] = kb
                dict.__setitem__(self.keyboards, f"{class_name}.{name}", kb)

            self._keyboard_source_modules.setdefault(name, set()).add(stem)

            # Preserve backward-compatible lookup when symbol is first seen
            if not dict.__contains__(self.keyboards, name):
                dict.__setitem__(self.keyboards, name, kb)

        for node in getattr(tree, "body", []):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kb = self._parse_keyboard_function(node, filepath)
                if kb and kb.rows:
                    _register_kb(node.name, kb)
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        kb = self._parse_keyboard_function(item, filepath)
                        if kb and kb.rows:
                            _register_kb(item.name, kb, class_name=node.name)
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                name_lower = target.id.lower()
                                if any(k in name_lower for k in ("markup", "keyboard", "buttons", "menu", "kb")):
                                    kb = self._parse_keyboard_expr(item.value, target.id, filepath, getattr(item, "lineno", 0), {})
                                    if kb and kb.rows:
                                        _register_kb(target.id, kb, class_name=node.name)
                    elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        name_lower = item.target.id.lower()
                        if any(k in name_lower for k in ("markup", "keyboard", "buttons", "menu", "kb")):
                            if item.value:
                                kb = self._parse_keyboard_expr(item.value, item.target.id, filepath, getattr(item, "lineno", 0), {})
                                if kb and kb.rows:
                                    _register_kb(item.target.id, kb, class_name=node.name)

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name_lower = target.id.lower()
                        if any(k in name_lower for k in ("markup", "keyboard", "buttons", "menu", "kb")):
                            kb = self._parse_keyboard_expr(node.value, target.id, filepath, getattr(node, "lineno", 0), {})
                            if kb and kb.rows:
                                _register_kb(target.id, kb)

            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name_lower = node.target.id.lower()
                if any(k in name_lower for k in ("markup", "keyboard", "buttons", "menu", "kb")):
                    if node.value:
                        kb = self._parse_keyboard_expr(node.value, node.target.id, filepath, getattr(node, "lineno", 0), {})
                        if kb and kb.rows:
                            _register_kb(node.target.id, kb)

    def _parse_keyboard_function(self, func_node: ast.FunctionDef, filepath: Path) -> Optional[Keyboard]:
        self._current_filepath = filepath
        active_constants = self._get_constants_for_file(filepath)
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
                    val = _ast_to_value(def_node, {}, active_constants)
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
                    val = _ast_to_value(kw_def, {}, active_constants)
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
                        adj_val = _ast_to_value(call.args[0], local_vars, active_constants)
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
                            active_constants = self._get_constants_for_file()
                            items_val = active_constants.get(iter_name)
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
                active_constants = self._get_constants_for_file()
                val = _ast_to_value(call_node.args[0], {}, active_constants)
                if val:
                    target = str(val).strip("'\"")
            return Button(text="« Назад", callback_data=target, line_number=getattr(call_node, "lineno", None))
        return None

    def _parse_button_element(self, elt_node: ast.AST, local_vars: Optional[Dict[str, Any]] = None) -> Optional[Button]:
        active_constants = self._get_constants_for_file()
        # Dictionary literal: {"text": "...", "callback_data": "..."}
        if isinstance(elt_node, ast.Dict):
            d: Dict[str, Any] = {}
            for k, v in zip(elt_node.keys, elt_node.values):
                if isinstance(k, ast.Constant):
                    val = _ast_to_value(v, local_vars or {}, active_constants)
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
                val = _ast_to_value(kw.value, local_vars or {}, active_constants)
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
                                inner_v = _ast_to_value(inner_kw.value, local_vars or {}, active_constants)
                                action_val = f":{inner_v}" if inner_v else ""
                        val = f"{call_name}{action_val}"
                kwargs[kw.arg] = val

            text_val = kwargs.get("text")
            if not text_val and elt_node.args:
                text_val = _ast_to_value(elt_node.args[0], local_vars or {}, active_constants)

            cb_val = kwargs.get("callback_data")
            if not cb_val and len(elt_node.args) > 1:
                cb_val = _ast_to_value(elt_node.args[1], local_vars or {}, active_constants)

            icon_emoji = kwargs.get("icon_custom_emoji_id")
            if icon_emoji:
                self.custom_emoji_ids.add(str(icon_emoji))
            style_val = kwargs.get("style")

            text = str(text_val or "Button")
            cb = str(cb_val) if cb_val is not None else None
            web_app_val = kwargs.get("web_app")
            switch_inline_val = kwargs.get("switch_inline_query") or kwargs.get("switch_inline_query_current_chat")
            pay_val = bool(kwargs.get("pay")) if "pay" in kwargs else None

            return Button(
                text=text,
                callback_data=cb,
                url=str(kwargs.get("url", "")) if kwargs.get("url") else None,
                web_app=str(web_app_val) if web_app_val else None,
                switch_inline_query=str(switch_inline_val) if switch_inline_val else None,
                pay=pay_val,
                icon_custom_emoji_id=str(icon_emoji) if icon_emoji is not None else None,
                style=str(style_val) if style_val else None,
                line_number=getattr(elt_node, "lineno", None),
            )

        return None

    def _specialize_keyboard_call(
        self, call_node: ast.Call, kb_name: str, local_body_vars: Dict[str, Any], filepath: Optional[Path] = None
    ) -> str:
        """If a parameterized keyboard function is called with custom string prefix arguments,
        clone the keyboard with the substituted callback_data prefix.
        """
        target_file = filepath or self._current_filepath
        active_constants = self._get_constants_for_file(target_file)
        base_kb = self.get_keyboard(kb_name, target_file)
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
                    passed = _ast_to_value(arg_node, local_body_vars, active_constants)
                    if isinstance(passed, str) and passed and not passed.startswith("$") and passed != def_str:
                        substitutions[def_str] = passed

        param_dict = dict(param_info)
        for kw in call_node.keywords:
            if kw.arg and kw.arg in param_dict and param_dict[kw.arg]:
                def_str = param_dict[kw.arg]
                passed = _ast_to_value(kw.value, local_body_vars, active_constants)
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
        if target_file is not None:
            self.module_keyboards.setdefault(target_file.stem, {})[spec_name] = spec_kb
            self.module_keyboards.setdefault(str(target_file), {})[spec_name] = spec_kb
        return spec_name
