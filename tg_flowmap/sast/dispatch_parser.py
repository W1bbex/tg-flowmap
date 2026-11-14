from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tg_flowmap.core.models import Button, Keyboard
from tg_flowmap.sast.evaluator import _ast_to_value
from tg_flowmap.sast.keyboard_parser import _unwind_call_chain


class DispatchParserMixin:
    """Mixin extracting response text, toasts, alerts, and keyboards dispatched from handlers."""

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
                elif isinstance(sub, ast.Expr) and isinstance(sub.value, ast.Call):
                    var_name, chain = _unwind_call_chain(sub.value)
                    if var_name:
                        for method, call in chain:
                            if method in ("add", "button", "row"):
                                builders.setdefault(var_name, [])
                                if method == "button":
                                    btn = self._parse_button_element(call, local_body_vars)
                                    if btn:
                                        builders[var_name].append(btn)
                                else:
                                    for arg in call.args:
                                        btn = self._parse_button_element(arg, local_body_vars)
                                        if btn:
                                            builders[var_name].append(btn)
                            elif method == "adjust" and call.args:
                                adj_val = _ast_to_value(call.args[0], local_body_vars, active_constants)
                                if isinstance(adj_val, int) and adj_val > 0:
                                    builder_adjust[var_name] = adj_val

        fallback_toast: Optional[str] = None
        for stmt in body:
            for subnode in ast.walk(stmt):
                if isinstance(subnode, ast.Call):
                    func_name = getattr(subnode.func, "attr", None) or getattr(subnode.func, "id", "")
                    func_low = func_name.lower()
                    if any(
                        k in func_low
                        for k in (
                            "send_message",
                            "edit_message",
                            "edit_text",
                            "edit_caption",
                            "send_photo",
                            "sendphoto",
                            "answer",
                            "send_player_card",
                        )
                    ):
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
                                                    if not b_name and isinstance(b_obj, ast.Call):
                                                        root_id, chain = _unwind_call_chain(b_obj)
                                                        if root_id:
                                                            b_name = root_id
                                                            for method, call in chain:
                                                                if method in ("add", "button", "row"):
                                                                    builders.setdefault(b_name, [])
                                                                    if method == "button":
                                                                        btn = self._parse_button_element(call, local_body_vars)
                                                                        if btn:
                                                                            builders[b_name].append(btn)
                                                                    else:
                                                                        for arg in call.args:
                                                                            btn = self._parse_button_element(arg, local_body_vars)
                                                                            if btn:
                                                                                builders[b_name].append(btn)
                                                                elif method == "adjust" and call.args:
                                                                    adj_val = _ast_to_value(call.args[0], local_body_vars, active_constants)
                                                                    if isinstance(adj_val, int) and adj_val > 0:
                                                                        builder_adjust[b_name] = adj_val
                                                    if b_name in builders and builders[b_name]:
                                                        btn_list = builders[b_name]
                                                        adj = builder_adjust.get(b_name, len(btn_list))
                                                        rows = [btn_list[i : i + adj] for i in range(0, len(btn_list), adj)]
                                                        if rows and not inline_kb:
                                                            b_type = builder_types.get(b_name, "inline")
                                                            inline_kb = Keyboard(
                                                                name=f"inline_{lineno}",
                                                                rows=rows,
                                                                keyboard_type=b_type,
                                                                source_file=str(filepath),
                                                                line_number=lineno,
                                                            )
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
                                                inline_kb = Keyboard(
                                                    name=f"inline_{lineno}",
                                                    rows=rows,
                                                    keyboard_type=b_type,
                                                    source_file=str(filepath),
                                                    line_number=lineno,
                                                )
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
