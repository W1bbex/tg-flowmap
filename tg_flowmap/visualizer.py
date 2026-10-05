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
  <title>tg-flowmap — Иерархическое дерево Telegram-бота</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; user-select: none; }}
    
    :root {{
      --bg-canvas: #090d16;
      --grid-dot: rgba(255, 255, 255, 0.06);
      --card-bg: #17212b;
      --card-border: rgba(255, 255, 255, 0.1);
      --card-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
      --text-main: #f5f5f5;
      --text-sub: #7e8b99;
      --btn-default: #242f3d;
      --color-primary: #2ea6ff;
      --color-success: #31b545;
      --color-danger: #df3f40;
      --color-back: #64748b;
      --color-dead: #ef4444;
      --accent: #38bdf8;
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
      height: 48px;
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      padding: 0 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      z-index: 100;
      box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    }}

    .brand {{
      font-weight: 700;
      font-size: 15px;
      letter-spacing: -0.3px;
      display: flex;
      align-items: center;
      gap: 6px;
      color: #f8fafc;
    }}
    .brand span {{ color: var(--accent); font-weight: 500; font-size: 13px; }}

    .toolbar-actions {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .search-box {{
      background: rgba(9, 13, 22, 0.7);
      border: 1px solid #334155;
      border-radius: 6px;
      padding: 6px 12px;
      color: #fff;
      font-size: 13px;
      width: 220px;
      outline: none;
      transition: border-color 0.15s, width 0.2s;
    }}
    .search-box:focus {{ border-color: var(--accent); width: 260px; }}

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
      gap: 5px;
      transition: background 0.15s;
    }}
    .btn-tool:hover {{ background: #334155; color: #fff; }}
    .btn-tool.active {{ background: #0369a1; border-color: #38bdf8; color: #fff; }}

    /* Viewport & World */
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

    /* SVG Layer with dynamic colored arrows */
    #svg-layer {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100000px;
      height: 100000px;
      pointer-events: none;
      overflow: visible;
      z-index: 10;
    }}

    .flow-edge {{
      fill: none;
      stroke-width: 2.8px;
      opacity: 0.85;
      pointer-events: stroke;
      transition: stroke-width 0.15s, opacity 0.15s;
    }}
    .flow-edge:hover {{
      stroke-width: 5px !important;
      opacity: 1 !important;
      filter: drop-shadow(0 0 6px var(--accent));
    }}
    .flow-edge.back {{
      stroke-dasharray: 8, 6;
      stroke-width: 2.2px;
      opacity: 0.45;
    }}
    .flow-edge.dead {{
      stroke-width: 3px;
      stroke-dasharray: 6, 4;
      opacity: 0.95;
    }}
    .flow-edge.highlighted {{
      stroke-width: 5px !important;
      opacity: 1 !important;
      filter: drop-shadow(0 0 8px var(--accent)) drop-shadow(0 0 14px var(--accent));
    }}
    .flow-edge.edge-pulse {{
      stroke-width: 5.5px !important;
      opacity: 1 !important;
      filter: drop-shadow(0 0 10px var(--accent)) drop-shadow(0 0 20px var(--accent)) !important;
      animation: edgePulseAnim 0.7s ease-in-out infinite alternate;
    }}
    @keyframes edgePulseAnim {{
      0% {{ stroke-width: 3.5px; opacity: 0.85; }}
      100% {{ stroke-width: 6px; opacity: 1; }}
    }}

    /* Edge Floating Label Badges */
    .edge-labels-container {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 15;
    }}

    .edge-label-pill {{
      position: absolute;
      transform: translate(-50%, -50%);
      background: #0b1320;
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 6px;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 5px;
      box-shadow: 0 4px 10px rgba(0,0,0,0.5);
      pointer-events: auto;
      white-space: nowrap;
      transition: transform 0.15s, border-color 0.15s;
    }}
    .edge-label-pill:hover {{
      transform: translate(-50%, -50%) scale(1.1);
      z-index: 50;
    }}
    .edge-label-pill code {{
      font-family: monospace;
      font-size: 10px;
      background: rgba(255, 255, 255, 0.08);
      padding: 1px 4px;
      border-radius: 3px;
      color: #cbd5e1;
    }}

    /* Nodes Container */
    .nodes-container {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 20;
    }}

    /* Telegram Card */
    .tg-card {{
      position: absolute;
      width: 320px;
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
    .tg-card.is-root-start {{
      border: 2px solid #eab308;
      box-shadow: 0 0 25px rgba(234, 179, 8, 0.3), var(--card-shadow);
    }}
    .tg-card.is-hub-menu {{
      border: 2px solid #10b981;
      box-shadow: 0 0 30px rgba(16, 185, 129, 0.35), var(--card-shadow);
    }}
    .start-entry-badge {{
      margin: 8px 12px 14px 12px;
      padding: 10px 12px;
      background: rgba(234, 179, 8, 0.08);
      border: 1px dashed rgba(234, 179, 8, 0.35);
      border-radius: 8px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .tg-card.highlighted {{
      border-color: var(--accent) !important;
      box-shadow: 0 0 0 2px var(--accent), 0 10px 30px rgba(56, 189, 248, 0.4) !important;
      z-index: 50;
    }}
    .tg-card.dimmed {{
      opacity: 0.2;
    }}

    /* Card Header */
    .tg-card-header {{
      padding: 8px 12px;
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
      max-width: 180px;
    }}

    .card-meta {{
      font-size: 10px;
      color: var(--text-sub);
      font-family: monospace;
      background: rgba(255, 255, 255, 0.05);
      padding: 2px 5px;
      border-radius: 4px;
    }}

    /* Card Message Body */
    .tg-card-body {{
      padding: 12px 14px 10px 14px;
      font-size: 12px;
      line-height: 1.45;
      color: var(--text-main);
      white-space: pre-wrap;
      word-break: break-word;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
      max-height: 180px;
      overflow: hidden;
    }}
    .tg-card-body b, .tg-card-body strong {{ color: #fff; font-weight: 600; }}
    .tg-card-body code {{
      background: rgba(0, 0, 0, 0.3);
      padding: 1px 4px;
      border-radius: 3px;
      font-size: 11px;
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
      height: 34px;
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
      min-width: 0;
      transition: filter 0.1s, transform 0.1s;
    }}
    .tg-btn:hover {{
      filter: brightness(1.2);
      transform: translateY(-1px);
    }}

    .tg-btn.style-success {{ background: var(--color-success) !important; color: #fff !important; border: none; }}
    .tg-btn.style-primary {{ background: var(--color-primary) !important; color: #fff !important; border: none; }}
    .tg-btn.style-danger {{ background: var(--color-danger) !important; color: #fff !important; border: none; }}
    .tg-btn.dead-end-btn {{
      border: 2px dashed var(--color-dead) !important;
      background: rgba(239, 68, 68, 0.2) !important;
      color: #fca5a5 !important;
    }}

    /* Connection Ports */
    .btn-port {{
      position: absolute;
      right: -3px;
      top: 50%;
      transform: translateY(-50%);
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--accent);
      border: 1px solid #fff;
    }}
    .card-top-port {{
      position: absolute;
      top: -5px;
      left: 50%;
      transform: translateX(-50%);
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      border: 2px solid var(--card-bg);
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
    <div class="brand">🧭 tg-flowmap <span>// граф экранов</span></div>
    <div class="toolbar-actions">
      <input type="text" id="search-input" class="search-box" placeholder="Поиск кнопки или экрана..." />
      <button class="btn-tool active" id="btn-labels" title="Включить / скрыть подписи на стрелочках">🏷️ Подписи</button>
      <button class="btn-tool" id="btn-fit" title="Вписать всё в экран">📐 Вписать всё</button>
    </div>
  </header>

  <div id="viewport">
    <div id="canvas-world">
      <svg id="svg-layer" width="100000" height="100000">
        <defs>
          <marker id="arrow-green" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#31b545" />
          </marker>
          <marker id="arrow-blue" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#2ea6ff" />
          </marker>
          <marker id="arrow-red" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#df3f40" />
          </marker>
          <marker id="arrow-back" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#94a3b8" />
          </marker>
          <marker id="arrow-dead" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#ef4444" />
          </marker>
          <marker id="arrow-default" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#38bdf8" />
          </marker>
        </defs>
        <g id="edges-group"></g>
      </svg>
      <div class="edge-labels-container" id="edge-labels-container"></div>
      <div class="nodes-container" id="nodes-container"></div>
    </div>

    <div class="hud-controls">
      <button class="hud-btn" id="btn-zoom-in" title="Приблизить">+</button>
      <button class="hud-btn" id="btn-zoom-out" title="Отдалить">−</button>
      <button class="hud-btn" id="btn-reset" title="К началу">⌂</button>
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

    let scale = 0.8;
    let panX = window.innerWidth / 2 - 160;
    let panY = 60;
    let isPanning = false;
    let startX = 0;
    let startY = 0;
    let showLabels = true;
    let activeFocusedNode = null;
    let animFrameId = null;

    const viewport = document.getElementById("viewport");
    const world = document.getElementById("canvas-world");
    const svgLayer = document.getElementById("svg-layer");
    const labelsContainer = document.getElementById("edge-labels-container");
    const nodesContainer = document.getElementById("nodes-container");

    function updateTransform() {{
      world.style.transform = `translate3d(${{panX}}px, ${{panY}}px, 0) scale(${{scale}})`;
    }}
    updateTransform();

    // Smooth Flying Animation Engine
    function smoothFlyTo(targetPanX, targetPanY, targetScale = scale, duration = 650) {{
      if (animFrameId) {{
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
      }}
      if (duration <= 0) {{
        panX = targetPanX;
        panY = targetPanY;
        scale = targetScale;
        updateTransform();
        return;
      }}

      const startPanX = panX;
      const startPanY = panY;
      const startScale = scale;
      const startTime = performance.now();

      function easeInOutCubic(t) {{
        return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      }}

      function frame(now) {{
        const elapsed = now - startTime;
        const p = Math.min(1.0, elapsed / duration);
        const ease = easeInOutCubic(p);

        panX = startPanX + (targetPanX - startPanX) * ease;
        panY = startPanY + (targetPanY - startPanY) * ease;
        scale = startScale + (targetScale - startScale) * ease;
        updateTransform();

        if (p < 1.0) {{
          animFrameId = requestAnimationFrame(frame);
        }} else {{
          animFrameId = null;
        }}
      }}

      animFrameId = requestAnimationFrame(frame);
    }}

    // Pan & Zoom
    viewport.addEventListener("mousedown", (e) => {{
      if (animFrameId) {{
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
      }}
      if (e.target.closest(".tg-card") || e.target.closest(".hud-controls") || e.target.closest(".edge-label-pill")) return;
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
      if (animFrameId) {{
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
      }}
      const zoomFactor = 1.15;
      const oldScale = scale;
      if (e.deltaY < 0) {{
        scale = Math.min(2.5, scale * zoomFactor);
      }} else {{
        scale = Math.max(0.015, scale / zoomFactor);
      }}
      const rect = viewport.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      panX = mouseX - (mouseX - panX) * (scale / oldScale);
      panY = mouseY - (mouseY - panY) * (scale / oldScale);
      updateTransform();
    }}, {{ passive: false }});

    document.getElementById("btn-zoom-in").addEventListener("click", () => {{
      smoothFlyTo(panX, panY, Math.min(2.5, scale * 1.3), 300);
    }});
    document.getElementById("btn-zoom-out").addEventListener("click", () => {{
      smoothFlyTo(panX, panY, Math.max(0.015, scale / 1.3), 300);
    }});
    document.getElementById("btn-reset").addEventListener("click", () => centerOnStart(650));

    function centerOnStart(duration = 650) {{
      const startPos = nodePositions.get("cmd:/start") || nodePositions.get("cb:menu") || {{ x: 0, y: 0 }};
      const targetScale = 0.8;
      const targetPanX = window.innerWidth / 2 - (startPos.x + CARD_W / 2) * targetScale;
      const targetPanY = 60;
      smoothFlyTo(targetPanX, targetPanY, targetScale, duration);
      highlightCard(nodePositions.has("cmd:/start") ? "cmd:/start" : "cb:menu");
    }}

    function centerOnHubMenu(duration = 650) {{
      const hubPos = nodePositions.get("cb:menu") || {{ x: 0, y: 0 }};
      const targetScale = 0.8;
      const targetPanX = window.innerWidth / 2 - (hubPos.x + CARD_W / 2) * targetScale;
      const targetPanY = window.innerHeight / 2 - (hubPos.y + 160) * targetScale;
      smoothFlyTo(targetPanX, targetPanY, targetScale, duration);
      highlightCard("cb:menu");
    }}

    // ==========================================
    // RIGOROUS NON-OVERLAPPING TREE LAYOUT (DAG)
    // ==========================================
    const CARD_W = 320;
    const CARD_H = 380;
    const SIBLING_GAP_X = 90;
    const LEVEL_GAP_Y = 190;

    const nodePositions = new Map();
    const nodeElements = new Map();

    // 1. Identify Spanning Tree Roots
    // Hierarchy: cmd:/start at top -> cb:menu (Dashboard) underneath -> submenus -> actions
    const rootId = rawData.nodes["cmd:/start"] ? "cmd:/start" : (rawData.nodes["cb:menu"] ? "cb:menu" : Object.keys(rawData.nodes)[0]);
    const hubId = rawData.nodes["cb:menu"] ? "cb:menu" : rootId;
    const isStartHubPair = (rootId === "cmd:/start" && hubId === "cb:menu" && rootId !== hubId);

    // Build forward adjacency list (excluding back buttons to avoid cycles)
    const forwardChildren = new Map();
    for (const id of Object.keys(rawData.nodes)) {{
      forwardChildren.set(id, []);
    }}

    // Add entry transition: /start -> cb:menu
    if (isStartHubPair) {{
      forwardChildren.get(rootId).push(hubId);
    }}

    for (const edge of rawData.edges) {{
      if (edge.is_back) continue;
      if (edge.from_node_id === edge.to_node_id) continue;
      // If root is /start and hub is cb:menu, don't duplicate submenus directly off /start; let cb:menu own them!
      if (isStartHubPair && edge.from_node_id === rootId) continue;
      if (edge.from_node_id === rootId && edge.to_node_id === hubId) continue; // already added

      const list = forwardChildren.get(edge.from_node_id);
      if (list && !list.includes(edge.to_node_id) && rawData.nodes[edge.to_node_id]) {{
        list.push(edge.to_node_id);
      }}
    }}

    // Calculate Subtree Widths recursively (with cycle breaker)
    function computeSubtreeWidth(nodeId, visitedPath) {{
      if (visitedPath.has(nodeId)) return CARD_W;
      const v = new Set(visitedPath);
      v.add(nodeId);

      const children = (forwardChildren.get(nodeId) || []).filter(c => !v.has(c));
      if (children.length === 0) return CARD_W;

      let totalW = 0;
      children.forEach((childId, i) => {{
        if (i > 0) totalW += SIBLING_GAP_X;
        totalW += computeSubtreeWidth(childId, v);
      }});
      return Math.max(CARD_W, totalW);
    }}

    // Place Nodes in Spanning Tree
    const placedNodes = new Set();

    function placeTreeNodes(nodeId, leftX, levelY, visitedPath) {{
      placedNodes.add(nodeId);
      const v = new Set(visitedPath);
      v.add(nodeId);

      const children = (forwardChildren.get(nodeId) || []).filter(c => !placedNodes.has(c) && !v.has(c));
      const subtreeW = computeSubtreeWidth(nodeId, visitedPath);

      // Center parent card above its children subtree
      const myX = leftX + (subtreeW - CARD_W) / 2;
      nodePositions.set(nodeId, {{ x: myX, y: levelY }});

      let childLeftX = leftX;
      children.forEach((childId) => {{
        const childW = computeSubtreeWidth(childId, v);
        placeTreeNodes(childId, childLeftX, levelY + CARD_H + LEVEL_GAP_Y, v);
        childLeftX += childW + SIBLING_GAP_X;
      }});
    }}

    // Lay out main bot tree from /start
    placeTreeNodes(rootId, 0, 0, new Set());

    // Lay out any unvisited or isolated nodes in neat columns to the side
    let unvisitedLeftX = 0;
    for (const [id, pos] of nodePositions.entries()) {{
      unvisitedLeftX = Math.max(unvisitedLeftX, pos.x + CARD_W + 240);
    }}

    let unvisitedY = 0;
    for (const id of Object.keys(rawData.nodes)) {{
      if (!placedNodes.has(id)) {{
        nodePositions.set(id, {{ x: unvisitedLeftX, y: unvisitedY }});
        unvisitedY += CARD_H + LEVEL_GAP_Y;
        placedNodes.add(id);
      }}
    }}

    // ==========================================
    // RENDER TELEGRAM CARDS
    // ==========================================
    for (const [nodeId, node] of Object.entries(rawData.nodes)) {{
      createCard(nodeId, node);
    }}

    function createCard(nodeId, node) {{
      const pos = nodePositions.get(nodeId) || {{ x: 0, y: 0 }};
      const card = document.createElement("div");
      card.className = "tg-card";
      if (nodeId === "cmd:/start") card.classList.add("is-root-start");
      if (nodeId === "cb:menu") card.classList.add("is-hub-menu");
      card.id = `card-${{nodeId}}`;
      card.style.left = `${{pos.x}}px`;
      card.style.top = `${{pos.y}}px`;

      // Top Port for incoming arrows
      const topPort = document.createElement("div");
      topPort.className = "card-top-port";
      card.appendChild(topPort);

      // Card Header
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

      // Message Body
      const body = document.createElement("div");
      body.className = "tg-card-body";
      body.innerHTML = node.text_template || "<i>(Пустой текст)</i>";
      card.appendChild(body);

      // Keyboard with Colored Buttons or Entry Badge
      const isStartHub = (isStartHubPair && nodeId === rootId);
      if (isStartHub) {{
        const badge = document.createElement("div");
        badge.className = "start-entry-badge";
        badge.innerHTML = `
          <div style="font-size:11px; color:#cbd5e1; font-weight:600;">⚡ Точка входа в бота:</div>
          <div style="display:flex; align-items:center; gap:8px;">
            <code style="background:rgba(234, 179, 8, 0.2); color:#facc15; border:1px solid rgba(234, 179, 8, 0.4); padding:3px 8px; border-radius:4px; font-weight:700;">/start</code>
            <span style="font-size:11px; color:#94a3b8;">➔ открывает Главное меню</span>
          </div>
        `;
        card.appendChild(badge);
      }} else if (node.keyboard && node.keyboard.rows && node.keyboard.rows.length) {{
        const kbDiv = document.createElement("div");
        kbDiv.className = "tg-keyboard";

        node.keyboard.rows.forEach((row, rowIdx) => {{
          const rowDiv = document.createElement("div");
          rowDiv.className = "tg-row";

          row.forEach((btn, btnIdx) => {{
            const btnEl = document.createElement("div");
            btnEl.className = "tg-btn";
            btnEl.id = `btn-${{nodeId}}-${{rowIdx}}-${{btnIdx}}`;
            btnEl.dataset.btnText = btn.text;
            if (btn.callback_data) btnEl.dataset.callbackData = btn.callback_data;

            // Color Class
            const btnStyle = getButtonColorClass(btn);
            if (btnStyle) btnEl.classList.add(btnStyle);

            // Dead end
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

            btnEl.addEventListener("mouseenter", () => highlightEdgeBranch(nodeId, btn.text));
            btnEl.addEventListener("mouseleave", () => resetEdgeHighlights());
            btnEl.addEventListener("click", (e) => {{
              e.stopPropagation();
              const edge = rawData.edges.find(e => e.from_node_id === nodeId && e.button_text === btn.text);
              if (edge && edge.to_node_id) {{
                pulseEdgeBranch(nodeId, edge.to_node_id, btn.text);
                focusOnCard(edge.to_node_id, 700);
              }}
            }});

            rowDiv.appendChild(btnEl);
          }});

          kbDiv.appendChild(rowDiv);
        }});

        card.appendChild(kbDiv);
      }}

      setupCardDrag(card, header, nodeId);
      nodesContainer.appendChild(card);
      nodeElements.set(nodeId, card);
    }}

    function getButtonColorClass(btn) {{
      if (btn.style) return `style-${{btn.style.toLowerCase()}}`;
      const tLow = btn.text.toLowerCase();
      if (tLow.includes("питание") || tLow.includes("включить") || tLow.includes("разблокировать")) return "style-success";
      if (tLow.includes("выключить") || tLow.includes("отмена") || tLow.includes("удалить")) return "style-danger";
      if (tLow.includes("скриншот") || tLow.includes("программы") || tLow.includes("звук") || tLow.includes("настройки")) return "style-primary";
      return "";
    }}

    function getButtonHexColor(btn) {{
      const cls = getButtonColorClass(btn);
      if (cls === "style-success") return "#31b545";
      if (cls === "style-danger") return "#df3f40";
      if (cls === "style-primary") return "#2ea6ff";
      return "#38bdf8";
    }}

    function setupCardDrag(card, handle, nodeId) {{
      let dragStartX, dragStartY, cardStartX, cardStartY, isDragging = false;

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
        renderConnectors();
      }});

      window.addEventListener("mouseup", () => {{
        if (isDragging) isDragging = false;
      }});
    }}

    // ==========================================
    // RENDER COLORED & LABELED ARROWS
    // ==========================================
    const renderedEdgePaths = [];

    function renderConnectors() {{
      const edgesGroup = document.getElementById("edges-group");
      if (!edgesGroup) return;
      edgesGroup.innerHTML = "";
      labelsContainer.innerHTML = "";
      renderedEdgePaths.length = 0;

      // Special entry connector: /start -> cb:menu
      if (isStartHubPair) {{
        drawDirectArrow(rootId, hubId, "Запуск бота", "/start", "#10b981", false);
      }}

      // Standard button transitions
      for (const edge of rawData.edges) {{
        if (isStartHubPair && edge.from_node_id === rootId) continue;

        const fromCard = nodeElements.get(edge.from_node_id);
        const toCard = nodeElements.get(edge.to_node_id);
        const fromPos = nodePositions.get(edge.from_node_id);
        const toPos = nodePositions.get(edge.to_node_id);
        if (!fromCard || !toCard || !fromPos || !toPos) continue;

        const btnEl = Array.from(fromCard.querySelectorAll(".tg-btn")).find(b => 
          (edge.callback_data && b.dataset.callbackData === edge.callback_data) ||
          (edge.button_text && b.dataset.btnText === edge.button_text) ||
          (edge.button_text && b.textContent.includes(edge.button_text))
        );
        
        let strokeColor = "#38bdf8";
        let markerId = "url(#arrow-default)";

        if (edge.status === "dead_end") {{
          strokeColor = "#ef4444";
          markerId = "url(#arrow-dead)";
        }} else if (edge.is_back) {{
          strokeColor = "#64748b";
          markerId = "url(#arrow-back)";
        }} else if (btnEl) {{
          const isSuccess = btnEl.classList.contains("style-success");
          const isDanger = btnEl.classList.contains("style-danger");
          const isPrimary = btnEl.classList.contains("style-primary");
          if (isSuccess) {{ strokeColor = "#31b545"; markerId = "url(#arrow-green)"; }}
          else if (isDanger) {{ strokeColor = "#df3f40"; markerId = "url(#arrow-red)"; }}
          else if (isPrimary) {{ strokeColor = "#2ea6ff"; markerId = "url(#arrow-blue)"; }}
        }}

        // Accurate coordinates relative to world canvas
        let fromX = fromPos.x + CARD_W / 2;
        let fromY = fromPos.y + (fromCard.offsetHeight || CARD_H);
        if (btnEl) {{
          const bRect = btnEl.getBoundingClientRect();
          const cRect = fromCard.getBoundingClientRect();
          if (bRect.width > 0 && scale > 0) {{
            const relX = (bRect.right - cRect.left) / scale;
            const relY = ((bRect.top + bRect.bottom) / 2 - cRect.top) / scale;
            fromX = fromPos.x + relX;
            fromY = fromPos.y + relY;
          }}
        }}

        const toX = toPos.x + CARD_W / 2;
        const toY = toPos.y;

        // Curve path
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        let d;
        let midX, midY;

        if (edge.is_back || toY <= fromY) {{
          // Return / backward curved loop
          const loop = 70;
          d = `M ${{fromX}} ${{fromY}} C ${{fromX + loop}} ${{fromY}}, ${{toX - loop}} ${{toY - 40}}, ${{toX}} ${{toY}}`;
          midX = (fromX + toX) / 2 + loop / 2;
          midY = (fromY + toY) / 2 - 20;
        }} else {{
          // Clean downward branching curve
          const dy = Math.max(30, (toY - fromY) * 0.5);
          d = `M ${{fromX}} ${{fromY}} C ${{fromX + 40}} ${{fromY + dy}}, ${{toX}} ${{toY - dy}}, ${{toX}} ${{toY}}`;
          midX = (fromX + toX) / 2;
          midY = (fromY + toY) / 2;
        }}

        path.setAttribute("d", d);
        let cls = "flow-edge";
        if (edge.status === "dead_end") cls += " dead";
        if (edge.is_back) cls += " back";

        path.setAttribute("class", cls);
        path.setAttribute("stroke", strokeColor);
        path.setAttribute("stroke-width", "2.8");
        path.setAttribute("fill", "none");
        path.setAttribute("marker-end", markerId);
        path.dataset.from = edge.from_node_id;
        path.dataset.to = edge.to_node_id;
        path.dataset.btn = edge.button_text;

        edgesGroup.appendChild(path);
        renderedEdgePaths.push(path);

        // Edge Floating Label Pill
        if (showLabels && !edge.is_back && edge.button_text) {{
          const pill = document.createElement("div");
          pill.className = "edge-label-pill";
          pill.style.left = `${{midX}}px`;
          pill.style.top = `${{midY}}px`;
          pill.style.borderColor = strokeColor;
          pill.innerHTML = `<span style="color:${{strokeColor}}">${{edge.button_text}}</span> <code>${{edge.callback_data}}</code>`;

          pill.addEventListener("mouseenter", () => highlightEdgeBranch(edge.from_node_id, edge.button_text));
          pill.addEventListener("mouseleave", () => resetEdgeHighlights());
          pill.addEventListener("click", () => {{
            pulseEdgeBranch(edge.from_node_id, edge.to_node_id, edge.button_text);
            focusOnCard(edge.to_node_id, 700);
          }});

          labelsContainer.appendChild(pill);
        }}
      }}
    }}

    function drawDirectArrow(fromId, toId, text, cb, color, isBack) {{
      const edgesGroup = document.getElementById("edges-group");
      if (!edgesGroup) return;
      const fromPos = nodePositions.get(fromId);
      const toPos = nodePositions.get(toId);
      const fromCard = nodeElements.get(fromId);
      const toCard = nodeElements.get(toId);
      if (!fromPos || !toPos || !fromCard || !toCard) return;

      const fromH = fromCard.offsetHeight || CARD_H;
      const fromX = fromPos.x + CARD_W / 2;
      const fromY = fromPos.y + fromH;
      const toX = toPos.x + CARD_W / 2;
      const toY = toPos.y;

      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      const d = `M ${{fromX}} ${{fromY}} C ${{fromX}} ${{fromY + 50}}, ${{toX}} ${{toY - 50}}, ${{toX}} ${{toY}}`;
      path.setAttribute("d", d);
      path.setAttribute("class", "flow-edge");
      path.setAttribute("stroke", color);
      path.setAttribute("stroke-width", "3.2");
      path.setAttribute("fill", "none");
      path.setAttribute("marker-end", "url(#arrow-green)");
      path.dataset.from = fromId;
      path.dataset.to = toId;
      path.dataset.btn = text;
      edgesGroup.appendChild(path);
      renderedEdgePaths.push(path);

      if (showLabels) {{
        const pill = document.createElement("div");
        pill.className = "edge-label-pill";
        pill.style.left = `${{(fromX + toX) / 2}}px`;
        pill.style.top = `${{(fromY + toY) / 2}}px`;
        pill.style.borderColor = color;
        pill.innerHTML = `<span style="color:${{color}}">${{text}}</span> <code>${{cb}}</code>`;
        pill.addEventListener("mouseenter", () => highlightEdgeBranch(fromId, text));
        pill.addEventListener("mouseleave", () => resetEdgeHighlights());
        pill.addEventListener("click", () => {{
          pulseEdgeBranch(fromId, toId, text);
          focusOnCard(toId, 700);
        }});
        labelsContainer.appendChild(pill);
      }}
    }}

    setTimeout(renderConnectors, 60);
    setTimeout(renderConnectors, 250);
    window.addEventListener("load", renderConnectors);

    function pulseEdgeBranch(fromId, toId, btnText) {{
      highlightEdgeBranch(fromId, btnText);
      for (const p of renderedEdgePaths) {{
        if ((p.dataset.from === fromId && p.dataset.to === toId) || (p.dataset.from === fromId && p.dataset.btn === btnText)) {{
          p.classList.add("edge-pulse");
          setTimeout(() => p.classList.remove("edge-pulse"), 1400);
        }}
      }}
    }}

    function highlightEdgeBranch(fromId, btnText) {{
      for (const p of renderedEdgePaths) {{
        if (p.dataset.from === fromId && p.dataset.btn === btnText) {{
          p.classList.add("highlighted");
          const targetCard = nodeElements.get(p.dataset.to);
          if (targetCard) targetCard.classList.add("highlighted");
        }} else {{
          p.classList.add("dimmed");
        }}
      }}
    }}

    function resetEdgeHighlights() {{
      for (const p of renderedEdgePaths) {{
        p.classList.remove("highlighted", "dimmed");
      }}
      document.querySelectorAll(".tg-card.highlighted").forEach(c => c.classList.remove("highlighted"));
    }}

    function highlightCard(nodeId) {{
      document.querySelectorAll(".tg-card.highlighted").forEach(c => c.classList.remove("highlighted"));
      const card = nodeElements.get(nodeId);
      if (card) card.classList.add("highlighted");
    }}

    function focusOnCard(nodeId, duration = 650) {{
      const pos = nodePositions.get(nodeId);
      if (!pos) return;
      highlightCard(nodeId);
      const targetPanX = window.innerWidth / 2 - (pos.x + CARD_W / 2) * scale;
      const targetPanY = window.innerHeight / 2 - (pos.y + 160) * scale;
      smoothFlyTo(targetPanX, targetPanY, scale, duration);
    }}

    // Search Input
    document.getElementById("search-input").addEventListener("input", (e) => {{
      const q = e.target.value.toLowerCase().trim();
      if (!q) return;

      for (const [id, node] of Object.entries(rawData.nodes)) {{
        const titleMatch = node.title.toLowerCase().includes(q) || id.toLowerCase().includes(q);
        const btnMatch = node.keyboard && node.keyboard.rows.some(r => r.some(b => b.text.toLowerCase().includes(q) || (b.callback_data && b.callback_data.toLowerCase().includes(q))));
        if (titleMatch || btnMatch) {{
          focusOnCard(id, 700);
          break;
        }}
      }}
    }});

    // Toggle Labels
    document.getElementById("btn-labels").addEventListener("click", function() {{
      showLabels = !showLabels;
      this.classList.toggle("active", showLabels);
      renderConnectors();
    }});

    // Fit View
    document.getElementById("btn-fit").addEventListener("click", () => {{
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const pos of nodePositions.values()) {{
        minX = Math.min(minX, pos.x);
        minY = Math.min(minY, pos.y);
        maxX = Math.max(maxX, pos.x + CARD_W);
        maxY = Math.max(maxY, pos.y + CARD_H);
      }}
      const worldW = maxX - minX + 160;
      const worldH = maxY - minY + 160;
      const targetScale = Math.min(1.0, Math.max(0.12, Math.min(window.innerWidth / worldW, window.innerHeight / worldH)));
      const targetPanX = (window.innerWidth - (maxX + minX) * targetScale) / 2;
      const targetPanY = 40;
      smoothFlyTo(targetPanX, targetPanY, targetScale, 700);
    }});

    window.addEventListener("resize", () => {{
      renderConnectors();
    }});

    // Initial View on load: Start at Top!
    centerOnStart(0);
  </script>
</body>
</html>
"""
        output_path.write_text(html_content, encoding="utf-8")
