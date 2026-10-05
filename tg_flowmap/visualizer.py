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
    #viewport.panning #canvas-world * {{
      pointer-events: none !important;
      user-select: none !important;
    }}
    #viewport.zoomed-out .edge-label-pill {{
      display: none !important;
    }}

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
      pointer-events: none;
      overflow: visible;
      z-index: 10;
    }}

    .flow-edge {{
      fill: none;
      stroke-width: 2.8px;
      opacity: 0.85;
      pointer-events: stroke;
      transition: stroke-width 0.12s, opacity 0.12s;
    }}
    .flow-edge:hover {{
      stroke-width: 4.8px !important;
      opacity: 1 !important;
    }}
    .flow-edge.back {{
      stroke-dasharray: 8, 6;
      stroke-width: 2.2px;
      opacity: 0.4;
    }}
    .flow-edge.dead {{
      stroke-width: 3px;
      stroke-dasharray: 6, 4;
      opacity: 0.95;
    }}
    .flow-edge.highlighted {{
      stroke-width: 4.8px !important;
      opacity: 1 !important;
    }}
    .flow-edge.edge-pulse {{
      stroke-width: 5.2px !important;
      opacity: 1 !important;
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
    .tg-card.is-utility-card {{
      border: 1px dashed rgba(239, 68, 68, 0.45);
      background: #0d1527;
    }}
    .utility-badge {{
      font-size: 10px;
      color: #f87171;
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.3);
      padding: 1px 5px;
      border-radius: 4px;
      font-weight: 600;
      white-space: nowrap;
    }}
    .cmd-badge {{
      font-size: 10px;
      color: #38bdf8;
      background: rgba(56, 189, 248, 0.15);
      border: 1px solid rgba(56, 189, 248, 0.3);
      padding: 1px 5px;
      border-radius: 4px;
      font-weight: 600;
      white-space: nowrap;
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
      <button class="btn-tool" id="btn-back-edges" title="Показать / скрыть обратные стрелки «Назад» и «В меню»">↩ Возвраты</button>
      <button class="btn-tool active" id="btn-labels" title="Включить / скрыть подписи на стрелочках">🏷️ Подписи</button>
      <button class="btn-tool" id="btn-fit" title="Вписать всё в экран">📐 Вписать всё</button>
    </div>
  </header>

  <div id="viewport">
    <div id="canvas-world">
      <svg id="svg-layer">
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

    let isTransformPending = false;

    function scheduleTransform() {{
      if (!isTransformPending) {{
        isTransformPending = true;
        requestAnimationFrame(() => {{
          updateTransform();
          isTransformPending = false;
        }});
      }}
    }}

    function updateTransform() {{
      world.style.transform = `translate3d(${{panX}}px, ${{panY}}px, 0) scale(${{scale}})`;
      if (scale < 0.35) {{
        viewport.classList.add("zoomed-out");
      }} else {{
        viewport.classList.remove("zoomed-out");
      }}
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
      scheduleTransform();
    }});

    window.addEventListener("mouseup", () => {{
      if (isPanning) {{
        isPanning = false;
        viewport.classList.remove("panning");
      }}
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
      scheduleTransform();
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
    // RIGOROUS NON-OVERLAPPING MULTI-ROOT DAG FOREST
    // ==========================================
    const CARD_W = 320;
    const CARD_H = 380;
    const SIBLING_GAP_X = 70;
    const LEVEL_GAP_Y = 160;

    const nodePositions = new Map();
    const nodeElements = new Map();

    const rootId = rawData.nodes["cmd:/start"] ? "cmd:/start" : (rawData.nodes["cb:menu"] ? "cb:menu" : Object.keys(rawData.nodes)[0]);
    const hubId = rawData.nodes["cb:menu"] ? "cb:menu" : rootId;
    const isStartHubPair = (rootId === "cmd:/start" && hubId === "cb:menu" && rootId !== hubId);

    // ==========================================
    // UTILITY / SYSTEM TARGETS DEFINITION
    // ==========================================
    const UTILITY_TARGETS = new Set([
      "cb:flow_unlock_retry",
      "cb:flow_unlock_cancel",
      "cb:noop",
      "cb:flow_workspace_cancel"
    ]);

    // Automatically detect utility callback targets (pure retry/cancel/close handlers)
    for (const [nodeId, node] of Object.entries(rawData.nodes)) {{
      const incoming = rawData.edges.filter(e => e.to_node_id === nodeId);
      if (incoming.length >= 3) {{
        const allUtility = incoming.every(e => {{
          const t = (e.button_text || "").toLowerCase();
          return t.includes("отмена") || t.includes("попробовать") || t.includes("cancel") || t.includes("retry") || t.includes("закрыть") || t.includes("close") || t.includes("выйти");
        }});
        if (allUtility) UTILITY_TARGETS.add(nodeId);
      }}
    }}

    // 1. Build Adjacency List (ignoring back buttons & utility popups)
    const forwardEdgesMap = new Map();
    for (const id of Object.keys(rawData.nodes)) {{
      forwardEdgesMap.set(id, []);
    }}

    if (isStartHubPair) {{
      forwardEdgesMap.get(rootId).push(hubId);
    }}

    for (const edge of rawData.edges) {{
      if (edge.is_back) continue;
      if (edge.from_node_id === edge.to_node_id) continue;
      if (isStartHubPair && edge.from_node_id === rootId) continue;
      if (edge.from_node_id === rootId && edge.to_node_id === hubId) continue;
      if (UTILITY_TARGETS.has(edge.to_node_id)) continue;

      const list = forwardEdgesMap.get(edge.from_node_id);
      if (list && !list.includes(edge.to_node_id) && rawData.nodes[edge.to_node_id]) {{
        list.push(edge.to_node_id);
      }}
    }}

    // 2. Build Strict BFS Spanning Forest
    const treeChildren = new Map();
    for (const id of Object.keys(rawData.nodes)) {{
      treeChildren.set(id, []);
    }}

    const visitedNodes = new Set();
    const nodeToRoot = new Map();
    const forestRoots = [];

    function exploreBfsTree(startRoot) {{
      if (!rawData.nodes[startRoot] || visitedNodes.has(startRoot) || UTILITY_TARGETS.has(startRoot)) return;
      visitedNodes.add(startRoot);
      forestRoots.push(startRoot);
      nodeToRoot.set(startRoot, startRoot);
      const queue = [startRoot];

      while (queue.length > 0) {{
        const curr = queue.shift();
        const children = forwardEdgesMap.get(curr) || [];
        for (const childId of children) {{
          if (UTILITY_TARGETS.has(childId)) continue;
          if (!visitedNodes.has(childId)) {{
            visitedNodes.add(childId);
            nodeToRoot.set(childId, startRoot);
            treeChildren.get(curr).push(childId);
            queue.push(childId);
          }}
        }}
      }}
    }}

    // Explore main bot first
    exploreBfsTree(rootId);
    if (!visitedNodes.has(hubId)) exploreBfsTree(hubId);

    // Explore secondary bot commands (e.g. /led, /console, /exit, /player)
    const priorityCmds = ["cmd:/led", "cmd:/console", "cmd:/exit", "cmd:/player", "cmd:/cmd", "cmd:/ps", "cmd:/led_on", "cmd:/led_off"];
    for (const cmdId of priorityCmds) {{
      exploreBfsTree(cmdId);
    }}
    for (const k of Object.keys(rawData.nodes)) {{
      if (k.startsWith("cmd:")) exploreBfsTree(k);
    }}

    // 3. Exact Subtree Width on the Spanning Tree (Zero phantom spaces!)
    function computeSubtreeWidth(nodeId) {{
      const children = treeChildren.get(nodeId) || [];
      if (children.length === 0) return CARD_W;
      let totalW = 0;
      for (let i = 0; i < children.length; i++) {{
        if (i > 0) totalW += SIBLING_GAP_X;
        totalW += computeSubtreeWidth(children[i]);
      }}
      return Math.max(CARD_W, totalW);
    }}

    function placeTreeNode(nodeId, leftX, levelY) {{
      const subtreeW = computeSubtreeWidth(nodeId);
      const myX = leftX + (subtreeW - CARD_W) / 2;
      nodePositions.set(nodeId, {{ x: myX, y: levelY }});

      let childLeftX = leftX;
      const children = treeChildren.get(nodeId) || [];
      for (const childId of children) {{
        const childW = computeSubtreeWidth(childId);
        placeTreeNode(childId, childLeftX, levelY + CARD_H + LEVEL_GAP_Y);
        childLeftX += childW + SIBLING_GAP_X;
      }}
    }}

    // 4. Place Trees side-by-side
    let currentBlockX = 0;
    for (const r of forestRoots) {{
      const treeW = computeSubtreeWidth(r);
      placeTreeNode(r, currentBlockX, 0);
      currentBlockX += treeW + 200;
    }}

    // 5. Place Utility Cards in a Dedicated Section
    const utilNodesList = Object.keys(rawData.nodes).filter(k => UTILITY_TARGETS.has(k));
    if (utilNodesList.length > 0) {{
      const utilBlockX = currentBlockX + 80;
      const cols = 2;
      utilNodesList.forEach((id, idx) => {{
        const c = idx % cols;
        const r = Math.floor(idx / cols);
        const gx = utilBlockX + c * (CARD_W + 50);
        const gy = r * (CARD_H + 50);
        nodePositions.set(id, {{ x: gx, y: gy }});
      }});
      currentBlockX = utilBlockX + cols * (CARD_W + 50) + 80;
    }}

    // 6. Place Remaining Unvisited Orphans in a Compact 4-Column Grid
    const unvisited = Object.keys(rawData.nodes).filter(k => !visitedNodes.has(k) && !UTILITY_TARGETS.has(k));
    if (unvisited.length > 0) {{
      const gridStartX = currentBlockX + 60;
      const cols = 4;
      unvisited.forEach((id, idx) => {{
        const c = idx % cols;
        const r = Math.floor(idx / cols);
        const gx = gridStartX + c * (CARD_W + 50);
        const gy = r * (CARD_H + 50);
        nodePositions.set(id, {{ x: gx, y: gy }});
      }});
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
      if (UTILITY_TARGETS.has(nodeId)) card.classList.add("is-utility-card");
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
      const icon = nodeId.startsWith("cmd:") ? "⚡" : (nodeId === "cb:menu" ? "📱" : (UTILITY_TARGETS.has(nodeId) ? "⚙️" : "💬"));
      const srcName = node.source_file ? node.source_file.split(/[/\\\\]/).pop() : "";
      const lineStr = node.line_number ? `:${{node.line_number}}` : "";

      let badgeHtml = "";
      if (UTILITY_TARGETS.has(nodeId)) {{
        badgeHtml = `<span class="utility-badge">Попап</span>`;
      }} else if (nodeId.startsWith("cmd:") && nodeId !== "cmd:/start") {{
        badgeHtml = `<span class="cmd-badge">Команда</span>`;
      }}

      header.innerHTML = `
        <div class="card-title-group">
          <span style="font-size:13px;">${{icon}}</span>
          <span class="card-screen-title" title="${{node.title}}">${{node.title}}</span>
          ${{badgeHtml}}
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

            btnEl.addEventListener("mouseenter", () => {{
              highlightEdgeBranch(nodeId, btn.text);
              showTempTargetArrow(nodeId, btn.text);
            }});
            btnEl.addEventListener("mouseleave", () => {{
              resetEdgeHighlights();
              removeTempReturnArrow();
            }});
            btnEl.addEventListener("click", (e) => {{
              e.stopPropagation();
              const edge = rawData.edges.find(e => 
                e.from_node_id === nodeId && 
                ((btn.callback_data && e.callback_data === btn.callback_data) || e.button_text === btn.text)
              );
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
    // RENDER COLORED & LABELED ARROWS WITH BUNDLING
    // ==========================================
    const renderedEdgePaths = [];
    let showBackEdges = false;
    let tempReturnPath = null;

    function isReturnOrCross(edge, fromPos, toPos) {{
      if (edge.is_back) return true;
      if (toPos.y <= fromPos.y) return true;
      const fromRoot = nodeToRoot.get(edge.from_node_id);
      const toRoot = nodeToRoot.get(edge.to_node_id);
      if ((toRoot === rootId || toRoot === hubId) && fromRoot !== toRoot) {{
        return true;
      }}
      return false;
    }}

    function renderConnectors() {{
      const edgesGroup = document.getElementById("edges-group");
      if (!edgesGroup) return;
      edgesGroup.innerHTML = "";
      labelsContainer.innerHTML = "";
      renderedEdgePaths.length = 0;
      removeTempReturnArrow();

      // Dynamically size SVG layer to match graph bounds
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const pos of nodePositions.values()) {{
        minX = Math.min(minX, pos.x);
        minY = Math.min(minY, pos.y);
        maxX = Math.max(maxX, pos.x + CARD_W);
        maxY = Math.max(maxY, pos.y + CARD_H);
      }}
      const worldW = Math.max(2000, maxX - minX + 600);
      const worldH = Math.max(2000, maxY - minY + 600);
      svgLayer.setAttribute("width", worldW);
      svgLayer.setAttribute("height", worldH);
      svgLayer.style.width = worldW + "px";
      svgLayer.style.height = worldH + "px";

      // Special entry connector: /start -> cb:menu
      if (isStartHubPair) {{
        drawDirectArrow(rootId, hubId, "Запуск бота", "/start", "#10b981", false);
      }}

      // Group edges by (from_node_id, to_node_id, is_back) to eliminate duplicate fans
      const bundles = new Map();
      for (const edge of rawData.edges) {{
        if (isStartHubPair && edge.from_node_id === rootId) continue;
        if (edge.from_node_id === edge.to_node_id) continue;
        if (UTILITY_TARGETS.has(edge.to_node_id)) continue;

        const fromPos = nodePositions.get(edge.from_node_id);
        const toPos = nodePositions.get(edge.to_node_id);
        if (!fromPos || !toPos) continue;

        const isRet = isReturnOrCross(edge, fromPos, toPos);
        if (isRet && !showBackEdges) continue;

        const bKey = `${{edge.from_node_id}}:::${{edge.to_node_id}}:::${{!!isRet}}`;
        if (!bundles.has(bKey)) {{
          bundles.set(bKey, {{
            from_node_id: edge.from_node_id,
            to_node_id: edge.to_node_id,
            is_back: !!isRet,
            status: edge.status,
            edges: []
          }});
        }}
        bundles.get(bKey).edges.push(edge);
      }}

      for (const bundle of bundles.values()) {{
        const fromCard = nodeElements.get(bundle.from_node_id);
        const toCard = nodeElements.get(bundle.to_node_id);
        const fromPos = nodePositions.get(bundle.from_node_id);
        const toPos = nodePositions.get(bundle.to_node_id);
        if (!fromCard || !toCard || !fromPos || !toPos) continue;

        const firstEdge = bundle.edges[0];
        const btnEl = Array.from(fromCard.querySelectorAll(".tg-btn")).find(b =>
          (firstEdge.callback_data && b.dataset.callbackData === firstEdge.callback_data) ||
          (firstEdge.button_text && b.dataset.btnText === firstEdge.button_text)
        );

        let strokeColor = "#38bdf8";
        let markerId = "url(#arrow-default)";

        if (bundle.status === "dead_end") {{
          strokeColor = "#ef4444";
          markerId = "url(#arrow-dead)";
        }} else if (bundle.is_back) {{
          strokeColor = "#64748b";
          markerId = "url(#arrow-back)";
        }} else if (btnEl) {{
          if (btnEl.classList.contains("style-success")) {{ strokeColor = "#31b545"; markerId = "url(#arrow-green)"; }}
          else if (btnEl.classList.contains("style-danger")) {{ strokeColor = "#df3f40"; markerId = "url(#arrow-red)"; }}
          else if (btnEl.classList.contains("style-primary")) {{ strokeColor = "#2ea6ff"; markerId = "url(#arrow-blue)"; }}
        }}

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

        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        let d, midX, midY;

        if (bundle.is_back || toY <= fromY) {{
          const loop = 70;
          d = `M ${{fromX}} ${{fromY}} C ${{fromX + loop}} ${{fromY}}, ${{toX - loop}} ${{toY - 40}}, ${{toX}} ${{toY}}`;
          midX = (fromX + toX) / 2 + loop / 2;
          midY = (fromY + toY) / 2 - 20;
        }} else {{
          const dy = Math.max(30, (toY - fromY) * 0.5);
          d = `M ${{fromX}} ${{fromY}} C ${{fromX + 40}} ${{fromY + dy}}, ${{toX}} ${{toY - dy}}, ${{toX}} ${{toY}}`;
          midX = (fromX + toX) / 2;
          midY = (fromY + toY) / 2;
        }}

        path.setAttribute("d", d);
        let cls = "flow-edge";
        if (bundle.status === "dead_end") cls += " dead";
        if (bundle.is_back) cls += " back";

        path.setAttribute("class", cls);
        path.setAttribute("stroke", strokeColor);
        path.setAttribute("stroke-width", bundle.edges.length > 1 ? "3.6" : "2.6");
        path.setAttribute("fill", "none");
        path.setAttribute("marker-end", markerId);
        path.dataset.from = bundle.from_node_id;
        path.dataset.to = bundle.to_node_id;
        path.dataset.btn = firstEdge.button_text;
        path.dataset.buttonList = JSON.stringify(bundle.edges.map(e => e.button_text));

        edgesGroup.appendChild(path);
        renderedEdgePaths.push(path);

        // Edge Floating Label Pill
        if (showLabels && !bundle.is_back) {{
          const pill = document.createElement("div");
          pill.className = "edge-label-pill";
          pill.style.left = `${{midX}}px`;
          pill.style.top = `${{midY}}px`;
          pill.style.borderColor = strokeColor;

          if (bundle.edges.length > 1) {{
            const targetTitle = (rawData.nodes[bundle.to_node_id] ? rawData.nodes[bundle.to_node_id].title : bundle.to_node_id.replace(/^cb:/, ''));
            pill.innerHTML = `<span style="color:${{strokeColor}}; font-weight:700;">×${{bundle.edges.length}} кнопок</span> <code>${{targetTitle}}</code>`;
          }} else {{
            pill.innerHTML = `<span style="color:${{strokeColor}}">${{firstEdge.button_text}}</span> <code>${{firstEdge.callback_data}}</code>`;
          }}

          pill.addEventListener("mouseenter", () => highlightEdgeBranch(bundle.from_node_id, firstEdge.button_text));
          pill.addEventListener("mouseleave", () => resetEdgeHighlights());
          pill.addEventListener("click", () => {{
            pulseEdgeBranch(bundle.from_node_id, bundle.to_node_id, firstEdge.button_text);
            focusOnCard(bundle.to_node_id, 700);
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

    function showTempTargetArrow(fromId, btnText) {{
      removeTempTargetArrow();
      const edge = rawData.edges.find(e => 
        e.from_node_id === fromId && 
        (e.button_text === btnText || (btnText && btnText.includes(e.button_text)))
      );
      if (!edge || !edge.to_node_id) return;
      const fromPos = nodePositions.get(edge.from_node_id);
      const toPos = nodePositions.get(edge.to_node_id);
      if (!fromPos || !toPos) return;

      const isUtil = UTILITY_TARGETS.has(edge.to_node_id);
      const isRet = isReturnOrCross(edge, fromPos, toPos);

      // Only draw dynamic arrow if the edge is hidden on canvas
      if (!isUtil && !isRet && !edge.is_back) return;
      if (isRet && showBackEdges) return; // already visible on canvas

      const fromCard = nodeElements.get(edge.from_node_id);
      const toCard = nodeElements.get(edge.to_node_id);
      if (!fromCard || !toCard) return;

      let fromX = fromPos.x + CARD_W / 2;
      let fromY = fromPos.y + (fromCard.offsetHeight || CARD_H);
      const btnEl = Array.from(fromCard.querySelectorAll(".tg-btn")).find(b => b.dataset.btnText === btnText);
      if (btnEl) {{
        const bRect = btnEl.getBoundingClientRect();
        const cRect = fromCard.getBoundingClientRect();
        if (bRect.width > 0 && scale > 0) {{
          fromX = fromPos.x + (bRect.right - cRect.left) / scale;
          fromY = fromPos.y + ((bRect.top + bRect.bottom) / 2 - cRect.top) / scale;
        }}
      }}

      const toX = toPos.x + CARD_W / 2;
      const toY = toPos.y;

      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      let d;
      if (toY <= fromY) {{
        const loop = 80;
        d = `M ${{fromX}} ${{fromY}} C ${{fromX - loop}} ${{fromY - 50}}, ${{toX + loop}} ${{toY + 50}}, ${{toX}} ${{toY}}`;
      }} else {{
        const dy = Math.max(30, (toY - fromY) * 0.5);
        d = `M ${{fromX}} ${{fromY}} C ${{fromX + 40}} ${{fromY + dy}}, ${{toX}} ${{toY - dy}}, ${{toX}} ${{toY}}`;
      }}

      path.setAttribute("d", d);
      path.setAttribute("class", "flow-edge back highlighted edge-pulse");
      path.setAttribute("stroke", isUtil ? "#ef4444" : "#94a3b8");
      path.setAttribute("stroke-width", "3.6");
      path.setAttribute("stroke-dasharray", "6, 4");
      path.setAttribute("fill", "none");
      path.setAttribute("marker-end", isUtil ? "url(#arrow-dead)" : "url(#arrow-back)");
      
      const edgesGroup = document.getElementById("edges-group");
      if (edgesGroup) {{
        edgesGroup.appendChild(path);
        tempReturnPath = path;
      }}
      toCard.classList.add("highlighted");
    }}

    function removeTempTargetArrow() {{
      if (tempReturnPath && tempReturnPath.parentNode) {{
        tempReturnPath.parentNode.removeChild(tempReturnPath);
        tempReturnPath = null;
      }}
    }}
    const removeTempReturnArrow = removeTempTargetArrow;

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
        let match = false;
        if (p.dataset.from === fromId) {{
          if (p.dataset.btn === btnText) match = true;
          else if (p.dataset.buttonList && p.dataset.buttonList.includes(btnText)) match = true;
        }}
        if (match) {{
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

    // Toggle Back Edges
    document.getElementById("btn-back-edges").addEventListener("click", function() {{
      showBackEdges = !showBackEdges;
      this.classList.toggle("active", showBackEdges);
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
      const worldW = maxX - minX + 240;
      const worldH = maxY - minY + 240;
      const targetScale = Math.min(1.0, Math.max(0.015, Math.min(window.innerWidth / worldW, window.innerHeight / worldH)));
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
