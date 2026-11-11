from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from tg_flowmap.core.models import Keyboard, MessageNode
from tg_flowmap.sast.evaluator import _ast_to_value, extract_module_constants
from tg_flowmap.sast.keyboard_parser import KeyboardParserMixin, KeyboardStore
from tg_flowmap.sast.screen_consolidator import ScreenConsolidatorMixin

__all__ = [
    "AstParser",
    "KeyboardStore",
    "_classify_operand_source",
    "_unwrap_operand",
]


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


class AstParser(KeyboardParserMixin, ScreenConsolidatorMixin):
    def __init__(self):
        self.reset()

    def reset(self) -> None:
        """Resets all parsed state containers before analysis."""
        self.keyboards: Dict[str, Keyboard] = KeyboardStore(self)
        self.module_keyboards: Dict[str, Dict[str, Keyboard]] = {}
        self._keyboard_source_modules: Dict[str, Set[str]] = {}
        self.keyboard_param_defaults: Dict[str, List[Tuple[str, Optional[str]]]] = {}
        self.nodes: Dict[str, MessageNode] = {}
        self.keyboard_aliases: Dict[str, str] = {}
        self.screen_aliases: Dict[str, str] = {}
        self.hub_return_nodes: Set[str] = set()
        self.global_constants: Dict[str, Any] = {}
        self.module_constants: Dict[str, Dict[str, Any]] = {}
        self._constant_source_modules: Dict[str, Set[str]] = {}
        self._current_filepath: Optional[Path] = None
        self.custom_emoji_ids: Set[str] = set()
        self.registered_menu_commands: Set[str] = set()
        self.has_set_my_commands: bool = False
        self.skipped_files: List[Tuple[Path, str]] = []

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
                self._extract_global_constants(tree, filepath)
            except (SyntaxError, UnicodeDecodeError, ValueError, RecursionError, OSError) as e:
                self.skipped_files.append((filepath, f"{type(e).__name__}: {e}"))
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
        except (SyntaxError, UnicodeDecodeError, ValueError, RecursionError, OSError) as e:
            self.skipped_files.append((filepath, f"{type(e).__name__}: {e}"))
            return

        self._extract_global_constants(tree, filepath)
        self._extract_keyboards(tree, filepath)
        self._extract_set_my_commands(tree, filepath)
        for alias, target in self.keyboard_aliases.items():
            if target in self.keyboards and alias not in self.keyboards:
                self.keyboards[alias] = self.keyboards[target]
        self._extract_handlers(tree, filepath)
        self._consolidate_duplicate_screens()

    def _extract_global_constants(self, tree: ast.AST, filepath: Optional[Path] = None) -> None:
        """Collects top-level module constants like CANONICAL_ICONS, EMOJI_BTN_*, etc."""
        constants = extract_module_constants(tree)
        if filepath is not None:
            self._current_filepath = filepath
            stem = filepath.stem
            file_str = str(filepath)
            self.module_constants.setdefault(stem, {}).update(constants)
            self.module_constants.setdefault(file_str, {}).update(constants)
            for k in constants:
                self._constant_source_modules.setdefault(k, set()).add(stem)

        for k, v in constants.items():
            if k not in self.global_constants:
                self.global_constants[k] = v
            elif filepath is not None and len(self._constant_source_modules.get(k, set())) <= 1:
                self.global_constants[k] = v

    def _get_constants_for_file(self, filepath: Optional[Path] = None) -> Dict[str, Any]:
        """Returns constant dictionary scoped to the given file, falling back to unambiguous constants."""
        target = filepath or self._current_filepath
        res = dict(self.global_constants)
        if target is not None:
            stem = target.stem
            file_str = str(target)
            mod_consts = self.module_constants.get(file_str) or self.module_constants.get(stem)
            if mod_consts:
                res.update(mod_consts)
        return res

    def get_keyboard(self, kb_ref: str, filepath: Optional[Path] = None) -> Optional[Keyboard]:
        """Resolves a keyboard by reference name, respecting file/module scope and unambiguous fallbacks."""
        if not kb_ref:
            return None

        # 1. Qualified module lookup: e.g. "admin.menu_kb"
        if "." in kb_ref:
            mod_part, name_part = kb_ref.split(".", 1)
            mod_cand = self.module_keyboards.get(mod_part)
            if mod_cand:
                kb = (
                    mod_cand.get(name_part)
                    or mod_cand.get(name_part.split(".")[-1])
                    or mod_cand.get(name_part.lstrip("_"))
                )
                if kb:
                    return kb

        # 2. Local file/module lookup
        target = filepath or self._current_filepath
        if target is not None:
            stem = target.stem
            file_str = str(target)
            for m_dict in (self.module_keyboards.get(stem), self.module_keyboards.get(file_str)):
                if m_dict:
                    kb = (
                        m_dict.get(kb_ref)
                        or m_dict.get(self.keyboard_aliases.get(kb_ref, ""))
                        or m_dict.get(kb_ref.split(".")[-1])
                        or m_dict.get(kb_ref.lstrip("_"))
                    )
                    if kb:
                        return kb

        # 3. Direct/unambiguous fallback in dict storage
        kb = (
            dict.get(self.keyboards, kb_ref)
            or dict.get(self.keyboards, self.keyboard_aliases.get(kb_ref, ""))
            or dict.get(self.keyboards, kb_ref.split(".")[-1])
            or dict.get(self.keyboards, kb_ref.lstrip("_"))
        )
        return kb

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
            resolved_kb = self.get_keyboard(kb_ref, source_file)
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

    def _find_message_dispatch(
        self, body: List[ast.stmt], filepath: Path
    ) -> Tuple[str, Optional[str], Optional[Keyboard]]:
        self._current_filepath = filepath
        active_constants = self._get_constants_for_file(filepath)
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
                            val = _ast_to_value(sub.value, local_body_vars, active_constants)
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
                        adj_val = _ast_to_value(sub.args[0], local_body_vars, active_constants)
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
                            val = _ast_to_value(arg, local_body_vars, active_constants)
                            if isinstance(val, str) and len(val) > 2 and not val.startswith("$"):
                                if not is_toast and not text_str:
                                    text_str = val
                                elif not text_str and not fallback_toast:
                                    fallback_toast = val
                        for kw in subnode.keywords:
                            if kw.arg in ("text", "caption"):
                                val = _ast_to_value(kw.value, local_body_vars, active_constants)
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
                                                if (
                                                    self.get_keyboard(c_func, filepath) is not None
                                                    or any(k.endswith(f".{c_func}") for k in self.keyboards)
                                                    or c_func.lstrip("_") in self.keyboards
                                                ):
                                                    if not kb_name:
                                                        kb_name = self._specialize_keyboard_call(node_val, c_func, local_body_vars, filepath)
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
                                                        kb_name = self._specialize_keyboard_call(node_val, c_func, local_body_vars, filepath)
                                                elif not kb_name:
                                                    kb_name = self._specialize_keyboard_call(node_val, c_func, local_body_vars, filepath)
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
                                    if self.get_keyboard(full_name, filepath) is not None:
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
                                    elif (
                                        self.get_keyboard(c_func, filepath) is not None
                                        or c_func.lstrip("_") in self.keyboards
                                    ):
                                        if not kb_name:
                                            kb_name = self._specialize_keyboard_call(kw.value, c_func, local_body_vars, filepath)
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

    def _parse_commands_list(self, node: ast.AST, tree: Optional[ast.AST] = None, visited_names: Optional[set] = None) -> None:
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
                if visited_names is None:
                    visited_names = set()
                if node.id in visited_names:
                    return
                visited_names.add(node.id)
                for n in ast.walk(tree):
                    if isinstance(n, (ast.Assign, ast.AnnAssign)):
                        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                        for t in targets:
                            if isinstance(t, ast.Name) and t.id == node.id and n.value:
                                self._parse_commands_list(n.value, tree, visited_names=visited_names)
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
