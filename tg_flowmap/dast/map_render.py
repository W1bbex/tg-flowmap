"""Генерация визуальных карт интерфейса бота:
- map.html: интерактивная офлайн-карта (zoom, pan, клик по узлам и рёбрам, детальный инспектор);
- map.svg: векторная схема графа переходов;
- map.mmd: исходный граф в формате Mermaid.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .state import State


def _escape_js_json(data: Any) -> str:
    """Безопасная сериализация JSON для встраивания в HTML."""
    dumped = json.dumps(data, ensure_ascii=False)
    return dumped.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def generate_maps(state: State, bot: str, output_dir: Path) -> dict[str, Path]:
    """Генерирует map.html, map.svg и map.mmd для указанного бота."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    screens = state.screens_all(bot)
    messages = state.messages_all(bot)
    buttons = state.buttons_all(bot)
    transitions = state.transitions_all(bot)
    edges = state.graph_edges_all(bot)
    actions = {a["action_id"]: a for s in screens for a in state.actions_for_screen(bot, s["screen_id"])}

    # Подготовка узлов
    nodes = []
    for s in screens:
        sid = s["screen_id"]
        # Собираем сообщения и кнопки для инспектора
        s_msgs = [m for m in messages if m.get("screen_id") == sid]
        s_btns = [b for b in buttons if b.get("screen_id") == sid]
        
        # Определяем тип узла
        is_checkout = any(b.get("blocked_reason") for b in s_btns)
        is_input = bool(s.get("requires_input"))
        
        node_type = "normal"
        if is_input:
            node_type = "input"
        if is_checkout:
            node_type = "blocked"

        preview_text = (s.get("text_norm") or "")[:40]
        if len(s.get("text_norm") or "") > 40:
            preview_text += "…"

        nodes.append({
            "id": sid,
            "label": f"{sid}\n{preview_text}",
            "text_norm": s.get("text_norm", ""),
            "fingerprint": s.get("fingerprint", ""),
            "depth_min": s.get("depth_min", 0),
            "requires_input": is_input,
            "type": node_type,
            "messages_count": len(s_msgs),
            "messages": [
                {
                    "message_id": m.get("message_id"),
                    "version": m.get("version"),
                    "event_type": m.get("event_type"),
                    "raw_text": m.get("raw_text", ""),
                    "captured_at": m.get("captured_at", ""),
                    "entities": m.get("entities", []),
                    "media": m.get("media", []),
                }
                for m in s_msgs
            ],
            "buttons": [
                {
                    "row": b.get("row"),
                    "col": b.get("col"),
                    "label": b.get("label", ""),
                    "button_type": b.get("button_type", ""),
                    "callback_hex": b.get("callback_hex"),
                    "callback_b64": b.get("callback_b64"),
                    "url": b.get("url"),
                    "blocked_reason": b.get("blocked_reason"),
                    "style_icon_id": b.get("style_icon_id"),
                }
                for b in s_btns
            ],
        })

    # Подготовка рёбер
    graph_edges = []
    # 1. Из graph_edges (новая модель)
    for e in edges:
        act = actions.get(e["action_id"], {})
        graph_edges.append({
            "source": e["source_screen_id"],
            "target": e["destination_screen_id"],
            "action_id": e["action_id"],
            "label": act.get("label", e["action_id"]),
            "result_type": e.get("result_type", "edit"),
            "confidence": float(e.get("confidence", 1.0)),
            "is_stable": bool(e.get("is_stable", 1)),
            "observations_count": int(e.get("observations_count", 1)),
        })

    # 2. Если graph_edges пуст — строим из transitions (обратная совместимость)
    if not graph_edges:
        for t in transitions:
            if t.get("from_screen") and t.get("to_screen"):
                graph_edges.append({
                    "source": t["from_screen"],
                    "target": t["to_screen"],
                    "action_id": str(t.get("button_rowid") or "nav"),
                    "label": t.get("action", "transition"),
                    "result_type": t.get("result_type", "edit"),
                    "confidence": 1.0,
                    "is_stable": True,
                    "observations_count": 1,
                })

    html_path = output_dir / "map.html"
    svg_path = output_dir / "map.svg"
    mmd_path = output_dir / "map.mmd"

    html_path.write_text(_render_map_html(bot, nodes, graph_edges), encoding="utf-8")
    svg_path.write_text(_render_map_svg(bot, nodes, graph_edges), encoding="utf-8")
    mmd_path.write_text(_render_map_mmd(bot, nodes, graph_edges), encoding="utf-8")

    return {
        "html": html_path,
        "svg": svg_path,
        "mmd": mmd_path,
    }


def _render_map_html(bot: str, nodes: list[dict], edges: list[dict]) -> str:
    escaped_data = _escape_js_json({"nodes": nodes, "edges": edges, "bot": bot})
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Карта экранов бота {html.escape(bot)}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; display: flex; height: 100vh; overflow: hidden; background: #1e1e24; color: #e0e0e0; }}
#sidebar {{ width: 380px; background: #25252d; border-right: 1px solid #33333d; display: flex; flex-direction: column; overflow-y: auto; padding: 20px; box-shadow: 2px 0 10px rgba(0,0,0,0.3); }}
#canvas-container {{ flex: 1; position: relative; overflow: hidden; background: radial-gradient(circle, #2a2a35 10%, #1e1e24 90%); cursor: grab; }}
#canvas-container:active {{ cursor: grabbing; }}
h1 {{ font-size: 1.2rem; margin-bottom: 15px; color: #fff; display: flex; align-items: center; justify-content: space-between; }}
.badge {{ font-size: 0.75rem; background: #3d3d4d; padding: 4px 8px; border-radius: 12px; color: #aaa; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; font-size: 0.8rem; }}
.legend-item {{ display: flex; align-items: center; gap: 6px; }}
.dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
.dot-normal {{ background: #4CAF50; }}
.dot-input {{ background: #FFC107; }}
.dot-blocked {{ background: #FF9800; }}
.dot-unstable {{ background: #9C27B0; }}
.panel-section {{ margin-top: 15px; border-top: 1px solid #33333d; padding-top: 15px; }}
.panel-section h3 {{ font-size: 0.9rem; text-transform: uppercase; color: #888; margin-bottom: 8px; }}
.detail-box {{ background: #1a1a20; padding: 12px; border-radius: 6px; font-size: 0.85rem; line-height: 1.4; word-break: break-word; }}
.btn-badge {{ display: inline-block; background: #2c2c38; border: 1px solid #444455; padding: 4px 8px; border-radius: 4px; margin: 3px; font-size: 0.75rem; }}
.controls {{ position: absolute; bottom: 20px; right: 20px; display: flex; gap: 10px; z-index: 10; }}
.control-btn {{ background: #2e2e3a; border: 1px solid #444455; color: #fff; padding: 8px 14px; border-radius: 6px; cursor: pointer; font-size: 0.9rem; }}
.control-btn:hover {{ background: #3d3d4d; }}
svg {{ width: 100%; height: 100%; }}
.node-circle {{ stroke-width: 2px; cursor: pointer; transition: r 0.2s; }}
.node-circle:hover {{ filter: drop-shadow(0 0 6px rgba(255,255,255,0.5)); }}
.node-label {{ fill: #e0e0e0; font-size: 11px; text-anchor: middle; pointer-events: none; user-select: none; }}
.edge-line {{ stroke: #555566; stroke-width: 1.5px; fill: none; }}
.edge-line.unstable {{ stroke: #9C27B0; stroke-dasharray: 4; }}
.edge-label {{ fill: #888899; font-size: 9px; text-anchor: middle; }}
</style>
</head>
<body>

<div id="sidebar">
  <h1><span>{html.escape(bot)}</span> <span class="badge">Интерактивная карта</span></h1>
  <div class="legend">
    <div class="legend-item"><span class="dot dot-normal"></span> Обычный</div>
    <div class="legend-item"><span class="dot dot-input"></span> Ввод текста</div>
    <div class="legend-item"><span class="dot dot-blocked"></span> Заблокировано</div>
    <div class="legend-item"><span class="dot dot-unstable"></span> Нестабильный</div>
  </div>
  
  <div id="inspector">
    <div class="detail-box">Нажмите на любой экран или стрелку перехода на схеме для детального анализа.</div>
  </div>
</div>

<div id="canvas-container">
  <svg id="svg-canvas">
    <defs>
      <marker id="arrow" viewBox="0 0 10 10" refX="22" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#777788"/>
      </marker>
      <marker id="arrow-unstable" viewBox="0 0 10 10" refX="22" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#9C27B0"/>
      </marker>
    </defs>
    <g id="transform-group">
      <g id="edges-group"></g>
      <g id="nodes-group"></g>
    </g>
  </svg>
  <div class="controls">
    <button class="control-btn" onclick="zoomIn()">+</button>
    <button class="control-btn" onclick="zoomOut()">−</button>
    <button class="control-btn" onclick="resetZoom()">Сброс</button>
  </div>
</div>

<script id="graph-data" type="application/json">
{escaped_data}
</script>

<script>
const data = JSON.parse(document.getElementById('graph-data').textContent);
const nodes = data.nodes;
const edges = data.edges;

const nodeMap = new Map();
nodes.forEach((n, i) => {{
  const cols = Math.ceil(Math.sqrt(nodes.length));
  const row = Math.floor(i / cols);
  const col = i % cols;
  n.x = 200 + col * 220 + (Math.random() * 40 - 20);
  n.y = 150 + row * 180 + (Math.random() * 40 - 20);
  nodeMap.set(n.id, n);
}});

const transformGroup = document.getElementById('transform-group');
const edgesGroup = document.getElementById('edges-group');
const nodesGroup = document.getElementById('nodes-group');
const inspector = document.getElementById('inspector');

let scale = 1;
let panX = 0;
let panY = 0;
let isPanning = false;
let startX = 0;
let startY = 0;

function updateTransform() {{
  transformGroup.setAttribute('transform', `translate(${{panX}}, ${{panY}}) scale(${{scale}})`);
}}

function zoomIn() {{ scale = Math.min(scale * 1.2, 4); updateTransform(); }}
function zoomOut() {{ scale = Math.max(scale / 1.2, 0.2); updateTransform(); }}
function resetZoom() {{ scale = 1; panX = 50; panY = 50; updateTransform(); }}

const container = document.getElementById('canvas-container');
container.addEventListener('mousedown', (e) => {{
  if (e.target.tagName === 'svg' || e.target.id === 'canvas-container') {{
    isPanning = true;
    startX = e.clientX - panX;
    startY = e.clientY - panY;
  }}
}});

window.addEventListener('mousemove', (e) => {{
  if (isPanning) {{
    panX = e.clientX - startX;
    panY = e.clientY - startY;
    updateTransform();
  }}
}});

window.addEventListener('mouseup', () => {{ isPanning = false; }});
container.addEventListener('wheel', (e) => {{
  e.preventDefault();
  const delta = e.deltaY > 0 ? 0.9 : 1.1;
  scale = Math.max(0.2, Math.min(4, scale * delta));
  updateTransform();
}});

function getColor(type) {{
  if (type === 'input') return '#FFC107';
  if (type === 'blocked') return '#FF9800';
  return '#4CAF50';
}}

// Отрисовка рёбер
edges.forEach(e => {{
  const src = nodeMap.get(e.source);
  const dst = nodeMap.get(e.target);
  if (!src || !dst) return;

  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  const dx = dst.x - src.x;
  const dy = dst.y - src.y;
  const cx = (src.x + dst.x) / 2 - dy * 0.1;
  const cy = (src.y + dst.y) / 2 + dx * 0.1;

  path.setAttribute('d', `M ${{src.x}} ${{src.y}} Q ${{cx}} ${{cy}} ${{dst.x}} ${{dst.y}}`);
  path.setAttribute('class', e.is_stable ? 'edge-line' : 'edge-line unstable');
  path.setAttribute('marker-end', e.is_stable ? 'url(#arrow)' : 'url(#arrow-unstable)');
  path.style.cursor = 'pointer';

  path.addEventListener('click', () => {{
    showEdgeDetails(e);
  }});

  edgesGroup.appendChild(path);
}});

// Отрисовка узлов
nodes.forEach(n => {{
  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  g.setAttribute('transform', `translate(${{n.x}}, ${{n.y}})`);
  g.style.cursor = 'pointer';

  const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  circle.setAttribute('r', '16');
  circle.setAttribute('fill', getColor(n.type));
  circle.setAttribute('stroke', '#ffffff');
  circle.setAttribute('class', 'node-circle');

  const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  text.setAttribute('y', '28');
  text.setAttribute('class', 'node-label');
  text.textContent = n.id;

  g.appendChild(circle);
  g.appendChild(text);

  g.addEventListener('click', () => {{
    showNodeDetails(n);
  }});

  nodesGroup.appendChild(g);
}});

function escapeHtml(str) {{
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}}

function showNodeDetails(n) {{
  const safeId = escapeHtml(n.id);
  const safeText = n.text_norm ? escapeHtml(n.text_norm) : '<i>[пустой текст]</i>';
  const safeFp = escapeHtml((n.fingerprint || '').substring(0, 16));
  const safeDepth = escapeHtml(n.depth_min);
  const safeReqInput = n.requires_input ? 'Да' : 'Нет';
  const safeMsgCount = escapeHtml(n.messages_count);

  let htmlContent = `
    <h2>${{safeId}}</h2>
    <div class="panel-section">
      <h3>Текст экрана</h3>
      <div class="detail-box">${{safeText}}</div>
    </div>
    <div class="panel-section">
      <h3>Параметры</h3>
      <div class="detail-box">
        <div><strong>Fingerprint:</strong> <code>${{safeFp}}...</code></div>
        <div><strong>Глубина:</strong> ${{safeDepth}}</div>
        <div><strong>Требует ввода:</strong> ${{safeReqInput}}</div>
        <div><strong>Версий сообщения:</strong> ${{safeMsgCount}}</div>
      </div>
    </div>
  `;

  if (n.buttons && n.buttons.length > 0) {{
    htmlContent += `
      <div class="panel-section">
        <h3>Кнопки (${{n.buttons.length}})</h3>
        <div class="detail-box">
    `;
    n.buttons.forEach(b => {{
      const bColor = b.blocked_reason ? '#e53935' : '#43a047';
      const safeLabel = escapeHtml(b.label || '[Без подписи]');
      const safeType = escapeHtml(b.button_type);
      const safeHex = escapeHtml(b.callback_hex);
      const safeBlock = escapeHtml(b.blocked_reason);

      htmlContent += `<div class="btn-badge" style="border-left: 3px solid ${{bColor}}">
        <strong>${{safeLabel}}</strong> (${{safeType}})
        ${{b.callback_hex ? `<div><small>hex: ${{safeHex}}</small></div>` : ''}}
        ${{b.blocked_reason ? `<div><small style="color:#ff8a80">Блок: ${{safeBlock}}</small></div>` : ''}}
      </div>`;
    }});
    htmlContent += `</div></div>`;
  }}

  inspector.innerHTML = htmlContent;
}}

function showEdgeDetails(e) {{
  const safeLabel = escapeHtml(e.label);
  const safeSrc = escapeHtml(e.source);
  const safeDst = escapeHtml(e.target);
  const safeRes = escapeHtml(e.result_type);
  const safeConf = (((e.confidence ?? 1.0)) * 100).toFixed(0);
  const safeStable = e.is_stable ? 'Стабильное' : 'Нестабильное';
  const safeObs = escapeHtml(e.observations_count);

  inspector.innerHTML = `
    <h2>Переход</h2>
    <div class="panel-section">
      <h3>Детали действия</h3>
      <div class="detail-box">
        <div><strong>Действие:</strong> ${{safeLabel}}</div>
        <div><strong>Откуда:</strong> ${{safeSrc}}</div>
        <div><strong>Куда:</strong> ${{safeDst}}</div>
        <div><strong>Результат:</strong> ${{safeRes}}</div>
        <div><strong>Confidence:</strong> ${{safeConf}}%</div>
        <div><strong>Стабильность:</strong> ${{safeStable}}</div>
        <div><strong>Наблюдений:</strong> ${{safeObs}}</div>
      </div>
    </div>
  `;
}}

if (nodes.length > 0) {{
  showNodeDetails(nodes[0]);
}}
resetZoom();
</script>
</body>
</html>
"""


def _render_map_svg(bot: str, nodes: list[dict], edges: list[dict]) -> str:
    """Генерирует статичный SVG файл схемы экранов."""
    node_map = {}
    cols = max(1, int(len(nodes) ** 0.5))
    width = max(800, cols * 240 + 200)
    rows = max(1, (len(nodes) + cols - 1) // cols)
    height = max(600, rows * 200 + 200)

    for i, n in enumerate(nodes):
        r = i // cols
        c = i % cols
        x = 120 + c * 240
        y = 100 + r * 200
        node_map[n["id"]] = (x, y, n)

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" style="background:#1e1e24;font-family:sans-serif;">',
        '<defs>',
        '  <marker id="arrow" viewBox="0 0 10 10" refX="22" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '    <path d="M 0 0 L 10 5 L 0 10 z" fill="#888899"/>',
        '  </marker>',
        '</defs>',
        f'<text x="20" y="35" fill="#ffffff" font-size="18" font-weight="bold">Карта интерфейса: {html.escape(bot)}</text>',
        '<g id="edges">',
    ]

    for e in edges:
        src = node_map.get(e["source"])
        dst = node_map.get(e["target"])
        if not src or not dst:
            continue
        x1, y1, _ = src
        x2, y2, _ = dst
        color = "#9C27B0" if not e.get("is_stable", True) else "#666677"
        dash = ' stroke-dasharray="4"' if not e.get("is_stable", True) else ""
        svg_lines.append(
            f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1.5"{dash} marker-end="url(#arrow)"/>'
        )

    svg_lines.append('</g>\n<g id="nodes">')
    for x, y, n in node_map.values():
        fill = "#FFC107" if n.get("requires_input") else ("#FF9800" if n.get("type") == "blocked" else "#4CAF50")
        label = html.escape(n["id"])
        text_preview = html.escape((n.get("text_norm") or "")[:20])
        svg_lines.append(f'  <g transform="translate({x},{y})">')
        svg_lines.append(f'    <circle r="16" fill="{fill}" stroke="#ffffff" stroke-width="2"/>')
        svg_lines.append(f'    <text y="28" fill="#e0e0e0" font-size="10" text-anchor="middle">{label}</text>')
        svg_lines.append(f'    <text y="40" fill="#888888" font-size="8" text-anchor="middle">{text_preview}</text>')
        svg_lines.append('  </g>')

    svg_lines.append('</g>\n</svg>')
    return "\n".join(svg_lines)


def _render_map_mmd(bot: str, nodes: list[dict], edges: list[dict]) -> str:
    """Генерирует Mermaid-граф переходов."""
    lines = ["graph TD", f"  %% Bot interface map: {bot}"]
    for n in nodes:
        sid = n["id"]
        text_preview = (n.get("text_norm") or "")[:25].replace('"', "'")
        lines.append(f'  {sid}["{sid}<br/>{text_preview}"]')

    for e in edges:
        src = e["source"]
        dst = e["target"]
        label = (e.get("label") or "go").replace('"', "'")
        if e.get("result_type") == "recovery":
            arrow = f'-.->|"recovery: {label}"|'
        else:
            arrow = f'-->|"{label}"|'
        lines.append(f'  {src} {arrow} {dst}')

    return "\n".join(lines)
