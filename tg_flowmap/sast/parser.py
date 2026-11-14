from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from tg_flowmap.core.models import Button, Keyboard, MessageNode
from tg_flowmap.sast.command_parser import CommandParserMixin
from tg_flowmap.sast.dispatch_parser import DispatchParserMixin
from tg_flowmap.sast.evaluator import extract_module_constants
from tg_flowmap.sast.keyboard_parser import KeyboardParserMixin, KeyboardStore
from tg_flowmap.sast.route_extractor import (
    RouteExtractorMixin,
    _classify_operand_source,
    _unwrap_operand,
)
from tg_flowmap.sast.screen_consolidator import ScreenConsolidatorMixin

__all__ = [
    "AstParser",
    "KeyboardStore",
    "_classify_operand_source",
    "_unwrap_operand",
]


class AstParser(
    KeyboardParserMixin,
    ScreenConsolidatorMixin,
    CommandParserMixin,
    DispatchParserMixin,
    RouteExtractorMixin,
):
    """Facade orchestrating static AST analysis across keyboards, routes, dispatches and command menus."""

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
        except (OSError, UnicodeDecodeError) as e:
            self.skipped_files.append((filepath, f"{type(e).__name__}: {e}"))
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
