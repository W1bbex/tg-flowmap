from __future__ import annotations


class AbortScan(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _outcome_event_type(kind: str) -> str:
    return kind if kind in ("new", "edit") else "snapshot"


def _msg_has_buttons(msg: object) -> bool:
    rm = getattr(msg, "reply_markup", None)
    rows = getattr(rm, "rows", None) or []
    return any(getattr(r, "buttons", None) for r in rows)


def mask_secret(text: str) -> str:
    """Manual answers — секреты: в публичные отчёты только факт и длина."""
    return f"[скрыто, длина {len(text or '')}]"
