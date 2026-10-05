from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict

from tg_flowmap.models import BotMap


class HtmlVisualizer:
    def __init__(self, bot_map: BotMap):
        self.bot_map = bot_map

    def render(self, output_path: Path) -> None:
        data_json = json.dumps(self.bot_map.to_dict(), ensure_ascii=False)

        html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>tg-flowmap — Интерактивная карта экранов Telegram-бота</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; user-select: none; }}
    
    :root {{
      --bg-canvas: #090d16;
      --grid-dot: rgba(255, 255, 255, 0.07);
      --card-bg: #17212b;
      --card-border: rgba(255, 255, 255, 0.08);
      --card-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
      --text-main: #f5f5f5;
      --text-sub: #7e8b99;
      --btn-default: #242f3d;
      --btn-default-hover: #2b394a;
      --btn-primary: #2ea6ff;
      --btn-success: #31b545;
      --btn-danger: #df3f40;
      --accent: #38bdf8;
      --danger: #ef4444;
      --warning: #f59e0b;
    }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg-canvas);
      color: var(--text-main);
      overflow: hidden;
      width: 100vw;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }}

    /* Top Navigation Toolbar */
    header {{
      height: 54px;
      background: #0f172a;
      border-bottom: 1px solid #1e293b;
      padding: 0 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      z-index: 100;
      box-shadow: 0 2px 10px rgba(0,0,0,0.3);
    }}

    .logo-area {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}

    .brand {{
      font-weight: 700;
      font-size: 17px;
      letter-spacing: -0.3px;
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .brand span {{ color: var(--accent); }}

    .stats-pills {{
      display: flex;
      gap: 8px;
      margin-left: 16px;
    }}

    .pill {{
      font-size: 12px;
      font-weight: 500;
      padding: 4px 10px;
      border-radius: 6px;
      background: #1e293b;
      color: #94a3b8;
      display: flex;
      align-items: center;
      gap: 5px;
    }}
    .pill strong {{ color: #fff; }}
    .pill.success strong {{ color: #4ade80; }}
    .pill.danger {{ background: #450a0a; color: #f87171; }}
    .pill.danger strong {{ color: #fca5a5; }}
    .pill.warning {{ background: #451a03; color: #fbbf24; }}
    .pill.warning strong {{ color: #fde68a; }}

    .toolbar-actions {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .search-box {{
      background: #090d16;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 6px 14px;
      color: #fff;
      font-size: 13px;
      width: 240px;
      outline: none;
      transition: border-color 0.2s;
    }}
    .search-box:focus {{
      border-color: var(--accent);
    }}

    .btn-tool {{
      background: #1e293b;
      border: 1px solid #334155;
      color: #cbd5e1;
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: background 0.15s, color 0.15s;
    }}
    .btn-tool:hover {{
      background: #334155;
      color: #fff;
    }}

    /* Main Viewport */
    #viewport {{
      flex: 1;
      position: relative;
      overflow: hidden;
      cursor: grab;
      background-color: var(--bg-canvas);
      background-image: radial-gradient(var(--grid-dot) 1.5px, transparent 1.5px);
      background-size: 24px 24px;
    }}
    #viewport.panning {{
      cursor: grabbing;
    }}

    #canvas-world {{
      position: absolute;
      top: 0;
      left: 0;
      transform-origin: 0 0;
      width: 10000px;
      height: 10000px;
      pointer-events: none;
    }}

    /* SVG Connector Edges Layer */
    #svg-layer {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      overflow: visible;
      z-index: 10;
    }}

    .flow-edge {{
      fill: none;
      stroke: var(--accent);
      stroke-width: 2px;
      opacity: 0.65;
      transition: stroke 0.2s, stroke-width 0.2s, opacity 0.2s;
    }}
    .flow-edge.back {{
      stroke: #64748b;
      stroke-dasharray: 5, 5;
      opacity: 0.45;
    }}
    .flow-edge.dead {{
      stroke: var(--danger);
      stroke-width: 2.5px;
      stroke-dasharray: 6, 4;
      opacity: 0.9;
    }}
    .flow-edge.highlighted {{
      stroke: #38bdf8 !important;
      stroke-width: 3.5px !important;
      opacity: 1 !important;
      filter: drop-shadow(0 0 6px rgba(56, 189, 248, 0.6));
    }}
    .flow-edge.dimmed {{
      opacity: 0.1 !important;
    }}

    /* Telegram Message Cards (HTML Nodes) */
    .nodes-container {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 20;
    }}

    .tg-card {{
      position: absolute;
      width: 340px;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      box-shadow: var(--card-shadow);
      pointer-events: auto;
      display: flex;
      flex-direction: column;
      user-select: text;
      transition: box-shadow 0.2s, border-color 0.2s;
    }}
    .tg-card:hover {{
      border-color: rgba(255, 255, 255, 0.18);
      box-shadow: 0 12px 36px rgba(0, 0, 0, 0.65);
    }}
    .tg-card.highlighted {{
      border-color: var(--accent) !important;
      box-shadow: 0 0 0 2px var(--accent), 0 14px 40px rgba(56, 189, 248, 0.3) !important;
    }}
    .tg-card.dead-end-card {{
      background: #2a1114;
      border-color: #ef4444;
      box-shadow: 0 0 20px rgba(239, 68, 68, 0.35);
    }}

    /* Card Header */
    .tg-card-header {{
      padding: 10px 14px;
      background: rgba(0, 0, 0, 0.2);
      border-top-left-radius: 14px;
      border-top-right-radius: 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: move;
      user-select: none;
    }}

    .card-title-group {{
      display: flex;
      align-items: center;
      gap: 6px;
      overflow: hidden;
    }}

    .card-type-icon {{
      font-size: 14px;
    }}

    .card-screen-title {{
      font-size: 13px;
      font-weight: 700;
      color: #e2e8f0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 180px;
    }}

    .card-meta {{
      font-size: 11px;
      color: var(--text-sub);
      font-family: monospace;
      background: rgba(255, 255, 255, 0.05);
      padding: 2px 6px;
      border-radius: 4px;
    }}

    /* Card Message Body */
    .tg-card-body {{
      padding: 14px 14px 10px 14px;
      font-size: 13px;
      line-height: 1.45;
      color: var(--text-main);
      white-space: pre-wrap;
      word-break: break-word;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
      max-height: 380px;
      overflow-y: auto;
    }}
    .tg-card-body b, .tg-card-body strong {{
      color: #fff;
      font-weight: 600;
    }}
    .tg-card-body i, .tg-card-body em {{
      color: #94a3b8;
    }}
    .tg-card-body code {{
      background: rgba(0, 0, 0, 0.3);
      padding: 2px 4px;
      border-radius: 4px;
      font-size: 12px;
      color: #38bdf8;
    }}

    /* Inline Keyboard Attached to Bubble Bottom */
    .tg-keyboard {{
      padding: 6px 8px 8px 8px;
      display: flex;
      flex-direction: column;
      gap: 5px;
      background: rgba(0, 0, 0, 0.15);
      border-bottom-left-radius: 14px;
      border-bottom-right-radius: 14px;
      user-select: none;
    }}

    .tg-row {{
      display: flex;
      gap: 5px;
      width: 100%;
    }}

    .tg-btn {{
      flex: 1;
      height: 36px;
      min-height: 36px;
      border-radius: 8px;
      background: var(--btn-default);
      color: #e4ecf2;
      border: 1px solid rgba(255, 255, 255, 0.06);
      font-size: 12.5px;
      font-weight: 600;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 0 8px;
      cursor: pointer;
      position: relative;
      transition: filter 0.15s, transform 0.1s, border-color 0.15s;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .tg-btn:hover {{
      filter: brightness(1.15);
      transform: translateY(-1px);
    }}

    /* Telegram Colored Button Themes */
    .tg-btn.style-success {{
      background: var(--btn-success) !important;
      color: #ffffff !important;
      border: none !important;
      box-shadow: 0 2px 8px rgba(49, 181, 69, 0.35);
    }}
    .tg-btn.style-primary {{
      background: var(--btn-primary) !important;
      color: #ffffff !important;
      border: none !important;
      box-shadow: 0 2px 8px rgba(46, 166, 255, 0.35);
    }}
    .tg-btn.style-danger {{
      background: var(--btn-danger) !important;
      color: #ffffff !important;
      border: none !important;
      box-shadow: 0 2px 8px rgba(223, 63, 64, 0.35);
    }}
    .tg-btn.dead-end-btn {{
      border: 2px dashed #ef4444 !important;
      background: rgba(239, 68, 68, 0.25) !important;
      color: #fca5a5 !important;
    }}

    .btn-port {{
      position: absolute;
      right: -5px;
      top: 50%;
      transform: translateY(-50%);
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--accent);
      border: 2px solid var(--card-bg);
      opacity: 0.6;
      transition: opacity 0.15s, transform 0.15s;
    }}
    .tg-btn:hover .btn-port {{
      opacity: 1;
      transform: translateY(-50%) scale(1.3);
    }}

    /* Input Port (Left side of card) */
    .card-input-port {{
      position: absolute;
      left: -6px;
      top: 24px;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #10b981;
      border: 2px solid var(--card-bg);
    }}

    /* Card Issue Badges */
    .card-issues-strip {{
      padding: 6px 12px;
      background: rgba(239, 68, 68, 0.15);
      border-top: 1px solid rgba(239, 68, 68, 0.3);
      font-size: 11px;
      color: #fca5a5;
      display: flex;
      flex-direction: column;
      gap: 3px;
    }}
    .card-warning-strip {{
      padding: 6px 12px;
      background: rgba(245, 158, 11, 0.12);
      border-top: 1px solid rgba(245, 158, 11, 0.3);
      font-size: 11px;
      color: #fde68a;
    }}

    /* Minimap & HUD Controls */
    .hud-controls {{
      position: absolute;
      bottom: 24px;
      right: 24px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      z-index: 100;
    }}
    .hud-btn {{
      width: 38px;
      height: 38px;
      border-radius: 8px;
      background: #1e293b;
      border: 1px solid #334155;
      color: #fff;
      font-size: 18px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      transition: background 0.15s, transform 0.1s;
    }}
    .hud-btn:hover {{
      background: #334155;
      transform: scale(1.05);
    }}
  </style>
</head>
<body>
  <header>
    <div class="logo-area">
      <div class="brand">🧭 tg-flowmap <span>// bot screens</span></div>
      <div class="stats-pills">
        <div class="pill">📱 Экраны: <strong id="stat-nodes">0</strong></div>
        <div class="pill">🔗 Переходы: <strong id="stat-edges">0</strong></div>
        <div class="pill danger" id="pill-dead">❌ Тупики: <strong id="stat-dead">0</strong></div>
        <div class="pill warning" id="pill-warn">⚠️ Предупреждения: <strong id="stat-warn">0</strong></div>
      </div>
    </div>
    <div class="toolbar-actions">
      <input type="text" id="search-input" class="search-box" placeholder="Поиск кнопки или экрана..." />
      <button class="btn-tool" id="btn-fit">📐 Вписать всё</button>
      <button class="btn-tool" id="btn-tidy">🪄 Выровнять</button>
      <button class="btn-tool" id="btn-toggle-lines">🔗 Скрыть линии</button>
    </div>
  </header>

  <div id="viewport">
    <div id="canvas-world">
      <svg id="svg-layer">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#38bdf8" />
          </marker>
          <marker id="arrow-back" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#64748b" />
          </marker>
          <marker id="arrow-dead" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#ef4444" />
          </marker>
        </defs>
      </svg>
      <div class="nodes-container" id="nodes-container"></div>
    </div>

    <div class="hud-controls">
      <button class="hud-btn" id="btn-zoom-in" title="Приблизить">+</button>
      <button class="hud-btn" id="btn-zoom-out" title="Отдалить">−</button>
      <button class="hud-btn" id="btn-reset" title="Сбросить масштаб">↺</button>
    </div>
  </div>

  <script>
    const rawData = {data_json};

    // Icon lookup dictionary
    const ICON_SYMBOLS = {{
      "power": "⚡", "screenshot": "📷", "sound": "🔊", "sound_mute": "🔇",
      "screen": "🖥", "apps": "🎮", "game": "🎮", "gear": "⚙️", "cpu": "🧠",
      "ram": "💾", "disk": "📁", "network": "🌐", "lock": "🔒", "light": "💡",
      "music": "🎵", "telegram": "✈️", "chrome": "🌐", "terminal": "📟",
      "pc": "💻", "user": "👤", "folder": "📁", "back": "↩", "refresh": "🔄",
      "cross": "❌", "trash": "🗑", "pencil": "✏️", "search": "🔍", "play": "▶️",
      "pause": "⏸️", "fwd10": "⏩", "back10": "⏪", "next": "⏭️", "prev": "⏮️",
      "repeat": "🔁", "heart": "❤️", "headphones": "🎧", "dot": "·", "check": "✔️",
      "clock": "🕒", "chart": "📊", "wifi": "📶", "battery": "🔋", "status_active": "🟢",
      "status_inactive": "❌", "wave": "〰️"
    }};

    document.getElementById("stat-nodes").textContent = Object.keys(rawData.nodes).length;
    document.getElementById("stat-edges").textContent = rawData.edges.length;
    document.getElementById("stat-dead").textContent = rawData.stats.dead_ends || 0;
    document.getElementById("stat-warn").textContent = (rawData.stats.missing_backs || 0) + (rawData.stats.broken_emojis || 0);

    if (!rawData.stats.dead_ends) {{
      document.getElementById("pill-dead").style.display = "none";
    }}

    // World & Canvas Pan/Zoom state
    let scale = 0.85;
    let panX = 100;
    let panY = 80;
    let isPanning = false;
    let startX = 0;
    let startY = 0;
    let showLines = true;

    const viewport = document.getElementById("viewport");
    const world = document.getElementById("canvas-world");
    const svgLayer = document.getElementById("svg-layer");
    const nodesContainer = document.getElementById("nodes-container");

    function updateTransform() {{
      world.style.transform = `translate(${{panX}}px, ${{panY}}px) scale(${{scale}})`;
    }}
    updateTransform();

    // Pan / Zoom events
    viewport.addEventListener("mousedown", (e) => {{
      if (e.target.closest(".tg-card") || e.target.closest(".hud-controls")) return;
      isPanning = true;
      startX = e.clientX - panX;
      startY = e.clientY - panY;
      viewport.classList.add("panning");
    }});

    window.addEventListener("mousemove", (e) => {{
      if (!isPanning) return;
      panX = e.clientX - startX;
      panY = e.clientY - startY;
      updateTransform();
    }});

    window.addEventListener("mouseup", () => {{
      isPanning = false;
      viewport.classList.remove("panning");
    }});

    viewport.addEventListener("wheel", (e) => {{
      e.preventDefault();
      const zoomFactor = 1.12;
      const oldScale = scale;
      if (e.deltaY < 0) {{
        scale = Math.min(2.5, scale * zoomFactor);
      }} else {{
        scale = Math.max(0.15, scale / zoomFactor);
      }}
      // Zoom centered on mouse
      const rect = viewport.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      panX = mouseX - (mouseX - panX) * (scale / oldScale);
      panY = mouseY - (mouseY - panY) * (scale / oldScale);
      updateTransform();
    }}, {{ passive: false }});

    document.getElementById("btn-zoom-in").addEventListener("click", () => {{
      scale = Math.min(2.5, scale * 1.2);
      updateTransform();
    }});
    document.getElementById("btn-zoom-out").addEventListener("click", () => {{
      scale = Math.max(0.15, scale / 1.2);
      updateTransform();
    }});
    document.getElementById("btn-reset").addEventListener("click", () => {{
      scale = 0.85; panX = 100; panY = 80;
      updateTransform();
    }});

    // Nodes Positioning & Layout
    const nodeElements = new Map();
    const nodePositions = new Map();
    const buttonPositions = new Map(); // buttonId -> {{ x, y }}

    // Categorize nodes into hierarchical layers
    const layers = [[], [], [], [], []];
    const visited = new Set();

    // Layer 0: Root nodes
    for (const [id, node] of Object.entries(rawData.nodes)) {{
      if (id === "cb:menu" || id === "cmd:/start" || id === "cb:start" || id === "cmd:/menu") {{
        layers[0].push(id);
        visited.add(id);
      }}
    }}
    if (layers[0].length === 0 && Object.keys(rawData.nodes).length) {{
      const firstId = Object.keys(rawData.nodes)[0];
      layers[0].push(firstId);
      visited.add(firstId);
    }}

    // Layer 1: Nodes called directly from Layer 0
    for (const edge of rawData.edges) {{
      if (layers[0].includes(edge.from_node_id) && !visited.has(edge.to_node_id) && !edge.is_back) {{
        layers[1].push(edge.to_node_id);
        visited.add(edge.to_node_id);
      }}
    }}

    // Layer 2: Nodes called from Layer 1
    for (const edge of rawData.edges) {{
      if (layers[1].includes(edge.from_node_id) && !visited.has(edge.to_node_id) && !edge.is_back) {{
        layers[2].push(edge.to_node_id);
        visited.add(edge.to_node_id);
      }}
    }}

    // Layer 3: Remaining normal nodes
    for (const id of Object.keys(rawData.nodes)) {{
      if (!visited.has(id)) {{
        layers[3].push(id);
        visited.add(id);
      }}
    }}

    // Layer 4: Unresolved dead-ends
    for (const edge of rawData.edges) {{
      if (edge.status === "dead_end" && !visited.has(edge.to_node_id)) {{
        layers[4].push(edge.to_node_id);
        visited.add(edge.to_node_id);
      }}
    }}

    function calculateLayout() {{
      const COL_WIDTH = 460;
      const GAP_Y = 36;
      let currentX = 60;

      layers.forEach((layerNodes, colIdx) => {{
        let currentY = 60;
        layerNodes.forEach((nodeId) => {{
          nodePositions.set(nodeId, {{ x: currentX, y: currentY }});
          currentY += 460 + GAP_Y; // estimated card height + gap
        }});
        if (layerNodes.length > 0) {{
          currentX += COL_WIDTH;
        }}
      }});
    }}
    calculateLayout();

    // Render Cards
    for (const [nodeId, node] of Object.entries(rawData.nodes)) {{
      createCard(nodeId, node);
    }}

    // Render Unresolved Dead-end cards
    const deadEndTargets = new Set(rawData.edges.filter(e => e.status === "dead_end").map(e => e.to_node_id));
    for (const deadId of deadEndTargets) {{
      if (!rawData.nodes[deadId]) {{
        createDeadEndCard(deadId);
      }}
    }}

    function createCard(nodeId, node) {{
      const pos = nodePositions.get(nodeId) || {{ x: 200, y: 200 }};
      const card = document.createElement("div");
      card.className = "tg-card";
      card.id = `card-${{nodeId}}`;
      card.style.left = `${{pos.x}}px`;
      card.style.top = `${{pos.y}}px`;

      // Input connector port
      const inputPort = document.createElement("div");
      inputPort.className = "card-input-port";
      card.appendChild(inputPort);

      // Card Header
      const header = document.createElement("div");
      header.className = "tg-card-header";
      const icon = nodeId.startsWith("cmd:") ? "⚡" : (nodeId === "cb:menu" ? "📱" : "💬");
      const srcName = node.source_file ? node.source_file.split(/[/\\\\]/).pop() : "";
      const lineStr = node.line_number ? `:${{node.line_number}}` : "";

      header.innerHTML = `
        <div class="card-title-group">
          <span class="card-type-icon">${{icon}}</span>
          <span class="card-screen-title" title="${{node.title}}">${{node.title}}</span>
        </div>
        <div class="card-meta">${{srcName}}${{lineStr}}</div>
      `;
      card.appendChild(header);

      // Card Message Body
      const body = document.createElement("div");
      body.className = "tg-card-body";
      body.innerHTML = node.text_template || "<i>(Пустой текст)</i>";
      card.appendChild(body);

      // Keyboard
      if (node.keyboard && node.keyboard.rows && node.keyboard.rows.length) {{
        const kbDiv = document.createElement("div");
        kbDiv.className = "tg-keyboard";

        node.keyboard.rows.forEach((row, rowIdx) => {{
          const rowDiv = document.createElement("div");
          rowDiv.className = "tg-row";

          row.forEach((btn, btnIdx) => {{
            const btnEl = document.createElement("div");
            btnEl.className = "tg-btn";
            const btnId = `btn-${{nodeId}}-${{rowIdx}}-${{btnIdx}}`;
            btnEl.id = btnId;

            // Apply Telegram color styles
            if (btn.style) {{
              btnEl.classList.add(`style-${{btn.style.toLowerCase()}}`);
            }} else {{
              // Heuristics for colors matching Telegram UX
              const tLow = btn.text.toLowerCase();
              if (tLow.includes("питание") || tLow.includes("включить") || tLow.includes("разблокировать")) {{
                btnEl.classList.add("style-success");
              }} else if (tLow.includes("выключить") || tLow.includes("отмена") || tLow.includes("удалить")) {{
                btnEl.classList.add("style-danger");
              }} else if (tLow.includes("скриншот") || tLow.includes("программы") || tLow.includes("звук") || tLow.includes("настройки")) {{
                btnEl.classList.add("style-primary");
              }}
            }}

            // Check if this button is a dead-end
            const isDead = rawData.edges.some(e => e.from_node_id === nodeId && e.button_text === btn.text && e.status === "dead_end");
            if (isDead) {{
              btnEl.classList.add("dead-end-btn");
              btnEl.title = `❌ ТУПИК: коллбек '${{btn.callback_data}}' не найден в коде!`;
            }}

            // Button Icon
            let iconGlyph = "";
            if (btn.icon_custom_emoji_id && ICON_SYMBOLS[btn.icon_custom_emoji_id]) {{
              iconGlyph = ICON_SYMBOLS[btn.icon_custom_emoji_id];
            }} else {{
              const tLow = btn.text.toLowerCase();
              for (const [k, sym] of Object.entries(ICON_SYMBOLS)) {{
                if (tLow.includes(k)) {{ iconGlyph = sym; break; }}
              }}
            }}

            btnEl.innerHTML = `
              <span>${{iconGlyph ? `${{iconGlyph}} ` : ""}}${{btn.text}}</span>
              <div class="btn-port"></div>
            `;

            // Hover & Click interaction
            btnEl.addEventListener("mouseenter", () => highlightEdgeFromButton(nodeId, btn.text));
            btnEl.addEventListener("mouseleave", () => resetEdgeHighlights());
            btnEl.addEventListener("click", (e) => {{
              e.stopPropagation();
              const edge = rawData.edges.find(e => e.from_node_id === nodeId && e.button_text === btn.text);
              if (edge && edge.to_node_id) {{
                focusNode(edge.to_node_id);
              }}
            }});

            rowDiv.appendChild(btnEl);
          }});

          kbDiv.appendChild(rowDiv);
        }});

        card.appendChild(kbDiv);
      }}

      // Issues strip
      const issues = rawData.issues.filter(i => i.node_id === nodeId);
      const errors = issues.filter(i => i.severity === "error");
      const warns = issues.filter(i => i.severity === "warning");

      if (errors.length) {{
        const errStrip = document.createElement("div");
        errStrip.className = "card-issues-strip";
        errStrip.innerHTML = errors.map(e => `<span>❌ ${{e.message}}</span>`).join("");
        card.appendChild(errStrip);
      }}
      if (warns.length) {{
        const warnStrip = document.createElement("div");
        warnStrip.className = "card-warning-strip";
        warnStrip.innerHTML = warns.map(w => `<span>⚠️ ${{w.message}}</span>`).join("");
        card.appendChild(warnStrip);
      }}

      // Enable card dragging
      setupCardDrag(card, header, nodeId);

      nodesContainer.appendChild(card);
      nodeElements.set(nodeId, card);
    }}

    function createDeadEndCard(deadId) {{
      const pos = nodePositions.get(deadId) || {{ x: 1800, y: 200 }};
      const card = document.createElement("div");
      card.className = "tg-card dead-end-card";
      card.id = `card-${{deadId}}`;
      card.style.left = `${{pos.x}}px`;
      card.style.top = `${{pos.y}}px`;

      card.innerHTML = `
        <div class="tg-card-header" style="background:#450a0a;">
          <div class="card-title-group">
            <span class="card-type-icon">❌</span>
            <span class="card-screen-title" style="color:#fca5a5;">ТУПИК (DEAD END)</span>
          </div>
          <div class="card-meta" style="color:#fca5a5;">${{deadId}}</div>
        </div>
        <div class="tg-card-body" style="color:#fca5a5;">
          <strong>Коллбек не найден!</strong><br><br>
          В коде бота отсутствует обработчик для переданного значения:
          <br><code>${{deadId.replace('unresolved:', '')}}</code>
        </div>
      `;

      setupCardDrag(card, card.querySelector(".tg-card-header"), deadId);
      nodesContainer.appendChild(card);
      nodeElements.set(deadId, card);
    }}

    function setupCardDrag(card, handle, nodeId) {{
      let dragStartX, dragStartY;
      let cardStartX, cardStartY;
      let isDraggingCard = false;

      handle.addEventListener("mousedown", (e) => {{
        isDraggingCard = true;
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        const pos = nodePositions.get(nodeId);
        cardStartX = pos.x;
        cardStartY = pos.y;
        e.stopPropagation();
      }});

      window.addEventListener("mousemove", (e) => {{
        if (!isDraggingCard) return;
        const dx = (e.clientX - dragStartX) / scale;
        const dy = (e.clientY - dragStartY) / scale;
        const newX = cardStartX + dx;
        const newY = cardStartY + dy;
        card.style.left = `${{newX}}px`;
        card.style.top = `${{newY}}px`;
        nodePositions.set(nodeId, {{ x: newX, y: newY }});
        renderEdges();
      }});

      window.addEventListener("mouseup", () => {{
        if (isDraggingCard) {{
          isDraggingCard = false;
        }}
      }});
    }}

    // Render Connector Lines
    const edgePaths = [];

    function renderEdges() {{
      if (!showLines) {{
        svgLayer.innerHTML = "";
        return;
      }}

      // Clear existing paths (keep defs)
      const defs = svgLayer.querySelector("defs");
      svgLayer.innerHTML = "";
      svgLayer.appendChild(defs);
      edgePaths.length = 0;

      for (const edge of rawData.edges) {{
        const fromCard = nodeElements.get(edge.from_node_id);
        const toCard = nodeElements.get(edge.to_node_id);
        if (!fromCard || !toCard) continue;

        // Find button element
        let fromX, fromY;
        const btnEl = Array.from(fromCard.querySelectorAll(".tg-btn")).find(b => b.textContent.includes(edge.button_text));

        const fromPos = nodePositions.get(edge.from_node_id);
        const toPos = nodePositions.get(edge.to_node_id);

        if (btnEl) {{
          fromX = fromPos.x + btnEl.offsetLeft + btnEl.offsetWidth;
          fromY = fromPos.y + btnEl.offsetTop + btnEl.offsetHeight / 2;
        }} else {{
          fromX = fromPos.x + 340;
          fromY = fromPos.y + 40;
        }}

        const toX = toPos.x;
        const toY = toPos.y + 28;

        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        const dx = Math.max(60, Math.abs(toX - fromX) * 0.45);

        // Smooth cubic bezier
        let d;
        if (edge.is_back || toX < fromX) {{
          // Backwards loop
          const loopOffset = 90;
          d = `M ${{fromX}} ${{fromY}} C ${{fromX + loopOffset}} ${{fromY}}, ${{toX - loopOffset}} ${{toY}}, ${{toX}} ${{toY}}`;
        }} else {{
          d = `M ${{fromX}} ${{fromY}} C ${{fromX + dx}} ${{fromY}}, ${{toX - dx}} ${{toY}}, ${{toX}} ${{toY}}`;
        }}

        path.setAttribute("d", d);
        let cls = "flow-edge";
        let marker = "url(#arrow)";

        if (edge.status === "dead_end") {{
          cls += " dead";
          marker = "url(#arrow-dead)";
        }} else if (edge.is_back) {{
          cls += " back";
          marker = "url(#arrow-back)";
        }}

        path.setAttribute("class", cls);
        path.setAttribute("marker-end", marker);
        path.dataset.from = edge.from_node_id;
        path.dataset.to = edge.to_node_id;
        path.dataset.btn = edge.button_text;

        svgLayer.appendChild(path);
        edgePaths.push(path);
      }}
    }}

    setTimeout(renderEdges, 50);

    function highlightEdgeFromButton(fromNodeId, btnText) {{
      for (const p of edgePaths) {{
        if (p.dataset.from === fromNodeId && p.dataset.btn === btnText) {{
          p.classList.add("highlighted");
          const targetCard = nodeElements.get(p.dataset.to);
          if (targetCard) targetCard.classList.add("highlighted");
        }} else {{
          p.classList.add("dimmed");
        }}
      }}
    }}

    function resetEdgeHighlights() {{
      for (const p of edgePaths) {{
        p.classList.remove("highlighted", "dimmed");
      }}
      document.querySelectorAll(".tg-card.highlighted").forEach(c => c.classList.remove("highlighted"));
    }}

    function focusNode(nodeId) {{
      const pos = nodePositions.get(nodeId);
      if (!pos) return;
      const targetCard = nodeElements.get(nodeId);
      if (targetCard) {{
        document.querySelectorAll(".tg-card.highlighted").forEach(c => c.classList.remove("highlighted"));
        targetCard.classList.add("highlighted");
      }}
      const vRect = viewport.getBoundingClientRect();
      panX = vRect.width / 2 - (pos.x + 170) * scale;
      panY = vRect.height / 2 - (pos.y + 120) * scale;
      updateTransform();
    }}

    // Search Box
    document.getElementById("search-input").addEventListener("input", (e) => {{
      const q = e.target.value.toLowerCase().trim();
      if (!q) return;

      for (const [id, node] of Object.entries(rawData.nodes)) {{
        const titleMatch = node.title.toLowerCase().includes(q) || id.toLowerCase().includes(q);
        const btnMatch = node.keyboard && node.keyboard.rows.some(r => r.some(b => b.text.toLowerCase().includes(q) || (b.callback_data && b.callback_data.toLowerCase().includes(q))));
        if (titleMatch || btnMatch) {{
          focusNode(id);
          break;
        }}
      }}
    }});

    // Tidy Layout button
    document.getElementById("btn-tidy").addEventListener("click", () => {{
      calculateLayout();
      for (const [id, pos] of nodePositions.entries()) {{
        const el = nodeElements.get(id);
        if (el) {{
          el.style.left = `${{pos.x}}px`;
          el.style.top = `${{pos.y}}px`;
        }}
      }}
      renderEdges();
    }});

    // Fit View
    document.getElementById("btn-fit").addEventListener("click", () => {{
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const pos of nodePositions.values()) {{
        minX = Math.min(minX, pos.x);
        minY = Math.min(minY, pos.y);
        maxX = Math.max(maxX, pos.x + 360);
        maxY = Math.max(maxY, pos.y + 400);
      }}
      const vRect = viewport.getBoundingClientRect();
      const worldW = maxX - minX + 160;
      const worldH = maxY - minY + 160;
      scale = Math.min(1.2, Math.max(0.18, Math.min(vRect.width / worldW, vRect.height / worldH)));
      panX = (vRect.width - (maxX + minX) * scale) / 2;
      panY = (vRect.height - (maxY + minY) * scale) / 2;
      updateTransform();
    }});

    // Toggle lines
    document.getElementById("btn-toggle-lines").addEventListener("click", () => {{
      showLines = !showLines;
      document.getElementById("btn-toggle-lines").textContent = showLines ? "🔗 Скрыть линии" : "🔗 Показать линии";
      renderEdges();
    }});
  </script>
</body>
</html>
"""
        output_path.write_text(html_content, encoding="utf-8")
