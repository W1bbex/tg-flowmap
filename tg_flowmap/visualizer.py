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
      --bg-canvas: #0b0f19;
      --grid-dot: rgba(255, 255, 255, 0.06);
      --card-bg: #17212b;
      --card-border: rgba(255, 255, 255, 0.09);
      --card-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
      --text-main: #f5f5f5;
      --text-sub: #7e8b99;
      --btn-default: #242f3d;
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
      height: 52px;
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
      font-size: 16px;
      letter-spacing: -0.3px;
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .brand span {{ color: var(--accent); }}

    .cluster-legend {{
      display: flex;
      gap: 10px;
      margin-left: 20px;
    }}
    .legend-tag {{
      font-size: 11px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 4px;
      background: #1e293b;
      color: #94a3b8;
      display: flex;
      align-items: center;
      gap: 4px;
    }}
    .legend-tag.center {{ border-left: 3px solid #10b981; color: #6ee7b7; }}
    .legend-tag.settings {{ border-left: 3px solid #38bdf8; color: #7dd3fc; }}
    .legend-tag.power {{ border-left: 3px solid #f87171; color: #fca5a5; }}
    .legend-tag.sound {{ border-left: 3px solid #c084fc; color: #e9d5ff; }}
    .legend-tag.apps {{ border-left: 3px solid #fbbf24; color: #fde68a; }}

    .toolbar-actions {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .search-box {{
      background: #090d16;
      border: 1px solid #334155;
      border-radius: 6px;
      padding: 6px 12px;
      color: #fff;
      font-size: 13px;
      width: 220px;
      outline: none;
    }}
    .search-box:focus {{ border-color: var(--accent); }}

    .btn-tool {{
      background: #1e293b;
      border: 1px solid #334155;
      color: #cbd5e1;
      padding: 5px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 5px;
      transition: background 0.15s, color 0.15s;
    }}
    .btn-tool:hover {{ background: #334155; color: #fff; }}
    .btn-tool.active {{ background: #0369a1; border-color: #38bdf8; color: #fff; }}

    /* Main Viewport */
    #viewport {{
      flex: 1;
      position: relative;
      overflow: hidden;
      cursor: grab;
      background-color: var(--bg-canvas);
      background-image: radial-gradient(var(--grid-dot) 1.5px, transparent 1.5px);
      background-size: 24px 24px;
      will-change: transform;
    }}
    #viewport.panning {{ cursor: grabbing; }}

    #canvas-world {{
      position: absolute;
      top: 0;
      left: 0;
      transform-origin: 0 0;
      pointer-events: none;
      will-change: transform;
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
      opacity: 0.55;
      pointer-events: stroke;
      cursor: pointer;
    }}
    .flow-edge.back {{
      stroke: #64748b;
      stroke-dasharray: 5, 5;
      opacity: 0.35;
    }}
    .flow-edge.dead {{
      stroke: var(--danger);
      stroke-width: 2.5px;
      stroke-dasharray: 6, 4;
      opacity: 0.85;
    }}
    .flow-edge.highlighted {{
      stroke: #38bdf8 !important;
      stroke-width: 3.5px !important;
      opacity: 1 !important;
      filter: drop-shadow(0 0 6px rgba(56, 189, 248, 0.7));
    }}
    .flow-edge.dimmed {{
      opacity: 0.05 !important;
    }}

    /* Cluster Background Areas */
    .cluster-zone {{
      position: absolute;
      border-radius: 20px;
      border: 1px dashed rgba(255, 255, 255, 0.07);
      background: rgba(255, 255, 255, 0.015);
      pointer-events: none;
      z-index: 5;
    }}
    .cluster-label {{
      position: absolute;
      top: -24px;
      left: 16px;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: #64748b;
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
      width: 330px;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      box-shadow: var(--card-shadow);
      pointer-events: auto;
      display: flex;
      flex-direction: column;
      user-select: text;
      contain: layout style paint;
      transition: border-color 0.15s, box-shadow 0.15s, opacity 0.15s;
    }}
    .tg-card.is-center-menu {{
      border: 2px solid #10b981;
      box-shadow: 0 0 25px rgba(16, 185, 129, 0.25), var(--card-shadow);
    }}
    .tg-card.highlighted {{
      border-color: var(--accent) !important;
      box-shadow: 0 0 0 2px var(--accent), 0 10px 30px rgba(56, 189, 248, 0.35) !important;
      z-index: 50;
    }}
    .tg-card.dimmed {{
      opacity: 0.25;
    }}
    .tg-card.dead-end-card {{
      background: #250d0f;
      border-color: #ef4444;
      box-shadow: 0 0 20px rgba(239, 68, 68, 0.35);
    }}

    /* Card Header */
    .tg-card-header {{
      padding: 9px 12px;
      background: rgba(0, 0, 0, 0.25);
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

    .card-screen-title {{
      font-size: 13px;
      font-weight: 700;
      color: #e2e8f0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 190px;
    }}

    .card-meta {{
      font-size: 10.5px;
      color: var(--text-sub);
      font-family: monospace;
      background: rgba(255, 255, 255, 0.05);
      padding: 2px 5px;
      border-radius: 4px;
    }}

    /* Card Message Body */
    .tg-card-body {{
      padding: 12px 14px 10px 14px;
      font-size: 12.5px;
      line-height: 1.45;
      color: var(--text-main);
      white-space: pre-wrap;
      word-break: break-word;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
      max-height: 280px;
      overflow-y: hidden;
    }}
    .tg-card-body b, .tg-card-body strong {{
      color: #fff;
      font-weight: 600;
    }}
    .tg-card-body code {{
      background: rgba(0, 0, 0, 0.3);
      padding: 1px 4px;
      border-radius: 4px;
      font-size: 11.5px;
      color: #38bdf8;
    }}

    /* Inline Keyboard */
    .tg-keyboard {{
      padding: 5px 8px 8px 8px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      background: rgba(0, 0, 0, 0.15);
      border-bottom-left-radius: 14px;
      border-bottom-right-radius: 14px;
      user-select: none;
    }}

    .tg-row {{
      display: flex;
      gap: 4px;
      width: 100%;
    }}

    .tg-btn {{
      flex: 1;
      height: 35px;
      border-radius: 7px;
      background: var(--btn-default);
      color: #e4ecf2;
      border: 1px solid rgba(255, 255, 255, 0.05);
      font-size: 12px;
      font-weight: 600;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 5px;
      padding: 0 6px;
      cursor: pointer;
      position: relative;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      transition: filter 0.1s, transform 0.1s;
    }}
    .tg-btn:hover {{
      filter: brightness(1.2);
      transform: translateY(-1px);
    }}

    /* Telegram Colored Buttons */
    .tg-btn.style-success {{
      background: var(--btn-success) !important;
      color: #ffffff !important;
      border: none !important;
    }}
    .tg-btn.style-primary {{
      background: var(--btn-primary) !important;
      color: #ffffff !important;
      border: none !important;
    }}
    .tg-btn.style-danger {{
      background: var(--btn-danger) !important;
      color: #ffffff !important;
      border: none !important;
    }}
    .tg-btn.dead-end-btn {{
      border: 2px dashed #ef4444 !important;
      background: rgba(239, 68, 68, 0.2) !important;
      color: #fca5a5 !important;
    }}

    .btn-port {{
      position: absolute;
      right: -4px;
      top: 50%;
      transform: translateY(-50%);
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--accent);
      border: 2px solid var(--card-bg);
      opacity: 0.6;
    }}
    .tg-btn:hover .btn-port {{
      opacity: 1;
      transform: translateY(-50%) scale(1.3);
    }}

    /* HUD Controls */
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
      width: 36px;
      height: 36px;
      border-radius: 8px;
      background: #1e293b;
      border: 1px solid #334155;
      color: #fff;
      font-size: 16px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      transition: background 0.15s;
    }}
    .hud-btn:hover {{ background: #334155; }}
  </style>
</head>
<body>
  <header>
    <div class="logo-area">
      <div class="brand">🧭 tg-flowmap <span>// hub canvas</span></div>
      <div class="cluster-legend">
        <div class="legend-tag center">🟢 Меню (Центр)</div>
        <div class="legend-tag settings">⚙️ Настройки (Справа)</div>
        <div class="legend-tag power">⚡ Питание (Слева)</div>
        <div class="legend-tag sound">🔊 Звук (Сверху)</div>
        <div class="legend-tag apps">🎮 Программы (Снизу)</div>
      </div>
    </div>
    <div class="toolbar-actions">
      <input type="text" id="search-input" class="search-box" placeholder="Поиск кнопки или экрана..." />
      <button class="btn-tool active" id="btn-focus-mode" title="Показывать связи только для активного экрана для устранения каши">🎯 Фокус-режим</button>
      <button class="btn-tool" id="btn-center-menu">📍 К Главному меню</button>
      <button class="btn-tool" id="btn-fit">📐 Вписать всё</button>
    </div>
  </header>

  <div id="viewport">
    <div id="canvas-world">
      <div id="clusters-layer"></div>
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
      <button class="hud-btn" id="btn-reset" title="К центру">⌂</button>
    </div>
  </div>

  <script>
    const rawData = {data_json};

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

    let scale = 0.85;
    let panX = window.innerWidth / 2 - 165;
    let panY = window.innerHeight / 2 - 180;
    let isPanning = false;
    let startX = 0;
    let startY = 0;
    let focusOnlyMode = true; // By default: focus mode to eliminate clutter and lag!
    let activeFocusedNode = "cb:menu";

    const viewport = document.getElementById("viewport");
    const world = document.getElementById("canvas-world");
    const svgLayer = document.getElementById("svg-layer");
    const nodesContainer = document.getElementById("nodes-container");
    const clustersLayer = document.getElementById("clusters-layer");

    function updateTransform() {{
      world.style.transform = `translate3d(${{panX}}px, ${{panY}}px, 0) scale(${{scale}})`;
    }}
    updateTransform();

    // Viewport Panning
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

    // Smooth Zooming
    viewport.addEventListener("wheel", (e) => {{
      e.preventDefault();
      const zoomFactor = 1.1;
      const oldScale = scale;
      if (e.deltaY < 0) {{
        scale = Math.min(2.0, scale * zoomFactor);
      }} else {{
        scale = Math.max(0.2, scale / zoomFactor);
      }}
      const rect = viewport.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      panX = mouseX - (mouseX - panX) * (scale / oldScale);
      panY = mouseY - (mouseY - panY) * (scale / oldScale);
      updateTransform();
    }}, {{ passive: false }});

    document.getElementById("btn-zoom-in").addEventListener("click", () => {{
      scale = Math.min(2.0, scale * 1.2);
      updateTransform();
    }});
    document.getElementById("btn-zoom-out").addEventListener("click", () => {{
      scale = Math.max(0.2, scale / 1.2);
      updateTransform();
    }});
    document.getElementById("btn-reset").addEventListener("click", centerOnMainMenu);
    document.getElementById("btn-center-menu").addEventListener("click", centerOnMainMenu);

    function centerOnMainMenu() {{
      scale = 0.85;
      panX = window.innerWidth / 2 - 165 * scale;
      panY = window.innerHeight / 2 - 180 * scale;
      updateTransform();
      setFocusedCard("cb:menu");
    }}

    // ==========================================
    // CLUSTERED / HUB-AND-SPOKE AUTO-LAYOUT
    // ==========================================
    const nodeElements = new Map();
    const nodePositions = new Map();

    function computeHubLayout() {{
      nodePositions.clear();

      // 1. Center Hub: Main Menu (0, 0)
      const centerNodeId = rawData.nodes["cb:menu"] ? "cb:menu" : (rawData.nodes["cmd:/start"] ? "cmd:/start" : Object.keys(rawData.nodes)[0]);
      nodePositions.set(centerNodeId, {{ x: 0, y: 0 }});

      if (rawData.nodes["cmd:/start"] && centerNodeId !== "cmd:/start") {{
        nodePositions.set("cmd:/start", {{ x: -40, y: -380 }});
      }}

      // Clusters configuration
      // Right wing: Settings and Services
      const settingsNodes = [];
      // Left wing: Power and System State
      const powerNodes = [];
      // Top wing: Sound and Media
      const soundNodes = [];
      // Bottom wing: Apps, Shortcuts and Workspaces
      const appsNodes = [];
      // Others / Service handlers
      const miscNodes = [];

      for (const [id, node] of Object.entries(rawData.nodes)) {{
        if (id === centerNodeId || id === "cmd:/start") continue;

        const idLow = id.toLowerCase();
        if (idLow.includes("settings") || idLow.includes("monitoring") || idLow.includes("history") || idLow.includes("led") || idLow.includes("console") || idLow.includes("physical") || idLow.includes("activity")) {{
          settingsNodes.push(id);
        }} else if (idLow.includes("power") || idLow.includes("shutdown") || idLow.includes("reboot") || idLow.includes("sleep") || idLow.includes("hibernate") || idLow.includes("lock") || idLow.includes("unlock")) {{
          powerNodes.push(id);
        }} else if (idLow.includes("sound") || idLow.includes("volume") || idLow.includes("player")) {{
          soundNodes.push(id);
        }} else if (idLow.includes("apps") || idLow.includes("workspace") || idLow.includes("screenshot") || idLow.includes("flow_")) {{
          appsNodes.push(id);
        }} else {{
          miscNodes.push(id);
        }}
      }}

      // Place Settings Cluster (Right: X from +460 to +1400)
      let curY = -280;
      settingsNodes.forEach((id, idx) => {{
        const col = (idx % 2 === 0) ? 500 : 920;
        const rowY = curY;
        if (idx % 2 === 1) curY += 380;
        nodePositions.set(id, {{ x: col, y: rowY }});
      }});

      // Place Power Cluster (Left: X from -500 to -1400)
      curY = -280;
      powerNodes.forEach((id, idx) => {{
        const col = (idx % 2 === 0) ? -500 : -920;
        const rowY = curY;
        if (idx % 2 === 1) curY += 380;
        nodePositions.set(id, {{ x: col, y: rowY }});
      }});

      // Place Sound Cluster (Top: Y from -480 to -900)
      let curX = -180;
      soundNodes.forEach((id) => {{
        nodePositions.set(id, {{ x: curX, y: -480 }});
        curX += 380;
      }});

      // Place Apps Cluster (Bottom: Y from +480 to +900)
      curX = -360;
      appsNodes.forEach((id, idx) => {{
        nodePositions.set(id, {{ x: curX, y: 520 }});
        curX += 380;
      }});

      // Place Misc / Service nodes neatly in an outer bottom area
      let miscX = -600;
      let miscY = 1000;
      miscNodes.forEach((id, idx) => {{
        nodePositions.set(id, {{ x: miscX, y: miscY }});
        miscX += 380;
        if (miscX > 1000) {{
          miscX = -600;
          miscY += 380;
        }}
      }});
    }}
    computeHubLayout();

    // Render Cards
    for (const [nodeId, node] of Object.entries(rawData.nodes)) {{
      createCard(nodeId, node);
    }}

    function createCard(nodeId, node) {{
      const pos = nodePositions.get(nodeId) || {{ x: 0, y: 0 }};
      const card = document.createElement("div");
      card.className = "tg-card";
      if (nodeId === "cb:menu" || nodeId === "cmd:/start") {{
        card.classList.add("is-center-menu");
      }}
      card.id = `card-${{nodeId}}`;
      card.style.left = `${{pos.x}}px`;
      card.style.top = `${{pos.y}}px`;

      // Header
      const header = document.createElement("div");
      header.className = "tg-card-header";
      const icon = nodeId.startsWith("cmd:") ? "⚡" : (nodeId === "cb:menu" ? "📱" : "💬");
      const srcName = node.source_file ? node.source_file.split(/[/\\\\]/).pop() : "";
      const lineStr = node.line_number ? `:${{node.line_number}}` : "";

      header.innerHTML = `
        <div class="card-title-group">
          <span style="font-size:13px;">${{icon}}</span>
          <span class="card-screen-title" title="${{node.title}}">${{node.title}}</span>
        </div>
        <div class="card-meta">${{srcName}}${{lineStr}}</div>
      `;
      card.appendChild(header);

      // Body (Message text)
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
            btnEl.id = `btn-${{nodeId}}-${{rowIdx}}-${{btnIdx}}`;

            // Telegram color styles
            if (btn.style) {{
              btnEl.classList.add(`style-${{btn.style.toLowerCase()}}`);
            }} else {{
              const tLow = btn.text.toLowerCase();
              if (tLow.includes("питание") || tLow.includes("включить") || tLow.includes("разблокировать")) {{
                btnEl.classList.add("style-success");
              }} else if (tLow.includes("выключить") || tLow.includes("отмена") || tLow.includes("удалить")) {{
                btnEl.classList.add("style-danger");
              }} else if (tLow.includes("скриншот") || tLow.includes("программы") || tLow.includes("звук") || tLow.includes("настройки")) {{
                btnEl.classList.add("style-primary");
              }}
            }}

            const isDead = rawData.edges.some(e => e.from_node_id === nodeId && e.button_text === btn.text && e.status === "dead_end");
            if (isDead) {{
              btnEl.classList.add("dead-end-btn");
              btnEl.title = `❌ ТУПИК: коллбек '${{btn.callback_data}}' не найден!`;
            }}

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

            btnEl.addEventListener("mouseenter", () => highlightBranch(nodeId, btn.text));
            btnEl.addEventListener("mouseleave", () => resetBranchHighlight());
            btnEl.addEventListener("click", (e) => {{
              e.stopPropagation();
              const edge = rawData.edges.find(e => e.from_node_id === nodeId && e.button_text === btn.text);
              if (edge && edge.to_node_id) {{
                focusCard(edge.to_node_id);
              }}
            }});

            rowDiv.appendChild(btnEl);
          }});

          kbDiv.appendChild(rowDiv);
        }});

        card.appendChild(kbDiv);
      }}

      // Card click -> set focus
      card.addEventListener("click", (e) => {{
        if (e.target.closest(".tg-btn")) return;
        setFocusedCard(nodeId);
      }});

      setupCardDrag(card, header, nodeId);
      nodesContainer.appendChild(card);
      nodeElements.set(nodeId, card);
    }}

    function setupCardDrag(card, handle, nodeId) {{
      let dragStartX, dragStartY;
      let cardStartX, cardStartY;
      let isDragging = false;

      handle.addEventListener("mousedown", (e) => {{
        isDragging = true;
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        const pos = nodePositions.get(nodeId);
        cardStartX = pos.x;
        cardStartY = pos.y;
        e.stopPropagation();
      }});

      window.addEventListener("mousemove", (e) => {{
        if (!isDragging) return;
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
        if (isDragging) isDragging = false;
      }});
    }}

    // ==========================================
    // OPTIMIZED FAST SVG CONNECTORS
    // ==========================================
    const edgePaths = [];

    function renderEdges() {{
      const defs = svgLayer.querySelector("defs");
      svgLayer.innerHTML = "";
      svgLayer.appendChild(defs);
      edgePaths.length = 0;

      // Filter edges based on focusOnlyMode to prevent clutter & lag!
      const edgesToRender = focusOnlyMode
        ? rawData.edges.filter(e => e.from_node_id === activeFocusedNode || e.to_node_id === activeFocusedNode)
        : rawData.edges;

      for (const edge of edgesToRender) {{
        const fromCard = nodeElements.get(edge.from_node_id);
        const toCard = nodeElements.get(edge.to_node_id);
        if (!fromCard || !toCard) continue;

        const fromPos = nodePositions.get(edge.from_node_id);
        const toPos = nodePositions.get(edge.to_node_id);

        const btnEl = Array.from(fromCard.querySelectorAll(".tg-btn")).find(b => b.textContent.includes(edge.button_text));
        let fromX, fromY;

        if (btnEl) {{
          fromX = fromPos.x + btnEl.offsetLeft + btnEl.offsetWidth;
          fromY = fromPos.y + btnEl.offsetTop + btnEl.offsetHeight / 2;
        }} else {{
          fromX = fromPos.x + 330;
          fromY = fromPos.y + 35;
        }}

        const toX = toPos.x;
        const toY = toPos.y + 30;

        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        const dx = Math.max(50, Math.abs(toX - fromX) * 0.4);

        let d;
        if (edge.is_back || toX < fromX) {{
          const offset = 80;
          d = `M ${{fromX}} ${{fromY}} C ${{fromX + offset}} ${{fromY}}, ${{toX - offset}} ${{toY}}, ${{toX}} ${{toY}}`;
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

    function setFocusedCard(nodeId) {{
      activeFocusedNode = nodeId;
      document.querySelectorAll(".tg-card").forEach(c => {{
        c.classList.remove("highlighted", "dimmed");
        if (focusOnlyMode && c.id !== `card-${{nodeId}}`) {{
          // Dim cards not connected to this node
          const isConnected = rawData.edges.some(e => (e.from_node_id === nodeId && e.to_node_id === c.id.replace("card-", "")) || (e.to_node_id === nodeId && e.from_node_id === c.id.replace("card-", "")));
          if (!isConnected) c.classList.add("dimmed");
        }}
      }});

      const card = nodeElements.get(nodeId);
      if (card) card.classList.add("highlighted");
      renderEdges();
    }}

    function highlightBranch(fromId, btnText) {{
      for (const p of edgePaths) {{
        if (p.dataset.from === fromId && p.dataset.btn === btnText) {{
          p.classList.add("highlighted");
          const targetCard = nodeElements.get(p.dataset.to);
          if (targetCard) targetCard.classList.add("highlighted");
        }} else {{
          p.classList.add("dimmed");
        }}
      }}
    }}

    function resetBranchHighlight() {{
      for (const p of edgePaths) {{
        p.classList.remove("highlighted", "dimmed");
      }}
      document.querySelectorAll(".tg-card").forEach(c => {{
        if (c.id !== `card-${{activeFocusedNode}}`) c.classList.remove("highlighted");
      }});
    }}

    function focusCard(nodeId) {{
      const pos = nodePositions.get(nodeId);
      if (!pos) return;
      setFocusedCard(nodeId);
      panX = window.innerWidth / 2 - (pos.x + 165) * scale;
      panY = window.innerHeight / 2 - (pos.y + 140) * scale;
      updateTransform();
    }}

    // Toggle Focus Mode
    document.getElementById("btn-focus-mode").addEventListener("click", function() {{
      focusOnlyMode = !focusOnlyMode;
      this.classList.toggle("active", focusOnlyMode);
      this.textContent = focusOnlyMode ? "🎯 Фокус-режим" : "🌐 Все линии";
      document.querySelectorAll(".tg-card").forEach(c => c.classList.remove("dimmed"));
      renderEdges();
    }});

    // Search Input
    document.getElementById("search-input").addEventListener("input", (e) => {{
      const q = e.target.value.toLowerCase().trim();
      if (!q) return;

      for (const [id, node] of Object.entries(rawData.nodes)) {{
        const titleMatch = node.title.toLowerCase().includes(q) || id.toLowerCase().includes(q);
        const btnMatch = node.keyboard && node.keyboard.rows.some(r => r.some(b => b.text.toLowerCase().includes(q) || (b.callback_data && b.callback_data.toLowerCase().includes(q))));
        if (titleMatch || btnMatch) {{
          focusCard(id);
          break;
        }}
      }}
    }});

    // Fit View
    document.getElementById("btn-fit").addEventListener("click", () => {{
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const pos of nodePositions.values()) {{
        minX = Math.min(minX, pos.x);
        minY = Math.min(minY, pos.y);
        maxX = Math.max(maxX, pos.x + 330);
        maxY = Math.max(maxY, pos.y + 360);
      }}
      const worldW = maxX - minX + 160;
      const worldH = maxY - minY + 160;
      scale = Math.min(1.0, Math.max(0.2, Math.min(window.innerWidth / worldW, window.innerHeight / worldH)));
      panX = (window.innerWidth - (maxX + minX) * scale) / 2;
      panY = (window.innerHeight - (maxY + minY) * scale) / 2;
      updateTransform();
    }});

    // Initial position on page load: CENTER ON MAIN MENU!
    centerOnMainMenu();
  </script>
</body>
</html>
"""
        output_path.write_text(html_content, encoding="utf-8")
