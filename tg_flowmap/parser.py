from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from tg_flowmap.ast_evaluator import _ast_to_value, evaluate_ast_node, extract_module_constants
from tg_flowmap.models import Button, Keyboard, MessageNode


class AstParser:
    def __init__(self):
        self.keyboards: Dict[str, Keyboard] = {}
        self.nodes: Dict[str, MessageNode] = {}
        self.raw_files: Dict[str, str] = {}
        self.keyboard_aliases: Dict[str, str] = {}
        self.screen_aliases: Dict[str, str] = {}
        self.hub_return_nodes: Set[str] = set()
        self.global_constants: Dict[str, Any] = {}
        self.custom_emoji_ids: Set[str] = set()

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

        self._consolidate_duplicate_screens()

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
        self._consolidate_duplicate_screens()

    def _consolidate_duplicate_screens(self) -> None:
        """Merges duplicate screens (e.g. /led command with led_menu callback)
        and converts pseudo-screens that just return to hub (like console_close)
        into actions transitioning to the hub.
        """
        hub_id = "cb:menu"
        hub_node = self.nodes.get(hub_id)
        if not hub_node or not hub_node.keyboard or not getattr(hub_node.keyboard, "name", None):
            return

        hub_kb_name = hub_node.keyboard.name

        to_remove = set()

        # Pass A: Merge commands that open existing callback screens
        for node_id, node in list(self.nodes.items()):
            if node_id.startswith("cmd:") and node_id not in ("cmd:/start", "cmd:/help"):
                cmd_clean = node_id.split("cmd:/", 1)[-1].strip()
                if not node.keyboard:
                    continue

                target_screen = None
                for other_id, other_node in self.nodes.items():
                    if other_id == node_id or not other_id.startswith("cb:"):
                        continue
                    if other_node.keyboard and other_node.keyboard.name == node.keyboard.name:
                        target_screen = other_node
                        break
                    other_clean = other_id.split("cb:", 1)[-1]
                    if other_clean in (f"{cmd_clean}_menu", f"{cmd_clean}_open", cmd_clean):
                        target_screen = other_node
                        break

                if target_screen:
                    cmd_alias = f"/{cmd_clean}"
                    if cmd_alias not in target_screen.aliases:
                        target_screen.aliases.append(cmd_alias)
                    self.screen_aliases[node_id] = target_screen.id
                    to_remove.add(node_id)

        # Pass B: Convert handlers that just re-send hub keyboard (only if explicitly named *_close, *_cancel, *_exit, *_back)
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
        builders: Dict[str, List[Button]] = {}
        builder_types: Dict[str, str] = {}
        builder_adjust: Dict[str, int] = {}

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
                    return Keyboard(name=name, rows=rows, keyboard_type=kb_type, source_file=str(filepath), line_number=lineno)

            # Case 2: Direct list of rows [ [ {...} ], [ {...} ] ]
            if isinstance(expr, ast.List):
                for row_node in expr.elts:
                    row = self._parse_button_row(row_node, local_vars)
                    if row:
                        rows.append(row)
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
                                    row = self._parse_button_row(row_node, local_vars)
                                    if row:
                                        rows.append(row)
                        if rows:
                            return Keyboard(name=name, rows=rows, keyboard_type=kb_type, source_file=str(filepath), line_number=lineno)


    def _parse_button_row(self, row_node: ast.AST, local_vars: Dict[str, List[ast.AST]]) -> List[Button]:
        row: List[Button] = []

        candidate_rows = [row_node]
        if isinstance(row_node, ast.Name) and row_node.id in local_vars:
            candidate_rows = local_vars[row_node.id]

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
                                    row.append(Button(text=str(item_str), callback_data=elt_btn.callback_data))
                    if not iter_resolved:
                        row.append(elt_btn)
            elif isinstance(candidate, ast.List):
                for elt in candidate.elts:
                    candidate_elts = [elt]
                    if isinstance(elt, ast.Name) and elt.id in local_vars:
                        candidate_elts = [local_vars[elt.id][0]]
                    for c_elt in candidate_elts:
                        btn = self._parse_button_element(c_elt, local_vars)
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
                    call_name = getattr(kw.value.func, "attr", None) or getattr(kw.value.func, "id", "")
                    if call_name and call_name not in ("str", "int", "float", "len", "bool", "range"):
                        action_val = ""
                        for inner_kw in kw.value.keywords:
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
            route_val = None
            if hasattr(ast, "MatchValue") and isinstance(pattern, ast.MatchValue):
                val = _ast_to_value(pattern.value, {}, self.global_constants)
                if val:
                    route_val = str(val)

            if route_val:
                text_template, kb_ref, inline_kb = self._find_message_dispatch(case.body, filepath)
                self._add_node(
                    node_id=f"cb:{route_val}",
                    title=route_val,
                    text_template=text_template or f"Экран {route_val}",
                    source_file=filepath,
                    lineno=case.pattern.lineno,
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

        prefix = "cmd:" if trigger_type == "command" else "cb:"
        node_id = f"{prefix}{canonical_key}"
        aliases = [k for k, _ in route_keys if k != canonical_key]

        title_str = canonical_key
        if aliases:
            title_str = f"{canonical_key} ({', '.join(aliases[:2])})"

        self._add_node(
            node_id=node_id,
            title=title_str,
            text_template=text_template or f"Экран {canonical_key}",
            source_file=filepath,
            lineno=if_node.lineno,
            trigger_type=trigger_type,
            trigger_pattern=canonical_key,
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
        if not text_template or text_template in (f"Экран {title}", f"Handler {title}"):
            t_low = title.lower()
            if "sound" in t_low or "volume" in t_low:
                text_template = "🔊 <b>Управление звуком</b>\n\nВыберите уровень громкости или действие:"
            elif "led" in t_low:
                text_template = "💡 <b>Подсветка (ARGB)</b>\n\nВыберите пресет или настройте яркость:"
            elif "power" in t_low:
                text_template = "⚡ <b>Управление питанием</b>\n\nВыберите режим работы ПК:"
            elif "settings" in t_low:
                text_template = "⚙️ <b>Настройки и сервисы</b>\n\nВыберите нужный раздел:"
            elif "apps" in t_low:
                text_template = "🎮 <b>Быстрый запуск программ</b>\n\nВыберите приложение:"
            elif "history" in t_low:
                text_template = "📊 <b>История и графики</b>\n\nВыберите метрику телеметрии:"
            elif "monitoring" in t_low:
                text_template = "📈 <b>Мониторинг железа</b>\n\nСводка загрузки процессора и видеокарты:"
            elif "reboot" in t_low:
                text_template = "🔄 <b>Перезагрузка ПК</b>\n\nВы уверены, что хотите перезагрузить компьютер?"
            elif "shutdown" in t_low:
                text_template = "🛑 <b>Выключение ПК</b>\n\nВыберите тип или подтвердите выключение:"
            elif "sleep" in t_low:
                text_template = "💤 <b>Спящий режим</b>\n\nПеревести компьютер в спящий режим?"
            elif "workspace" in t_low:
                text_template = "🚀 <b>Рабочий сетап</b>\n\nЗапустить рабочий набор приложений и VPN?"
            elif "physical" in t_low:
                text_template = "🕹 <b>Физическая кнопка</b>\n\nУправление жестами и кодами разблокировки:"

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

        # Attach local inline keyboard or resolve keyboard reference
        if inline_kb and inline_kb.rows:
            node.keyboard = inline_kb
        elif kb_ref:
            resolved_kb = (
                self.keyboards.get(kb_ref)
                or self.keyboards.get(self.keyboard_aliases.get(kb_ref, ""))
                or self.keyboards.get(kb_ref.lstrip("_"))
            )
            if resolved_kb:
                node.keyboard = resolved_kb

        # Classify node_type
        if node_id.startswith("cmd:") or trigger_type == "command":
            node.node_type = "command"
        elif any(k in node_id.lower() for k in ("cancel", "retry", "noop", "close")):
            node.node_type = "popup"
            node.is_alert = True
        elif node.keyboard and node.keyboard.rows and len(node.keyboard.rows) > 0:
            node.node_type = "message"
        else:
            node.node_type = "callback"

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

    def _find_message_dispatch(
        self, body: List[ast.stmt], filepath: Path
    ) -> Tuple[str, Optional[str], Optional[Keyboard]]:
        text_str = ""
        kb_name = None
        inline_kb: Optional[Keyboard] = None

        local_body_vars: Dict[str, Any] = {}
        local_body_nodes: Dict[str, ast.AST] = {}
        builders: Dict[str, List[Button]] = {}
        builder_types: Dict[str, str] = {}
        builder_adjust: Dict[str, int] = {}

        for stmt in body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        local_body_nodes[target.id] = stmt.value
                        val = _ast_to_value(stmt.value, local_body_vars, self.global_constants)
                        if val is not None:
                            local_body_vars[target.id] = val
                        if isinstance(stmt.value, ast.Call):
                            call_fn = getattr(stmt.value.func, "id", "") or getattr(stmt.value.func, "attr", "")
                            if "reply" in call_fn.lower():
                                builder_types[target.id] = "reply"
                            elif "inline" in call_fn.lower():
                                builder_types[target.id] = "inline"
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and isinstance(sub.func.value, ast.Name):
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

        for stmt in body:
            for subnode in ast.walk(stmt):
                if isinstance(subnode, ast.Call):
                    func_name = getattr(subnode.func, "attr", None) or getattr(subnode.func, "id", "")
                    if any(k in func_name.lower() for k in ("send_message", "edit_message", "sendphoto", "answer", "send_player_card")):
                        for arg in subnode.args:
                            val = _ast_to_value(arg, local_body_vars, self.global_constants)
                            if isinstance(val, str) and len(val) > 2 and not text_str and not val.startswith("$"):
                                text_str = val
                        for kw in subnode.keywords:
                            if kw.arg in ("text", "caption"):
                                val = _ast_to_value(kw.value, local_body_vars, self.global_constants)
                                if isinstance(val, str) and val:
                                    text_str = val
                            elif kw.arg == "reply_markup":
                                lineno = getattr(kw.value, "lineno", getattr(subnode, "lineno", 0))
                                if isinstance(kw.value, ast.Dict):
                                    inline_kb = self._parse_keyboard_expr(
                                        kw.value,
                                        f"inline_{lineno}",
                                        filepath,
                                        lineno,
                                        {k: [v] for k, v in local_body_nodes.items()},
                                    )
                                elif isinstance(kw.value, ast.Name):
                                    var_id = kw.value.id
                                    if var_id in local_body_nodes:
                                        node_val = local_body_nodes[var_id]
                                        if isinstance(node_val, ast.Call):
                                            c_func = getattr(node_val.func, "attr", None) or getattr(node_val.func, "id", "")
                                            if c_func == "as_markup":
                                                b_obj = getattr(node_val.func, "value", None)
                                                b_name = getattr(b_obj, "id", "")
                                                if b_name in builders and builders[b_name]:
                                                    btn_list = builders[b_name]
                                                    adj = builder_adjust.get(b_name, len(btn_list))
                                                    rows = [btn_list[i : i + adj] for i in range(0, len(btn_list), adj)]
                                                    if rows:
                                                        b_type = builder_types.get(b_name, "inline")
                                                        inline_kb = Keyboard(name=f"inline_{lineno}", rows=rows, keyboard_type=b_type, source_file=str(filepath), line_number=lineno)
                                            elif any(k in c_func.lower() for k in ("markup", "keyboard")):
                                                inline_kb = self._parse_keyboard_expr(
                                                    node_val,
                                                    f"{var_id}_{lineno}",
                                                    filepath,
                                                    lineno,
                                                    {k: [v] for k, v in local_body_nodes.items()},
                                                )
                                            else:
                                                kb_name = c_func
                                        else:
                                            inline_kb = self._parse_keyboard_expr(
                                                node_val,
                                                f"{var_id}_{lineno}",
                                                filepath,
                                                lineno,
                                                {k: [v] for k, v in local_body_nodes.items()},
                                            )
                                    else:
                                        kb_name = var_id
                                elif isinstance(kw.value, ast.Call):
                                    c_func = getattr(kw.value.func, "attr", None) or getattr(kw.value.func, "id", "")
                                    if c_func == "as_markup":
                                        b_obj = getattr(kw.value.func, "value", None)
                                        b_name = getattr(b_obj, "id", "")
                                        if b_name in builders and builders[b_name]:
                                            btn_list = builders[b_name]
                                            adj = builder_adjust.get(b_name, len(btn_list))
                                            rows = [btn_list[i : i + adj] for i in range(0, len(btn_list), adj)]
                                            if rows:
                                                b_type = builder_types.get(b_name, "inline")
                                                inline_kb = Keyboard(name=f"inline_{lineno}", rows=rows, keyboard_type=b_type, source_file=str(filepath), line_number=lineno)
                                    elif c_func in self.keyboards:
                                        kb_name = c_func
                                    elif any(k in c_func for k in ("InlineKeyboardMarkup", "ReplyKeyboardMarkup")):
                                        inline_kb = self._parse_keyboard_expr(
                                            kw.value,
                                            f"inline_{lineno}",
                                            filepath,
                                            lineno,
                                            {k: [v] for k, v in local_body_nodes.items()},
                                        )
                                    else:
                                        kb_name = c_func



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
                if not commands and (func_node.name.startswith("cmd_") or func_node.name.startswith("command_")):
                    commands.append(func_node.name.split("_", 1)[1])

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
                elif "start" in dec_low:
                    text_template, kb_ref, inline_kb = self._find_message_dispatch(func_node.body, filepath)
                    self._add_node(
                        node_id="cmd:/start",
                        title="/start",
                        text_template=text_template or f"Command {func_node.name}",
                        source_file=filepath,
                        lineno=func_node.lineno,
                        trigger_type="command",
                        trigger_pattern="/start",
                        kb_ref=kb_ref,
                        inline_kb=inline_kb,
                    )

