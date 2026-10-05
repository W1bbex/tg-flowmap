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

    /* Type Filter Bar */
    .type-filter-group {{
      display: flex;
      align-items: center;
      gap: 5px;
      background: rgba(15, 23, 42, 0.65);
      padding: 3px 6px;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.08);
    }}
    .filter-chip {{
      background: transparent;
      border: 1px solid transparent;
      color: #94a3b8;
      padding: 4px 9px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 5px;
      transition: all 0.15s ease;
      user-select: none;
    }}
    .filter-chip:hover {{
      background: rgba(255, 255, 255, 0.08);
      color: #f1f5f9;
    }}
    .filter-chip.active {{
      background: #1e293b;
      color: #fff;
      border-color: rgba(255, 255, 255, 0.15);
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
    }}
    .filter-chip .chip-dot {{
      width: 7px;
      height: 7px;
      border-radius: 50%;
    }}
    .chip-dot.dot-all {{ background: #94a3b8; }}
    .chip-dot.dot-command {{ background: #38bdf8; box-shadow: 0 0 6px #38bdf8; }}
    .chip-dot.dot-message {{ background: #818cf8; box-shadow: 0 0 6px #818cf8; }}
    .chip-dot.dot-callback {{ background: #fbbf24; box-shadow: 0 0 6px #fbbf24; }}
    .chip-dot.dot-popup {{ background: #fb7185; box-shadow: 0 0 6px #fb7185; }}

    .chip-count {{
      font-size: 10px;
      padding: 1px 5px;
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.1);
      color: #cbd5e1;
      font-family: monospace;
    }}
    .filter-chip.active .chip-count {{
      background: rgba(255, 255, 255, 0.22);
      color: #fff;
    }}

    .search-box {{
      background: rgba(9, 13, 22, 0.7);
      border: 1px solid #334155;
      border-radius: 6px;
      padding: 6px 12px;
      color: #fff;
      font-size: 13px;
      width: 200px;
      outline: none;
      transition: border-color 0.15s, width 0.2s;
    }}
    .search-box:focus {{ border-color: var(--accent); width: 240px; }}

    .btn-tool {{
      background: #1e293b;
      border: 1px solid #334155;
      color: #cbd5e1;
      padding: 6px 11px;
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
      contain: layout style;
      transition: border-color 0.15s, box-shadow 0.15s, opacity 0.15s;
    }}
    /* Card Type Distinct Borders, Backgrounds and Shadows */
    .tg-card.card-type-command {{
      border: 1.5px solid rgba(56, 189, 248, 0.65);
      background: linear-gradient(180deg, #0b172a 0%, #070d18 100%);
      box-shadow: 0 4px 20px rgba(14, 165, 233, 0.15), var(--card-shadow);
    }}
    .tg-card.card-type-message {{
      border: 1.5px solid rgba(129, 140, 248, 0.5);
      background: linear-gradient(180deg, #13192f 0%, #0d1322 100%);
      box-shadow: 0 4px 20px rgba(99, 102, 241, 0.12), var(--card-shadow);
    }}
    .tg-card.card-type-callback {{
      border: 1.5px solid rgba(245, 158, 11, 0.55);
      background: linear-gradient(180deg, #1c150c 0%, #0e121a 100%);
      box-shadow: 0 4px 20px rgba(245, 158, 11, 0.12), var(--card-shadow);
    }}
    .tg-card.card-type-popup {{
      border: 1.5px dashed rgba(244, 63, 94, 0.75);
      background: linear-gradient(180deg, #220f16 0%, #0e111a 100%);
      box-shadow: 0 4px 20px rgba(244, 63, 94, 0.15), var(--card-shadow);
    }}

    /* VIP Cards */
    .tg-card.is-root-start {{
      border: 2.5px solid #eab308 !important;
      box-shadow: 0 0 35px rgba(234, 179, 8, 0.45), var(--card-shadow) !important;
    }}
    .tg-card.is-hub-menu {{
      border: 2.5px solid #10b981 !important;
      box-shadow: 0 0 40px rgba(16, 185, 129, 0.45), var(--card-shadow) !important;
    }}
    .tg-card.is-utility-card {{
      border: 1.5px dashed rgba(244, 63, 94, 0.65);
    }}

    /* Badges */
    .badge-type {{
      font-size: 10px;
      padding: 1px 6px;
      border-radius: 4px;
      font-weight: 700;
      white-space: nowrap;
      text-transform: uppercase;
      letter-spacing: 0.3px;
      display: inline-flex;
      align-items: center;
      gap: 3px;
    }}
    .badge-type-command {{
      color: #38bdf8;
      background: rgba(56, 189, 248, 0.15);
      border: 1px solid rgba(56, 189, 248, 0.35);
    }}
    .badge-type-message {{
      color: #a5b4fc;
      background: rgba(129, 140, 248, 0.15);
      border: 1px solid rgba(129, 140, 248, 0.35);
    }}
    .badge-type-callback {{
      color: #fbbf24;
      background: rgba(245, 158, 11, 0.15);
      border: 1px solid rgba(245, 158, 11, 0.35);
    }}
    .badge-type-popup {{
      color: #fb7185;
      background: rgba(244, 63, 94, 0.15);
      border: 1px solid rgba(244, 63, 94, 0.35);
    }}
    .badge-type-entry {{
      color: #fde047;
      background: rgba(234, 179, 8, 0.2);
      border: 1px solid rgba(234, 179, 8, 0.5);
    }}
    .badge-type-hub {{
      color: #34d399;
      background: rgba(16, 185, 129, 0.2);
      border: 1px solid rgba(16, 185, 129, 0.5);
    }}
    .orphan-badge {{
      font-size: 10px;
      color: #94a3b8;
      background: rgba(148, 163, 184, 0.12);
      border: 1px solid rgba(148, 163, 184, 0.25);
      padding: 1px 5px;
      border-radius: 4px;
      font-weight: 600;
      white-space: nowrap;
    }}

    /* Inner Custom Boxes for Types */
    .popup-modal-mockup {{
      padding: 12px 14px;
      display: flex;
      gap: 10px;
      align-items: flex-start;
      background: rgba(244, 63, 94, 0.08);
      border-radius: 8px;
      margin: 10px 12px 6px 12px;
      border: 1px solid rgba(244, 63, 94, 0.2);
    }}
    .popup-modal-icon {{ font-size: 20px; line-height: 1; }}
    .popup-modal-content {{ flex: 1; }}
    .popup-modal-title {{
      font-size: 11px;
      font-weight: 700;
      color: #fca5a5;
      margin-bottom: 3px;
      text-transform: uppercase;
    }}
    .popup-modal-text {{
      font-size: 12px;
      color: #f1f5f9;
      line-height: 1.4;
    }}
    .popup-modal-footer {{
      padding: 4px 12px 12px 12px;
      display: flex;
      justify-content: flex-end;
    }}
    .popup-modal-btn {{
      padding: 5px 16px;
      border-radius: 6px;
      background: rgba(244, 63, 94, 0.2);
      border: 1px solid rgba(244, 63, 94, 0.4);
      color: #fecdd3;
      font-size: 11px;
      font-weight: 700;
      text-align: center;
      cursor: default;
    }}

    .callback-action-box {{
      margin: 10px 12px 12px 12px;
      padding: 10px 12px;
      border-radius: 8px;
      background: rgba(245, 158, 11, 0.08);
      border: 1px solid rgba(245, 158, 11, 0.25);
    }}
    .callback-action-header {{
      font-size: 11px;
      font-weight: 700;
      color: #fde68a;
      margin-bottom: 4px;
    }}
    .callback-action-header code {{
      font-size: 11px;
      color: #fbbf24;
      background: rgba(0, 0, 0, 0.3);
      padding: 1px 4px;
      border-radius: 3px;
    }}
    .callback-action-text {{
      font-size: 12px;
      color: #cbd5e1;
      line-height: 1.4;
    }}

    .command-box {{
      margin: 10px 12px 12px 12px;
      padding: 10px 12px;
      border-radius: 8px;
      background: rgba(56, 189, 248, 0.08);
      border: 1px solid rgba(56, 189, 248, 0.25);
    }}
    .command-box-prompt {{
      margin-bottom: 4px;
    }}
    .command-box-prompt code {{
      font-size: 13px;
      font-weight: 700;
      color: #38bdf8;
      background: rgba(0, 0, 0, 0.3);
      padding: 2px 6px;
      border-radius: 4px;
    }}
    .command-box-text {{
      font-size: 12px;
      color: #cbd5e1;
      line-height: 1.4;
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

    .tg-card.highlighted, .tg-card.type-highlighted {{
      border-color: var(--accent) !important;
      box-shadow: 0 0 0 2px var(--accent), 0 10px 30px rgba(56, 189, 248, 0.4) !important;
      z-index: 50;
    }}
    .tg-card.dimmed {{
      opacity: 0.15 !important;
      filter: grayscale(60%);
      pointer-events: none;
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

    /* Connection Ports on Outer Card Boundary */
    .card-edge-port {{
      position: absolute;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--accent);
      border: 1.5px solid #fff;
      box-shadow: 0 0 10px currentColor;
      pointer-events: none;
      z-index: 30;
      transition: transform 0.15s, box-shadow 0.15s;
    }}
    .card-edge-port.port-left {{
      left: -5px;
      transform: translateY(-50%);
    }}
    .card-edge-port.port-right {{
      right: -5px;
      transform: translateY(-50%);
    }}
    .card-edge-port.port-down {{
      bottom: -5px;
      left: 50%;
      transform: translateX(-50%);
    }}
    .card-top-port {{
      position: absolute;
      top: -5px;
      left: 50%;
      transform: translateX(-50%);
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #38bdf8;
      border: 1.5px solid #fff;
      box-shadow: 0 0 10px currentColor;
      pointer-events: none;
      z-index: 30;
    }}

    /* Canvas Zones (Commands, Popups, Handlers) */
    .canvas-zone {{
      position: absolute;
      border-radius: 18px;
      pointer-events: none;
      transition: opacity 0.2s;
    }}
    .canvas-zone.zone-commands {{
      border: 2px dashed rgba(56, 189, 248, 0.4);
      background: rgba(14, 165, 233, 0.04);
    }}
    .canvas-zone.zone-popups {{
      border: 2px dashed rgba(244, 63, 94, 0.4);
      background: rgba(244, 63, 94, 0.04);
    }}
    .canvas-zone.zone-handlers {{
      border: 2px dashed rgba(148, 163, 184, 0.3);
      background: rgba(15, 23, 42, 0.35);
    }}
    .canvas-zone-header {{
      position: absolute;
      top: -36px;
      left: 16px;
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      font-weight: 700;
      color: #cbd5e1;
      white-space: nowrap;
    }}
    .canvas-zone-header .zone-icon {{
      font-size: 14px;
    }}
    .canvas-zone-header .zone-sub {{
      font-size: 11px;
      font-weight: 500;
      color: #64748b;
    }}
    .hide-orphans .is-orphan-card,
    .hide-orphans .canvas-zone {{
      display: none !important;
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
    <div class="type-filter-group" id="type-filters">
      <button class="filter-chip active" data-type="all">
        <span class="chip-dot dot-all"></span> Все <span class="chip-count" id="count-all">0</span>
      </button>
      <button class="filter-chip" data-type="command">
        <span class="chip-dot dot-command"></span> ⚡ Команды <span class="chip-count" id="count-command">0</span>
      </button>
      <button class="filter-chip" data-type="message">
        <span class="chip-dot dot-message"></span> 💬 Экраны <span class="chip-count" id="count-message">0</span>
      </button>
      <button class="filter-chip" data-type="callback">
        <span class="chip-dot dot-callback"></span> 🔘 Действия <span class="chip-count" id="count-callback">0</span>
      </button>
      <button class="filter-chip" data-type="popup">
        <span class="chip-dot dot-popup"></span> 🔔 Всплывающие <span class="chip-count" id="count-popup">0</span>
      </button>
    </div>
    <div class="toolbar-actions">
      <input type="text" id="search-input" class="search-box" placeholder="Поиск кнопки или экрана..." />
      <button class="btn-tool" id="btn-back-edges" title="Показать / скрыть обратные стрелки «Назад» и «В меню»">↩ Возвраты</button>
      <button class="btn-tool active" id="btn-labels" title="Включить / скрыть подписи на стрелочках">🏷️ Подписи</button>
      <button class="btn-tool active" id="btn-orphans" title="Показать или скрыть несвязанные экраны и обработчики">📦 Дополнительные</button>
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

    if (isStartHubPair) {{
      forwardEdgesMap.set(rootId, [hubId]);
    }}

    function getChildCategory(parentId, childId) {{
      const node = rawData.nodes[parentId];
      if (!node || !node.keyboard || !node.keyboard.rows) return "left";
      const numRows = node.keyboard.rows.length;
      for (let r = 0; r < numRows; r++) {{
        const row = node.keyboard.rows[r];
        for (let c = 0; c < row.length; c++) {{
          const btn = row[c];
          const match = rawData.edges.some(e =>
            e.from_node_id === parentId &&
            e.to_node_id === childId &&
            ((btn.callback_data && e.callback_data === btn.callback_data) || e.button_text === btn.text)
          );
          if (match) {{
            if (row.length > 2) {{
              if (c === 0) return "left";
              if (c === row.length - 1) return "right";
              return "bottom";
            }} else if (row.length === 2) {{
              return c === 0 ? "left" : "right";
            }} else {{
              // Full-width (row.length === 1):
              // If bottom row (or in lower half of rows): goes bottom/center!
              if (r === numRows - 1 || r >= Math.ceil(numRows / 2)) {{
                return "bottom";
              }} else {{
                return "left";
              }}
            }}
          }}
        }}
      }}
      return "left";
    }}

    // Sort children so "left" comes first, "bottom" comes second, "right" comes third
    const CATEGORY_ORDER = {{ left: 0, bottom: 1, right: 2 }};
    for (const [id, kids] of forwardEdgesMap.entries()) {{
      const node = rawData.nodes[id];
      if (node && node.keyboard && node.keyboard.rows && node.keyboard.rows.some(r => r.length > 1)) {{
        kids.sort((a, b) => {{
          const catA = CATEGORY_ORDER[getChildCategory(id, a)] ?? 0;
          const catB = CATEGORY_ORDER[getChildCategory(id, b)] ?? 0;
          return catA - catB;
        }});
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

    // Explore main bot tree
    exploreBfsTree(rootId);
    if (!visitedNodes.has(hubId)) exploreBfsTree(hubId);

    // Classification helper for the 4 core types
    function getNodeType(nodeId, node) {{
      if (node && node.node_type) return node.node_type;
      if (nodeId.startsWith("cmd:") || (node && node.trigger_type === "command")) return "command";
      if (UTILITY_TARGETS.has(nodeId) || (node && node.is_alert)) return "popup";
      if (node && node.keyboard && node.keyboard.rows && node.keyboard.rows.length > 0) return "message";
      return "callback";
    }}

    // 3. Exact Subtree Width on the Spanning Tree with Trifurcation Support (Left / Bottom-Center / Right)
    function computeSubtreeWidth(nodeId) {{
      const children = treeChildren.get(nodeId) || [];
      if (children.length === 0) return CARD_W;

      const isHub = (nodeId === hubId);
      if (isHub) {{
        const leftKids = children.filter(c => getChildCategory(nodeId, c) === "left");
        const bottomKids = children.filter(c => getChildCategory(nodeId, c) === "bottom");
        const rightKids = children.filter(c => getChildCategory(nodeId, c) === "right");

        if (leftKids.length > 0 || rightKids.length > 0 || bottomKids.length > 0) {{
          let leftW = 0;
          for (let i = 0; i < leftKids.length; i++) {{
            if (i > 0) leftW += SIBLING_GAP_X;
            leftW += computeSubtreeWidth(leftKids[i]);
          }}

          let bottomW = 0;
          for (let i = 0; i < bottomKids.length; i++) {{
            if (i > 0) bottomW += SIBLING_GAP_X;
            bottomW += computeSubtreeWidth(bottomKids[i]);
          }}

          let rightW = 0;
          for (let i = 0; i < rightKids.length; i++) {{
            if (i > 0) rightW += SIBLING_GAP_X;
            rightW += computeSubtreeWidth(rightKids[i]);
          }}

          const centerBlockW = Math.max(CARD_W, bottomW);
          const gapLeft = (leftW > 0) ? Math.max(SIBLING_GAP_X, 80) : 0;
          const gapRight = (rightW > 0) ? Math.max(SIBLING_GAP_X, 80) : 0;

          return leftW + gapLeft + centerBlockW + gapRight + rightW;
        }}
      }}

      let totalW = 0;
      for (let i = 0; i < children.length; i++) {{
        if (i > 0) totalW += SIBLING_GAP_X;
        totalW += computeSubtreeWidth(children[i]);
      }}
      return Math.max(CARD_W, totalW);
    }}

    function shiftSubtree(nodeId, dx) {{
      if (dx === 0) return;
      const pos = nodePositions.get(nodeId);
      if (pos) pos.x += dx;
      const kids = treeChildren.get(nodeId) || [];
      for (const kid of kids) shiftSubtree(kid, dx);
    }}

    function placeTreeNode(nodeId, leftX, levelY) {{
      const children = treeChildren.get(nodeId) || [];
      const isHub = (nodeId === hubId);

      if (isHub) {{
        const leftKids = children.filter(c => getChildCategory(nodeId, c) === "left");
        const bottomKids = children.filter(c => getChildCategory(nodeId, c) === "bottom");
        const rightKids = children.filter(c => getChildCategory(nodeId, c) === "right");

        if (leftKids.length > 0 || rightKids.length > 0 || bottomKids.length > 0) {{
          let leftW = 0;
          for (let i = 0; i < leftKids.length; i++) {{
            if (i > 0) leftW += SIBLING_GAP_X;
            leftW += computeSubtreeWidth(leftKids[i]);
          }}

          let bottomW = 0;
          for (let i = 0; i < bottomKids.length; i++) {{
            if (i > 0) bottomW += SIBLING_GAP_X;
            bottomW += computeSubtreeWidth(bottomKids[i]);
          }}

          let rightW = 0;
          for (let i = 0; i < rightKids.length; i++) {{
            if (i > 0) rightW += SIBLING_GAP_X;
            rightW += computeSubtreeWidth(rightKids[i]);
          }}

          const centerBlockW = Math.max(CARD_W, bottomW);
          const gapLeft = (leftW > 0) ? Math.max(SIBLING_GAP_X, 80) : 0;
          const gapRight = (rightW > 0) ? Math.max(SIBLING_GAP_X, 80) : 0;

          const centerBlockX = leftX + (leftW > 0 ? leftW + gapLeft : 0);
          const myX = centerBlockX + (centerBlockW - CARD_W) / 2;
          nodePositions.set(nodeId, {{ x: myX, y: levelY }});

          // 1. Place leftKids
          let childLeftX = leftX;
          for (const childId of leftKids) {{
            const childW = computeSubtreeWidth(childId);
            placeTreeNode(childId, childLeftX, levelY + CARD_H + LEVEL_GAP_Y);
            childLeftX += childW + SIBLING_GAP_X;
          }}

          // 2. Place bottomKids (centered directly under parent card!)
          let childBottomX = centerBlockX + (centerBlockW - bottomW) / 2;
          for (const childId of bottomKids) {{
            const childW = computeSubtreeWidth(childId);
            placeTreeNode(childId, childBottomX, levelY + CARD_H + LEVEL_GAP_Y);
            childBottomX += childW + SIBLING_GAP_X;
          }}

          // If single bottom kid, align its card center directly under parent card center!
          if (bottomKids.length === 1) {{
            const bKid = bottomKids[0];
            const bPos = nodePositions.get(bKid);
            if (bPos) shiftSubtree(bKid, myX - bPos.x);
          }}

          // 3. Place rightKids
          let childRightX = centerBlockX + centerBlockW + gapRight;
          for (const childId of rightKids) {{
            const childW = computeSubtreeWidth(childId);
            placeTreeNode(childId, childRightX, levelY + CARD_H + LEVEL_GAP_Y);
            childRightX += childW + SIBLING_GAP_X;
          }}
          return;
        }}
      }}

      const subtreeW = computeSubtreeWidth(nodeId);
      const myX = leftX + (subtreeW - CARD_W) / 2;
      nodePositions.set(nodeId, {{ x: myX, y: levelY }});

      let childLeftX = leftX;
      for (const childId of children) {{
        const childW = computeSubtreeWidth(childId);
        placeTreeNode(childId, childLeftX, levelY + CARD_H + LEVEL_GAP_Y);
        childLeftX += childW + SIBLING_GAP_X;
      }}
    }}

    // 4. Place Main Tree
    placeTreeNode(rootId, 0, 0);
    if (isStartHubPair && nodePositions.has(rootId) && nodePositions.has(hubId)) {{
      nodePositions.get(rootId).x = nodePositions.get(hubId).x;
    }}

    const mainTreeWidth = computeSubtreeWidth(rootId);

    // 5. Place Secondary Commands in a Compact 3-Column Deck
    const secondaryCmds = Object.keys(rawData.nodes).filter(k => k.startsWith("cmd:") && !nodePositions.has(k));
    let cmdBox = null;
    let maxCmdX = mainTreeWidth + 120;
    let maxCmdY = 0;
    if (secondaryCmds.length > 0) {{
      const cmdCols = 3;
      const cmdStartX = mainTreeWidth + 120;
      secondaryCmds.forEach((id, idx) => {{
        const c = idx % cmdCols;
        const r = Math.floor(idx / cmdCols);
        const gx = cmdStartX + c * (CARD_W + 50);
        const gy = r * (CARD_H + 50);
        nodePositions.set(id, {{ x: gx, y: gy }});
        maxCmdX = Math.max(maxCmdX, gx + CARD_W);
        maxCmdY = Math.max(maxCmdY, gy + CARD_H);
      }});
      cmdBox = {{
        x: cmdStartX - 20,
        y: -10,
        w: maxCmdX - cmdStartX + 40,
        h: maxCmdY + 50,
        count: secondaryCmds.length,
      }};
    }}

    // 6. Place Utility / Popups in a Compact 2-Column Deck
    const utilNodesList = Object.keys(rawData.nodes).filter(k => UTILITY_TARGETS.has(k) && !nodePositions.has(k));
    let utilBox = null;
    let maxUtilX = maxCmdX + 70;
    let maxUtilY = 0;
    if (utilNodesList.length > 0) {{
      const utilCols = 2;
      const utilStartX = maxCmdX + 70;
      utilNodesList.forEach((id, idx) => {{
        const c = idx % utilCols;
        const r = Math.floor(idx / utilCols);
        const gx = utilStartX + c * (CARD_W + 50);
        const gy = r * (CARD_H + 50);
        nodePositions.set(id, {{ x: gx, y: gy }});
        maxUtilX = Math.max(maxUtilX, gx + CARD_W);
        maxUtilY = Math.max(maxUtilY, gy + CARD_H);
      }});
      utilBox = {{
        x: utilStartX - 20,
        y: -10,
        w: maxUtilX - utilStartX + 40,
        h: maxUtilY + 50,
        count: utilNodesList.length,
      }};
    }}

    // 7. Place Remaining Handlers in a Compact 4-Column Deck below
    const unvisited = Object.keys(rawData.nodes).filter(k => !nodePositions.has(k));
    let remBox = null;
    if (unvisited.length > 0) {{
      const remCols = 4;
      const remStartX = mainTreeWidth + 120;
      const remStartY = Math.max(maxCmdY, maxUtilY) + 100;
      let maxRemX = remStartX;
      let maxRemY = remStartY;
      unvisited.forEach((id, idx) => {{
        const c = idx % remCols;
        const r = Math.floor(idx / remCols);
        const gx = remStartX + c * (CARD_W + 50);
        const gy = remStartY + r * (CARD_H + 50);
        nodePositions.set(id, {{ x: gx, y: gy }});
        maxRemX = Math.max(maxRemX, gx + CARD_W);
        maxRemY = Math.max(maxRemY, gy + CARD_H);
      }});
      remBox = {{
        x: remStartX - 20,
        y: remStartY - 40,
        w: maxRemX - remStartX + 40,
        h: maxRemY - remStartY + 80,
        count: unvisited.length,
      }};
    }}

    // Render Canvas Zone Boxes
    if (cmdBox) {{
      const z = document.createElement("div");
      z.className = "canvas-zone zone-commands";
      z.style.left = `${{cmdBox.x}}px`;
      z.style.top = `${{cmdBox.y}}px`;
      z.style.width = `${{cmdBox.w}}px`;
      z.style.height = `${{cmdBox.h}}px`;
      z.innerHTML = `
        <div class="canvas-zone-header">
          <span class="zone-icon">⚡</span>
          <span>Слэш-команды Telegram (${{cmdBox.count}})</span>
          <span class="zone-sub">// вводятся в чат через /</span>
        </div>
      `;
      nodesContainer.appendChild(z);
    }}

    if (utilBox) {{
      const z = document.createElement("div");
      z.className = "canvas-zone zone-popups";
      z.style.left = `${{utilBox.x}}px`;
      z.style.top = `${{utilBox.y}}px`;
      z.style.width = `${{utilBox.w}}px`;
      z.style.height = `${{utilBox.h}}px`;
      z.innerHTML = `
        <div class="canvas-zone-header">
          <span class="zone-icon">🔔</span>
          <span>Всплывающие окна и диалоги (${{utilBox.count}})</span>
          <span class="zone-sub">// answerCallbackQuery</span>
        </div>
      `;
      nodesContainer.appendChild(z);
    }}

    if (remBox) {{
      const z = document.createElement("div");
      z.className = "canvas-zone zone-handlers";
      z.style.left = `${{remBox.x}}px`;
      z.style.top = `${{remBox.y}}px`;
      z.style.width = `${{remBox.w}}px`;
      z.style.height = `${{remBox.h}}px`;
      z.innerHTML = `
        <div class="canvas-zone-header">
          <span class="zone-icon">📦</span>
          <span>Дополнительные сценарии и обработчики (${{remBox.count}})</span>
          <span class="zone-sub">// вспомогательные действия и подсистемы</span>
        </div>
      `;
      nodesContainer.appendChild(z);
    }}

    for (const [nodeId, node] of Object.entries(rawData.nodes)) {{
      createCard(nodeId, node);
    }}

    function createCard(nodeId, node) {{
      const pos = nodePositions.get(nodeId) || {{ x: 0, y: 0 }};
      const card = document.createElement("div");
      card.className = "tg-card";
      const nodeType = getNodeType(nodeId, node);
      card.dataset.nodeType = nodeType;
      card.classList.add(`card-type-${{nodeType}}`);


      if (nodeId === "cmd:/start") card.classList.add("is-root-start");
      if (nodeId === "cb:menu") card.classList.add("is-hub-menu");
      if (nodeType === "popup") card.classList.add("is-utility-card");
      if (unvisited.includes(nodeId)) card.classList.add("is-orphan-card");
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
      const srcName = node.source_file ? node.source_file.split(/[/\\\\]/).pop() : "";
      const lineStr = node.line_number ? `:${{node.line_number}}` : "";

      let icon = "💬";
      let badgeHtml = "";
      if (nodeId === "cmd:/start") {{
        icon = "⭐";
        badgeHtml = `<span class="badge-type badge-type-entry">⭐ Вход</span>`;
      }} else if (nodeId === "cb:menu") {{
        icon = "🏠";
        badgeHtml = `<span class="badge-type badge-type-hub">🏠 Меню</span>`;
      }} else if (nodeType === "command") {{
        icon = "⚡";
        badgeHtml = `<span class="badge-type badge-type-command">⚡ Команда</span>`;
      }} else if (nodeType === "popup") {{
        icon = "🔔";
        badgeHtml = `<span class="badge-type badge-type-popup">🔔 Всплывающее</span>`;
      }} else if (nodeType === "callback") {{
        icon = "🔘";
        badgeHtml = `<span class="badge-type badge-type-callback">🔘 Действие</span>`;
      }} else {{
        icon = "💬";
        badgeHtml = `<span class="badge-type badge-type-message">💬 Экран</span>`;
      }}

      const displayTitle = nodeType === "command" ? (nodeId.startsWith("cmd:/") ? nodeId.slice(4) : "/" + nodeId.slice(4)) : node.title;

      header.innerHTML = `
        <div class="card-title-group">
          <span style="font-size:13px;">${{icon}}</span>
          <span class="card-screen-title" title="${{displayTitle}}">${{displayTitle}}</span>
          ${{badgeHtml}}
        </div>
        <div class="card-meta">${{srcName}}${{lineStr}}</div>
      `;
      card.appendChild(header);

      // Message Body / Custom Box Mockup
      const isStartHub = (isStartHubPair && nodeId === rootId);
      if (isStartHub) {{
        const body = document.createElement("div");
        body.className = "tg-card-body";
        body.innerHTML = node.text_template || "<i>(Точка входа)</i>";
        card.appendChild(body);

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
      }} else if (nodeType === "popup") {{
        const body = document.createElement("div");
        body.className = "tg-card-body";
        body.innerHTML = `
          <div class="popup-modal-mockup">
            <div class="popup-modal-icon">🔔</div>
            <div class="popup-modal-content">
              <div class="popup-modal-title">Всплывающее окно</div>
              <div class="popup-modal-text">${{node.text_template || "Уведомление answerCallbackQuery"}}</div>
            </div>
          </div>
          <div class="popup-modal-footer">
            <div class="popup-modal-btn">OK</div>
          </div>
        `;
        card.appendChild(body);
      }} else if (nodeType === "command") {{
        const body = document.createElement("div");
        body.className = "tg-card-body";
        const cmdName = nodeId.startsWith("cmd:/") ? nodeId.slice(5) : nodeId.slice(4);
        body.innerHTML = `
          <div class="command-box">
            <div class="command-box-prompt"><code>/${{cmdName}}</code></div>
            <div class="command-box-text">${{node.text_template || "Команда Telegram-чата"}}</div>
          </div>
        `;
        card.appendChild(body);
      }} else if (nodeType === "callback" && (!node.keyboard || !node.keyboard.rows || !node.keyboard.rows.length)) {{
        const body = document.createElement("div");
        body.className = "tg-card-body";
        const cbName = nodeId.replace(/^cb:/, '');
        body.innerHTML = `
          <div class="callback-action-box">
            <div class="callback-action-header">🔘 Действие: <code>${{cbName}}</code></div>
            <div class="callback-action-text">${{node.text_template || "Обрабатывает нажатие инлайн-кнопки"}}</div>
          </div>
        `;
        card.appendChild(body);
      }} else {{
        const body = document.createElement("div");
        body.className = "tg-card-body";
        body.innerHTML = node.text_template || "<i>(Пустой текст)</i>";
      }}

      // Keyboard with Colored Buttons
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

            btnEl.innerHTML = `<span>${{iconGlyph ? `${{iconGlyph}} ` : ""}}${{btn.text}}</span>`;

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
      document.querySelectorAll(".card-edge-port").forEach(p => p.remove());

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

        const toX = toPos.x + CARD_W / 2;
        const toY = toPos.y;
        let fromX = fromPos.x + CARD_W / 2;
        let fromY = fromPos.y + (fromCard.offsetHeight || CARD_H);
        let portDirection = "down";

        if (btnEl) {{
          let cur = btnEl;
          let offLeft = 0;
          let offTop = 0;
          while (cur && cur !== fromCard) {{
            offLeft += cur.offsetLeft;
            offTop += cur.offsetTop;
            cur = cur.offsetParent;
          }}
          const bW = btnEl.offsetWidth || 140;
          const bH = btnEl.offsetHeight || 34;
          const btnCenterY = offTop + bH / 2;

          const rowEl = btnEl.closest(".tg-row");
          const rowButtons = rowEl ? Array.from(rowEl.querySelectorAll(".tg-btn")) : [btnEl];
          const btnIdxInRow = rowButtons.indexOf(btnEl);
          const isLeftCol = (rowButtons.length > 1 && btnIdxInRow === 0);
          const isRightCol = (rowButtons.length > 1 && btnIdxInRow === rowButtons.length - 1);

          const toCenterX = toPos.x + CARD_W / 2;
          const fromCardCenterX = fromPos.x + CARD_W / 2;

          if (bundle.is_back || toY <= fromPos.y) {{
            portDirection = "return";
            fromX = fromPos.x + CARD_W;
            fromY = fromPos.y + btnCenterY;
          }} else if (isLeftCol) {{
            portDirection = "left";
            fromX = fromPos.x;
            fromY = fromPos.y + btnCenterY;
          }} else if (isRightCol) {{
            portDirection = "right";
            fromX = fromPos.x + CARD_W;
            fromY = fromPos.y + btnCenterY;
          }} else if (toCenterX < fromCardCenterX - 30) {{
            portDirection = "left";
            fromX = fromPos.x;
            fromY = fromPos.y + btnCenterY;
          }} else if (toCenterX > fromCardCenterX + 30) {{
            portDirection = "right";
            fromX = fromPos.x + CARD_W;
            fromY = fromPos.y + btnCenterY;
          }} else {{
            portDirection = "down";
            fromX = fromPos.x + offLeft + bW / 2;
            fromY = fromPos.y + (fromCard.offsetHeight || CARD_H);
          }}

          let portEl = fromCard.querySelector(`.card-edge-port[data-btn-id="${{btnEl.id}}"]`);
          if (!portEl) {{
            portEl = document.createElement("div");
            portEl.className = `card-edge-port port-${{portDirection}}`;
            portEl.dataset.btnId = btnEl.id;
            portEl.style.color = strokeColor;
            portEl.style.backgroundColor = strokeColor;
            if (portDirection === "left" || portDirection === "right" || portDirection === "return") {{
              portEl.style.top = `${{btnCenterY}}px`;
            }} else if (portDirection === "down") {{
              portEl.style.left = `${{offLeft + bW / 2}}px`;
            }}
            fromCard.appendChild(portEl);
          }}
        }}

        const topPort = toCard.querySelector(".card-top-port");
        if (topPort && !bundle.is_back) {{
          topPort.style.backgroundColor = strokeColor;
          topPort.style.color = strokeColor;
        }}

        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        let d, midX, midY;

        if (portDirection === "return" || bundle.is_back || toY <= fromY) {{
          const loop = Math.max(50, Math.min(120, Math.abs(toX - fromX) * 0.4));
          d = `M ${{fromX}} ${{fromY}} C ${{fromX + loop}} ${{fromY}}, ${{toX - loop}} ${{toY - 50}}, ${{toX}} ${{toY}}`;
          midX = (fromX + toX) / 2 + loop / 2;
          midY = (fromY + toY) / 2 - 25;
        }} else if (portDirection === "left") {{
          const cdx = Math.min(100, Math.max(35, Math.abs(fromX - toX) * 0.35));
          const cdy = Math.max(40, (toY - fromY) * 0.4);
          d = `M ${{fromX}} ${{fromY}} C ${{fromX - cdx}} ${{fromY}}, ${{toX}} ${{toY - cdy}}, ${{toX}} ${{toY}}`;
          midX = (fromX + toX) / 2 - cdx * 0.3;
          midY = (fromY + toY) / 2;
        }} else if (portDirection === "right") {{
          const cdx = Math.min(100, Math.max(35, Math.abs(toX - fromX) * 0.35));
          const cdy = Math.max(40, (toY - fromY) * 0.4);
          d = `M ${{fromX}} ${{fromY}} C ${{fromX + cdx}} ${{fromY}}, ${{toX}} ${{toY - cdy}}, ${{toX}} ${{toY}}`;
          midX = (fromX + toX) / 2 + cdx * 0.3;
          midY = (fromY + toY) / 2;
        }} else {{
          const dy = Math.max(35, (toY - fromY) * 0.5);
          d = `M ${{fromX}} ${{fromY}} C ${{fromX}} ${{fromY + dy}}, ${{toX}} ${{toY - dy}}, ${{toX}} ${{toY}}`;
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

      let portEl = fromCard.querySelector(".card-edge-port.port-down");
      if (!portEl) {{
        portEl = document.createElement("div");
        portEl.className = "card-edge-port port-down";
        portEl.style.color = color;
        portEl.style.backgroundColor = color;
        portEl.style.left = "50%";
        fromCard.appendChild(portEl);
      }}
      const topPort = toCard.querySelector(".card-top-port");
      if (topPort) {{
        topPort.style.backgroundColor = color;
        topPort.style.color = color;
      }}

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
        let cur = btnEl;
        let offLeft = 0;
        let offTop = 0;
        while (cur && cur !== fromCard) {{
          offLeft += cur.offsetLeft;
          offTop += cur.offsetTop;
          cur = cur.offsetParent;
        }}
        const bH = btnEl.offsetHeight || 34;
        const rowEl = btnEl.closest(".tg-row");
        const rowButtons = rowEl ? Array.from(rowEl.querySelectorAll(".tg-btn")) : [btnEl];
        const btnIdxInRow = rowButtons.indexOf(btnEl);
        const isLeftCol = (rowButtons.length > 1 && btnIdxInRow === 0);
        const isRightCol = (rowButtons.length > 1 && btnIdxInRow === rowButtons.length - 1);
        const btnCenterY = offTop + bH / 2;

        if (isLeftCol) {{
          fromX = fromPos.x;
          fromY = fromPos.y + btnCenterY;
        }} else if (isRightCol) {{
          fromX = fromPos.x + CARD_W;
          fromY = fromPos.y + btnCenterY;
        }} else {{
          fromX = fromPos.x + offLeft + (btnEl.offsetWidth || 140) / 2;
          fromY = fromPos.y + (fromCard.offsetHeight || CARD_H);
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

    // Type Filters Engine
    let currentFilterType = "all";
    const filterChips = document.querySelectorAll(".filter-chip");

    // Populate live counts
    const typeCounts = {{ all: Object.keys(rawData.nodes).length, command: 0, message: 0, callback: 0, popup: 0 }};
    for (const [id, node] of Object.entries(rawData.nodes)) {{
      const t = getNodeType(id, node);
      if (typeCounts[t] !== undefined) typeCounts[t]++;
    }}
    const elCountAll = document.getElementById("count-all");
    const elCountCmd = document.getElementById("count-command");
    const elCountMsg = document.getElementById("count-message");
    const elCountCb = document.getElementById("count-callback");
    const elCountPop = document.getElementById("count-popup");

    if (elCountAll) elCountAll.textContent = typeCounts.all;
    if (elCountCmd) elCountCmd.textContent = typeCounts.command;
    if (elCountMsg) elCountMsg.textContent = typeCounts.message;
    if (elCountCb) elCountCb.textContent = typeCounts.callback;
    if (elCountPop) elCountPop.textContent = typeCounts.popup;

    filterChips.forEach(chip => {{
      const type = chip.dataset.type;

      chip.addEventListener("mouseenter", () => {{
        if (type === "all") return;
        document.querySelectorAll(".tg-card").forEach(c => {{
          if (c.dataset.nodeType === type) {{
            c.classList.add("type-highlighted");
            c.classList.remove("dimmed");
          }} else {{
            c.classList.remove("type-highlighted");
            c.classList.add("dimmed");
          }}
        }});
      }});

      chip.addEventListener("mouseleave", () => {{
        if (currentFilterType !== "all") {{
          applyFilter(currentFilterType, false);
        }} else {{
          document.querySelectorAll(".tg-card").forEach(c => {{
            c.classList.remove("type-highlighted", "dimmed");
          }});
        }}
      }});

      chip.addEventListener("click", () => {{
        filterChips.forEach(ch => ch.classList.remove("active"));
        chip.classList.add("active");
        currentFilterType = type;
        applyFilter(type, true);
      }});
    }});

    function applyFilter(type, shouldFly = false) {{
      if (type === "all") {{
        document.querySelectorAll(".tg-card").forEach(c => {{
          c.classList.remove("dimmed", "type-highlighted");
        }});
        if (shouldFly) centerOnStart(600);
        return;
      }}

      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      let matchedCount = 0;

      document.querySelectorAll(".tg-card").forEach(c => {{
        if (c.dataset.nodeType === type) {{
          c.classList.remove("dimmed");
          c.classList.add("type-highlighted");
          matchedCount++;
          const nodeId = c.id.replace(/^card-/, "");
          const pos = nodePositions.get(nodeId);
          if (pos) {{
            minX = Math.min(minX, pos.x);
            minY = Math.min(minY, pos.y);
            maxX = Math.max(maxX, pos.x + CARD_W);
            maxY = Math.max(maxY, pos.y + CARD_H);
          }}
        }} else {{
          c.classList.add("dimmed");
          c.classList.remove("type-highlighted");
        }}
      }});

      if (shouldFly && matchedCount > 0 && isFinite(minX)) {{
        const boxW = maxX - minX + 240;
        const boxH = maxY - minY + 240;
        const targetScale = Math.min(1.0, Math.max(0.15, Math.min(window.innerWidth / boxW, window.innerHeight / boxH)));
        const targetPanX = (window.innerWidth - (maxX + minX) * targetScale) / 2;
        const targetPanY = Math.max(30, (window.innerHeight - (maxY + minY) * targetScale) / 2);
        smoothFlyTo(targetPanX, targetPanY, targetScale, 700);
      }}
    }}

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

    // Toggle Orphans
    let showOrphans = true;
    const btnOrphans = document.getElementById("btn-orphans");
    if (btnOrphans) {{
      btnOrphans.addEventListener("click", function() {{
        showOrphans = !showOrphans;
        this.classList.toggle("active", showOrphans);
        world.classList.toggle("hide-orphans", !showOrphans);
        renderConnectors();
      }});
    }}

    // Fit View
    function fitView(duration = 700) {{
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const [id, pos] of nodePositions.entries()) {{
        if (!showOrphans && unvisited.includes(id)) continue;
        minX = Math.min(minX, pos.x);
        minY = Math.min(minY, pos.y);
        maxX = Math.max(maxX, pos.x + CARD_W);
        maxY = Math.max(maxY, pos.y + CARD_H);
      }}
      if (!isFinite(minX)) {{
        minX = 0; minY = 0; maxX = 1200; maxY = 800;
      }}
      const worldW = maxX - minX + 240;
      const worldH = maxY - minY + 240;
      const targetScale = Math.min(1.0, Math.max(0.015, Math.min(window.innerWidth / worldW, window.innerHeight / worldH)));
      const targetPanX = (window.innerWidth - (maxX + minX) * targetScale) / 2;
      const targetPanY = 40;
      smoothFlyTo(targetPanX, targetPanY, targetScale, duration);
    }}

    document.getElementById("btn-fit").addEventListener("click", () => fitView(700));

    window.addEventListener("resize", () => {{
      renderConnectors();
    }});

    // Initial View on load
    if (window.location.hash === "#fit") {{
      fitView(0);
    }} else {{
      centerOnStart(0);
    }}
  </script>
</body>
</html>
"""
        output_path.write_text(html_content, encoding="utf-8")
