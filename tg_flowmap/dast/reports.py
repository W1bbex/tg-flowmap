"""Отчёты по боту: graph.json (+routes), report.md, messages.json,
callbacks.json, premium_emojis.json, timeline.json (экспорт), errors.log,
HTML-превью экранов.

Безопасность вывода: весь пользовательский контент (тексты, метки кнопок,
имена) экранируется; manual answers показываются только маской
(см. crawler.mask_secret) — секреты не публикуются.
"""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from pathlib import Path

from .config import Config
from .map_render import generate_maps
from .state import State

PRICE_WORDS_HINT = ("товар", "аккаунт", "карта", "gift", "account", "card", "ключ", "key")


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _latest_message_for_screen(state: State, bot: str, screen_id: str) -> dict | None:
    rows = state._query(
        "SELECT * FROM messages WHERE bot=? AND screen_id=? ORDER BY id DESC LIMIT 1",
        (bot, screen_id))
    if not rows:
        return None
    r = dict(rows[0])
    r["entities"] = [dict(e) for e in state._query(
        "SELECT * FROM entities WHERE message_rowid=?", (r["id"],))]
    r["media"] = [dict(m) for m in state._query(
        "SELECT * FROM media WHERE message_rowid=?", (r["id"],))]
    return r


def _screen_texts(state: State, bot: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in state._query(
            "SELECT screen_id, raw_text FROM messages WHERE bot=? "
            "ORDER BY id", (bot,)):
        out[row["screen_id"]] = row["raw_text"] or ""
    return out


def _find_prices(text: str, price_re) -> list[str]:
    return [m.group(0) for m in price_re.finditer(text or "")]


def _style_str(b: dict) -> str:
    """Человекочитаемый стиль кнопки (Telethon 1.44 KeyboardButtonStyle)."""
    parts = []
    if b.get("style_bg_success"):
        parts.append("bg:success")
    if b.get("style_bg_danger"):
        parts.append("bg:danger")
    if b.get("style_bg_primary"):
        parts.append("bg:primary")
    if b.get("style_icon_id"):
        parts.append(f"icon:{b['style_icon_id']}")
    if b.get("style_requires_password"):
        parts.append("requires_password")
    return ",".join(parts)


def render_tree(screens: list[dict], transitions: list[dict], routes: list[dict] | None = None) -> str:
    """Дерево разделов вида Main menu ├── Catalog │ ├── Xbox…
    Показываются ВСЕ корневые экраны (по root routes с parent_route=None или depth 0)
    и несвязанные/вспомогательные экраны. Циклы помечаются «(повтор)» и не раскрываются."""
    if not screens:
        return "(экранов нет)"
    children: dict[str, list[dict]] = defaultdict(list)
    for t in transitions:
        if t["from_screen"] and t["to_screen"]:
            children[t["from_screen"]].append(t)

    root_sids = []
    if routes is not None:
        root_sids = [r["screen_id"] for r in routes if r.get("parent_route") is None]
    if root_sids:
        seen_sids = set()
        roots = []
        for sid in root_sids:
            if sid not in seen_sids:
                seen_sids.add(sid)
                matching = [s for s in screens if s["screen_id"] == sid]
                if matching:
                    roots.append(matching[0])
    else:
        roots = [s for s in screens if s["depth_min"] == 0]
    if not roots and screens:
        roots = [screens[0]]

    reachable: set[str] = set()
    stack = [s["screen_id"] for s in roots]
    while stack:
        sid = stack.pop()
        if sid in reachable:
            continue
        reachable.add(sid)
        stack.extend(t["to_screen"] for t in children.get(sid, []))

    lines: list[str] = []

    def walk(screen_id: str, prefix: str, seen: set) -> None:
        kids = children.get(screen_id, [])
        for i, t in enumerate(kids):
            last = i == len(kids) - 1
            connector = "└── " if last else "├── "
            to = t["to_screen"]
            repeat = " (повтор)" if to in seen else ""
            res = t["result_type"] or ""
            lines.append(f"{prefix}{connector}{t['action']}{repeat}  [{res}]")
            if to not in seen:
                walk(to, prefix + ("    " if last else "│   "), seen | {to})

    for r_i, root in enumerate(roots):
        if r_i > 0:
            lines.append("")
        lines.append(f"Root {r_i + 1}: {root['screen_id']} (/start)")
        walk(root["screen_id"], "", {root["screen_id"]})

    isolated = [s for s in screens if s["screen_id"] not in reachable]
    if isolated:
        lines.append("")
        lines.append("Несвязанные экраны (не достигнуты от корней):")
        for s in isolated:
            lines.append(f"  - {s['screen_id']} (depth {s['depth_min']})")
    return "\n".join(lines)


def _routes_export(state: State, bot: str) -> list[dict]:
    """Маршруты для graph.json — отдельно от transition-edges.
    Текстовые ответы маскируются (секреты не публикуются)."""
    out = []
    for r in state.routes_all(bot):
        path = []
        for step in r["path"]:
            s = dict(step)
            if s.get("step_type") == "text":
                s["text"] = "[hidden]"  # manual answer — секрет
            path.append(s)
        out.append({
            "route_id": r["route_id"], "screen_id": r["screen_id"],
            "parent_route": r["parent_route"], "depth": r["depth"],
            "status": r["status"], "path": path,
        })
    return out


def build_graph(state: State, bot: str) -> dict:
    screens = state.screens_all(bot)
    texts = _screen_texts(state, bot)
    buttons = state.buttons_all(bot)
    by_screen: dict[str, list[dict]] = defaultdict(list)
    for b in buttons:
        by_screen[b["screen_id"]].append(b)
    nodes = []
    for s in screens:
        sid = s["screen_id"]
        msg = _latest_message_for_screen(state, bot, sid)
        nodes.append({
            "id": sid,
            "bot": bot,
            "text": (texts.get(sid) or "")[:2000],
            "entities": (msg or {}).get("entities", []),
            "buttons": [
                {
                    "row": b["row"], "col": b["col"], "label": b["label"],
                    "button_type": b["button_type"],
                    "callback_data": b["callback_b64"], "callback_hex": b["callback_hex"],
                    "url": b["url"], "blocked_reason": b["blocked_reason"],
                    "style": {
                        "bg_primary": bool(b.get("style_bg_primary")),
                        "bg_success": bool(b.get("style_bg_success")),
                        "bg_danger": bool(b.get("style_bg_danger")),
                        "icon_document_id": b.get("style_icon_id"),
                        "requires_password": bool(b.get("style_requires_password")),
                    },
                }
                for b in by_screen.get(sid, [])
            ],
            "media": (msg or {}).get("media", []),
            "requires_input": bool(s["requires_input"]),
            "depth": s["depth_min"],
        })
    edges = [
        {
            "from": t["from_screen"], "to": t["to_screen"], "action": t["action"],
            "action_type": t["action_type"], "result_type": t["result_type"],
        }
        for t in state.transitions_all(bot) if t["from_screen"]
    ]
    return {"nodes": nodes, "edges": edges, "routes": _routes_export(state, bot)}


def build_callbacks_json(state: State, bot: str) -> list[dict]:
    out = []
    for c in state.callbacks_all(bot):
        row = {
            "bot": bot,
            "from_screen": c.get("from_screen_id"),
            "button": c.get("label"),
            "callback_data_b64": c.get("callback_b64"),
            "callback_data_hex": c.get("callback_hex"),
            "action_id": c["action_id"],
            "answer": c["answer_message"],
            "alert": bool(c["is_alert"]),
            "url": c["url"],
            "cache_time": c["cache_time"],
            "duration_ms": c["duration_ms"],
            "exception": c["exception"],
        }
        if c["raw_json"]:
            try:
                row["raw"] = json.loads(c["raw_json"])
            except json.JSONDecodeError:
                row["raw"] = None
        t = state._query_one(
            "SELECT to_screen, result_type FROM transitions WHERE bot=? AND button_rowid=?",
            (bot, c["button_rowid"]))
        if t:
            row["next_screen"] = t["to_screen"]
            row["result"] = t["result_type"]
        out.append(row)
    return out


def build_report_md(cfg: Config, state: State, bot: str) -> str:
    screens = state.screens_all(bot)
    transitions = state.transitions_all(bot)
    routes = state.routes_all(bot)
    buttons = state.buttons_all(bot)
    texts = _screen_texts(state, bot)
    price_re = cfg.compiled_price()
    by_screen: dict[str, list[dict]] = defaultdict(list)
    for b in buttons:
        by_screen[b["screen_id"]].append(b)
    route_of: dict[str, dict] = {}
    for r in routes:
        route_of.setdefault(r["screen_id"], r)

    result_counts = defaultdict(int)
    for t in transitions:
        result_counts[t["result_type"] or "?"] += 1
    blocked_counts = defaultdict(int)
    for b in buttons:
        if b["blocked_reason"]:
            blocked_counts[b["blocked_reason"].split(":")[0]] += 1

    metrics = state.metrics_all(bot)
    actions_total = int(state.progress_get(bot, "actions", str(metrics.get("telegram_actions", 0))))
    starts_total = metrics.get("start_count", int(state.progress_get(bot, "start_count", "0")))
    rec_starts = metrics.get("recovery_start_count", 0)
    local_returns = metrics.get("successful_local_returns", 0)
    avoided = metrics.get("avoided_replays", 0)
    saved_actions = metrics.get("estimated_actions_saved", 0)
    replans = metrics.get("replans", 0)
    unstable_e = metrics.get("unstable_edges", 0)

    lines: list[str] = []
    lines.append(f"# Отчёт обхода: {bot}")
    lines.append("")
    lines.append("## Общая статистика")
    lines.append(f"- **Экранов (Canonical):** {len(screens)}")
    lines.append(f"- **Переходов:** {len(transitions)} (edit: {result_counts.get('edit', 0)}, new: {result_counts.get('new', 0)}, answer_only: {result_counts.get('answer_only', 0)}, timeout: {result_counts.get('timeout', 0)}, error: {result_counts.get('error', 0)})")
    lines.append(f"- **Кнопок:** {len(buttons)} (заблокировано по безопасности: {sum(1 for b in buttons if b['blocked_reason'])})")
    if blocked_counts:
        lines.append(f"- **Причины блокировки:** " + ", ".join(f"{k}={v}" for k, v in sorted(blocked_counts.items())))
    lines.append("")
    lines.append("## Эффективность Graph-First планировщика")
    lines.append(f"- **Всего Telegram-действий:** {actions_total}")
    lines.append(f"- **Первоначальных /start:** {starts_total - rec_starts if starts_total >= rec_starts else starts_total}")
    lines.append(f"- **Восстановительных /start (Recovery):** {rec_starts}")
    lines.append(f"- **Локальных возвратов по графу:** {local_returns}")
    lines.append(f"- **Предотвращено повторных /start с корня:** {avoided}")
    lines.append(f"- **Сэкономлено действий навигации:** ~{saved_actions}")
    lines.append(f"- **Нестабильных рёбер / перепланирований:** {unstable_e} / {replans}")
    lines.append("")
    lines.append("## Интерактивные схемы")
    lines.append("- [Интерактивная офлайн-карта интерфейса (map.html)](map.html)")
    lines.append("- [Векторная диаграмма переходов (map.svg)](map.svg)")
    lines.append("- [Исходная схема Mermaid (map.mmd)](map.mmd)")
    lines.append("")
    lines.append("## Карта экранов")
    lines.append("")
    lines.append("```")
    lines.append(render_tree(screens, transitions, routes))
    lines.append("```")
    lines.append("")

    premium_by_screen: dict[str, set[str]] = defaultdict(set)
    for occ in state.emoji_occurrences_all(bot):
        row = state._query_one(
            "SELECT screen_id FROM messages WHERE id=?", (occ["message_rowid"],))
        if row and row["screen_id"]:
            premium_by_screen[row["screen_id"]].add(occ["document_id"])

    for s in sorted(screens, key=lambda x: (x["depth_min"], x["id"])):
        sid = s["screen_id"]
        text = texts.get(sid) or ""
        r = route_of.get(sid)
        path_str = " → ".join(
            ["/start"] + [step["action"] for step in (r["path"] if r else [])]) or "/start"
        lines.append(f"## Экран `{sid}` (depth {s['depth_min']})")
        lines.append("")
        lines.append(f"**Полный путь:** {path_str}")
        prices = _find_prices(text, price_re)
        is_product = bool(prices) and any(w in text.lower() for w in PRICE_WORDS_HINT)
        if prices:
            lines.append(f"**Цена:** {', '.join(prices[:10])}"
                         + ("  _(похоже на карточку товара)_" if is_product else ""))
        if s["requires_input"]:
            lines.append("**requires_input:** бот запросил ввод текста")
        if premium_by_screen.get(sid):
            lines.append(f"**Premium emoji:** {', '.join(sorted(premium_by_screen[sid]))}")
        lines.append("")
        lines.append("**Текст сообщения (последняя версия, без изменений):**")
        lines.append("")
        lines.append("```")
        lines.append(text[:4000] if text else "(пусто)")
        lines.append("```")
        sbtns = by_screen.get(sid, [])
        if sbtns:
            lines.append("")
            lines.append("**Кнопки:**")
            lines.append("")
            lines.append("| ряд | поз | метка | тип | callback (hex) | стиль | статус |")
            lines.append("|---|---|---|---|---|---|---|")
            for b in sorted(sbtns, key=lambda x: (x["row"], x["col"])):
                status = "OK" if not b["blocked_reason"] else \
                    f"BLOCKED: {b['blocked_reason']}"
                hexv = (b["callback_hex"] or "")[:24]
                safe_label = str(b["label"] or "").replace("|", "\\|").replace("\n", " ")
                lines.append(
                    f"| {b['row']} | {b['col']} | {safe_label} | {b['button_type']} "
                    f"| `{hexv}` | {_style_str(b) or '—'} | {status} |")
        outs = [t for t in transitions if t["from_screen"] == sid]
        if outs:
            lines.append("")
            lines.append("**Переходы:** " + "; ".join(
                f"`{t['action']}` → {t['to_screen'] or '(без экрана)'} "
                f"({t['action_type']}/{t['result_type']})" for t in outs))
        msg_rows = state._query(
            "SELECT version, event_type, captured_at, raw_text FROM messages "
            "WHERE bot=? AND screen_id=? ORDER BY id", (bot, sid))
        if len(msg_rows) > 1:
            lines.append("")
            lines.append(f"**Версии сообщения** ({len(msg_rows)}): " + ", ".join(
                f"v{r['version']} ({r['event_type']})" for r in msg_rows))
            if len(msg_rows) >= 2:
                lines.append("")
                lines.append("До/после последнего изменения:")
                lines.append("")
                lines.append("```diff")
                lines.append("- " + (msg_rows[-2]["raw_text"] or "").replace("\n", "\n- "))
                lines.append("+ " + (msg_rows[-1]["raw_text"] or "").replace("\n", "\n+ "))
                lines.append("```")
        medias = state._query(
            "SELECT m.* FROM media m JOIN messages msg ON msg.id=m.message_rowid "
            "WHERE msg.bot=? AND msg.screen_id=?", (bot, sid))
        if medias:
            lines.append("")
            media_items = []
            for m in medias:
                if m["file_path"]:
                    rel_p = f"media/{Path(m['file_path']).name}"
                    media_items.append(f"[{m['kind']}]({rel_p})")
                else:
                    media_items.append(f"[{m['kind']}](не скачано)")
            lines.append("**Медиа:** " + "; ".join(media_items))
        lines.append("")
    return "\n".join(lines)


_PREVIEW_TMPL = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{screen_id}</title>
<style>
body{{font-family:-apple-system,Segoe UI,sans-serif;background:#0f0f0f;display:flex;justify-content:center;padding:24px}}
.phone{{width:380px;background:#17212b;border-radius:16px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.5)}}
.hdr{{padding:10px 14px;color:#fff;background:#231f34;font-weight:600}}
.msg{{padding:14px;color:#fff;background:#2b5278;margin:10px;border-radius:12px;white-space:pre-wrap;font-size:14px}}
.btns{{padding:6px}}
.btnrow{{display:flex;gap:6px;margin:4px 6px}}
.btn{{flex:1;background:#231f34;color:#8ed7ff;padding:10px;border-radius:8px;text-align:center;font-size:14px}}
.btn.blocked{{color:#ff8a8a;background:#3a1f24}}
.meta{{color:#7f91a4;font-size:11px;padding:8px 14px}}
</style></head><body>
<div class="phone">
  <div class="hdr">{bot}</div>
  <div class="msg">{text}</div>
  <div class="btns">{buttons}</div>
  <div class="meta">{screen_id} · depth {depth}</div>
</div></body></html>
"""


def write_previews(cfg: Config, state: State, bot: str, bot_dir: Path) -> None:
    preview_dir = bot_dir / "screenshots_or_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    texts = _screen_texts(state, bot)
    for s in state.screens_all(bot):
        sid = s["screen_id"]
        rows: dict[int, list] = {}
        for b in state.buttons_for_screen(bot, sid):
            rows.setdefault(b.row, []).append(b)
        btn_html = []
        for r in sorted(rows):
            cells = "".join(
                f'<div class="btn{" blocked" if b.blocked_reason else ""}">'
                f"{_esc(b.label)}{' 🔒' if b.blocked_reason else ''}</div>"
                for b in sorted(rows[r], key=lambda x: x.col))
            btn_html.append(f'<div class="btnrow">{cells}</div>')
        text = _esc((texts.get(sid) or "(пусто)")[:3000])
        html_doc = _PREVIEW_TMPL.format(
            screen_id=_esc(sid), bot=_esc(bot), text=text,
            buttons="".join(btn_html), depth=_esc(s["depth_min"]))
        (preview_dir / f"{sid}.html").write_text(html_doc, encoding="utf-8")


def generate_reports(cfg: Config, state: State, bot: str) -> dict[str, Path]:
    safe_bot = re.sub(r"[^a-zA-Z0-9_-]", "_", bot.lstrip("@")) or "bot"
    bot_dir = cfg.output_dir / safe_bot
    bot_dir.mkdir(parents=True, exist_ok=True)

    graph = build_graph(state, bot)
    _write_json(bot_dir / "graph.json", graph)
    _write_json(bot_dir / "messages.json", state.messages_all(bot))
    _write_json(bot_dir / "callbacks.json", build_callbacks_json(state, bot))
    _write_json(bot_dir / "premium_emojis.json", {
        "documents": state.emoji_documents_all(),
        "occurrences": state.emoji_occurrences_all(bot),
    })
    if cfg.export_timeline_json:
        timeline = state.timeline_all(bot)
        for row in timeline:
            raw_payload = row.pop("payload_json", None)
            try:
                row["payload"] = json.loads(raw_payload or "null")
            except (json.JSONDecodeError, TypeError):
                row["payload"] = raw_payload
        _write_json(bot_dir / "timeline.json", timeline)
    (bot_dir / "report.md").write_text(
        build_report_md(cfg, state, bot), encoding="utf-8")

    errs = state.errors_list(bot, limit=10000)
    err_lines = [
        f"{e['ts']}\t{e['kind']}\t{e['message']}\t{e['context'] or ''}" for e in reversed(errs)]
    (bot_dir / "errors.log").write_text("\n".join(err_lines), encoding="utf-8")

    write_previews(cfg, state, bot, bot_dir)
    maps = generate_maps(state, bot, bot_dir)

    return {
        "graph": bot_dir / "graph.json",
        "report": bot_dir / "report.md",
        "messages": bot_dir / "messages.json",
        "callbacks": bot_dir / "callbacks.json",
        "premium_emojis": bot_dir / "premium_emojis.json",
        "errors": bot_dir / "errors.log",
        "map_html": maps["html"],
        "map_svg": maps["svg"],
        "map_mmd": maps["mmd"],
    }
