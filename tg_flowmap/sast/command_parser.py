from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from tg_flowmap.sast.evaluator import _ast_to_value


class CommandParserMixin:
    """Mixin extracting bot command menus registered in set_my_commands / setMyCommands."""

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

    def _parse_commands_list(
        self, node: ast.AST, tree: Optional[ast.AST] = None, visited_names: Optional[set] = None
    ) -> None:
        """Parses a list/tuple of BotCommand objects or variable reference."""
        if isinstance(node, (ast.List, ast.Tuple)):
            for elt in node.elts:
                cmd_name = self._extract_single_bot_command(elt)
                if cmd_name:
                    self.registered_menu_commands.add(str(cmd_name).strip().lstrip("/"))
        elif isinstance(node, ast.Name):
            var_val = self.global_constants.get(node.id)
            found_any = False
            if isinstance(var_val, list):
                for item in var_val:
                    if isinstance(item, str):
                        self.registered_menu_commands.add(item.strip().lstrip("/"))
                        found_any = True
                    elif isinstance(item, dict) and "command" in item:
                        self.registered_menu_commands.add(str(item["command"]).strip().lstrip("/"))
                        found_any = True
            if not found_any and tree is not None:
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
