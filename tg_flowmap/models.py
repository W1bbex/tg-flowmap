from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Button:
    text: str
    callback_data: Optional[str] = None
    url: Optional[str] = None
    icon_custom_emoji_id: Optional[str] = None
    style: Optional[str] = None
    line_number: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "callback_data": self.callback_data,
            "url": self.url,
            "icon_custom_emoji_id": self.icon_custom_emoji_id,
            "style": self.style,
            "line_number": self.line_number,
        }


@dataclass
class Keyboard:
    name: str
    rows: List[List[Button]] = field(default_factory=list)
    keyboard_type: str = "inline"  # "inline" or "reply"
    source_file: str = ""
    line_number: Optional[int] = None

    def all_buttons(self) -> List[Button]:
        return [btn for row in self.rows for btn in row]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "rows": [[btn.to_dict() for btn in row] for row in self.rows],
            "keyboard_type": self.keyboard_type,
            "source_file": self.source_file,
            "line_number": self.line_number,
        }



@dataclass
class MessageNode:
    id: str
    title: str
    text_template: str = ""
    keyboard: Optional[Keyboard] = None
    source_file: str = ""
    line_number: Optional[int] = None
    trigger_type: str = "callback"  # "command", "callback", "entry"
    trigger_pattern: str = ""
    aliases: List[str] = field(default_factory=list)
    node_type: str = "message"  # "command", "message", "callback", "popup"
    is_alert: bool = False
    popup_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "text_template": self.text_template,
            "keyboard": self.keyboard.to_dict() if self.keyboard else None,
            "source_file": self.source_file,
            "line_number": self.line_number,
            "trigger_type": self.trigger_type,
            "trigger_pattern": self.trigger_pattern,
            "aliases": self.aliases,
            "node_type": self.node_type,
            "is_alert": self.is_alert,
            "popup_text": self.popup_text,
        }


@dataclass
class Edge:
    from_node_id: str
    to_node_id: str
    button_text: str
    callback_data: str
    is_back: bool = False
    status: str = "ok"  # "ok", "dead_end", "dynamic", "unresolved"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "button_text": self.button_text,
            "callback_data": self.callback_data,
            "is_back": self.is_back,
            "status": self.status,
        }


@dataclass
class Issue:
    severity: str  # "error", "warning", "info"
    issue_type: str  # "dead_end", "null_emoji", "missing_back", "dangling_handler"
    message: str
    node_id: str = ""
    source_file: str = ""
    line_number: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "issue_type": self.issue_type,
            "message": self.message,
            "node_id": self.node_id,
            "source_file": self.source_file,
            "line_number": self.line_number,
        }


@dataclass
class BotMap:
    nodes: Dict[str, MessageNode] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    custom_emojis: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "issues": [i.to_dict() for i in self.issues],
            "stats": self.stats,
            "custom_emojis": self.custom_emojis,
        }
