from __future__ import annotations

from typing import Set


class ScreenConsolidatorMixin:
    """Mixin consolidating duplicate screen representations and hub return handlers."""

    def _consolidate_duplicate_screens(self) -> None:
        """Merges duplicate screens (e.g. /led command with led_menu callback)
        and converts pseudo-screens that just return to hub (like console_close)
        into actions transitioning to the hub.
        """
        to_remove: Set[str] = set()

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
