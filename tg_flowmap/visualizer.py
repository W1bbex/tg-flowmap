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
  <title>tg-flowmap — Интерактивная карта Telegram-бота</title>
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #0f172a;
      color: #f8fafc;
      overflow: hidden;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }}
    header {{
      background: #1e293b;
      border-bottom: 1px solid #334155;
      padding: 12px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      z-index: 10;
    }}
    .logo {{
      font-weight: 700;
      font-size: 18px;
      letter-spacing: -0.5px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .logo span {{ color: #38bdf8; }}
    .stats-bar {{
      display: flex;
      gap: 16px;
      font-size: 13px;
    }}
    .stat-badge {{
      background: #334155;
      padding: 4px 10px;
      border-radius: 6px;
      display: flex;
      gap: 6px;
      align-items: center;
    }}
    .stat-badge.error {{ background: #7f1d1d; color: #fca5a5; }}
    .stat-badge.warning {{ background: #78350f; color: #fde68a; }}
    .stat-badge.success {{ background: #064e3b; color: #6ee7b7; }}

    .search-box {{
      background: #0f172a;
      border: 1px solid #475569;
      border-radius: 6px;
      padding: 6px 12px;
      color: #fff;
      font-size: 13px;
      outline: none;
      width: 220px;
    }}
    .search-box:focus {{ border-color: #38bdf8; }}

    .main-container {{
      flex: 1;
      display: flex;
      position: relative;
      overflow: hidden;
    }}
    #network-canvas {{
      flex: 1;
      height: 100%;
      background: radial-gradient(#1e293b 1px, transparent 1px);
      background-size: 24px 24px;
    }}
    .side-panel {{
      width: 380px;
      background: #1e293b;
      border-left: 1px solid #334155;
      padding: 20px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .panel-title {{
      font-size: 16px;
      font-weight: 600;
      color: #38bdf8;
      word-break: break-all;
    }}
    .card {{
      background: #0f172a;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 12px;
    }}
    .card-title {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #94a3b8;
      margin-bottom: 8px;
    }}
    .card-content {{
      font-size: 13px;
      line-height: 1.5;
      color: #e2e8f0;
      white-space: pre-wrap;
      max-height: 200px;
      overflow-y: auto;
      background: #020617;
      padding: 8px;
      border-radius: 6px;
      font-family: monospace;
    }}
    .button-list {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .btn-item {{
      background: #1e293b;
      border: 1px solid #475569;
      padding: 6px 10px;
      border-radius: 6px;
      font-size: 13px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .btn-item.dead {{ border-color: #ef4444; background: #450a0a; }}
    .btn-cb {{ font-size: 11px; color: #94a3b8; font-family: monospace; }}

    .issues-list {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .issue-item {{
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.4;
    }}
    .issue-item.error {{ background: #450a0a; border-left: 3px solid #ef4444; color: #fca5a5; }}
    .issue-item.warning {{ background: #451a03; border-left: 3px solid #f59e0b; color: #fde68a; }}
  </style>
</head>
<body>
  <header>
    <div class="logo">🧭 tg-flowmap <span>// bot visualizer & linter</span></div>
    <div class="stats-bar">
      <div class="stat-badge success">Экраны: <strong id="stat-nodes">0</strong></div>
      <div class="stat-badge">Связи: <strong id="stat-edges">0</strong></div>
      <div class="stat-badge error">Тупики: <strong id="stat-dead">0</strong></div>
      <div class="stat-badge warning">Предупреждения: <strong id="stat-warn">0</strong></div>
    </div>
    <input type="text" id="search-input" class="search-box" placeholder="Поиск кнопки или экрана..." />
  </header>

  <div class="main-container">
    <div id="network-canvas"></div>
    <div class="side-panel" id="side-panel">
      <div class="panel-title" id="panel-title">Выберите экран на карте</div>
      
      <div class="card" id="card-message" style="display:none;">
        <div class="card-title">Текст сообщения Telegram</div>
        <div class="card-content" id="panel-text"></div>
      </div>

      <div class="card" id="card-buttons" style="display:none;">
        <div class="card-title">Клавиатура (Кнопки)</div>
        <div class="button-list" id="panel-buttons"></div>
      </div>

      <div class="card" id="card-issues" style="display:none;">
        <div class="card-title">Дефекты экрана</div>
        <div class="issues-list" id="panel-issues"></div>
      </div>
    </div>
  </div>

  <script>
    const rawData = {data_json};

    document.getElementById("stat-nodes").textContent = rawData.stats.total_nodes || Object.keys(rawData.nodes).length;
    document.getElementById("stat-edges").textContent = rawData.stats.total_edges || rawData.edges.length;
    document.getElementById("stat-dead").textContent = rawData.stats.dead_ends || 0;
    document.getElementById("stat-warn").textContent = (rawData.stats.missing_backs || 0) + (rawData.stats.broken_emojis || 0);

    const visNodes = [];
    const visEdges = [];

    // Map nodes
    for (const [nodeId, node] of Object.entries(rawData.nodes)) {{
      const isStart = nodeId === "cb:menu" || nodeId === "cmd:/start";
      const hasIssues = rawData.issues.some(i => i.node_id === nodeId && i.severity === "error");
      
      let bg = "#1e293b";
      let border = "#38bdf8";
      if (isStart) {{ bg = "#064e3b"; border = "#10b981"; }}
      if (hasIssues) {{ bg = "#450a0a"; border = "#ef4444"; }}

      visNodes.push({{
        id: nodeId,
        label: `📱 ${{node.title}}\\n${{node.keyboard ? `[${{node.keyboard.rows.flat().length}} кнопок]` : ""}}`,
        shape: "box",
        margin: 12,
        color: {{
          background: bg,
          border: border,
          highlight: {{ background: "#334155", border: "#67e8f9" }}
        }},
        font: {{ color: "#ffffff", size: 14, face: "-apple-system, sans-serif" }},
        shadow: {{ enabled: true, color: "rgba(0,0,0,0.5)", size: 8 }}
      }});
    }}

    // Unresolved dead-end targets
    const createdUnresolved = new Set();
    for (const edge of rawData.edges) {{
      if (edge.status === "dead_end" && !createdUnresolved.has(edge.to_node_id)) {{
        createdUnresolved.add(edge.to_node_id);
        visNodes.push({{
          id: edge.to_node_id,
          label: `❌ ТУПИК\\n${{edge.callback_data}}`,
          shape: "box",
          margin: 10,
          color: {{ background: "#7f1d1d", border: "#ef4444" }},
          font: {{ color: "#fca5a5", size: 12, face: "monospace" }}
        }});
      }}

      visEdges.push({{
        from: edge.from_node_id,
        to: edge.to_node_id,
        label: edge.button_text,
        arrows: "to",
        color: edge.status === "dead_end" ? "#ef4444" : (edge.is_back ? "#64748b" : "#38bdf8"),
        font: {{ color: "#94a3b8", size: 11, background: "#0f172a" }},
        dashes: edge.is_back || edge.status === "dead_end"
      }});
    }}

    const container = document.getElementById("network-canvas");
    const netData = {{
      nodes: new vis.DataSet(visNodes),
      edges: new vis.DataSet(visEdges)
    }};

    const options = {{
      layout: {{
        improvedLayout: true,
        hierarchical: false
      }},
      physics: {{
        solver: "forceAtlas2Based",
        forceAtlas2Based: {{
          gravitationalConstant: -70,
          centralGravity: 0.01,
          springLength: 160,
          springConstant: 0.08
        }},
        stabilization: {{ iterations: 150 }}
      }},
      interaction: {{
        hover: true,
        navigationButtons: true,
        keyboard: true
      }}
    }};

    const network = new vis.Network(container, netData, options);

    // Click handler to display inspector details
    network.on("selectNode", function(params) {{
      if (!params.nodes.length) return;
      const selectedId = params.nodes[0];
      const node = rawData.nodes[selectedId];

      const pTitle = document.getElementById("panel-title");
      const cMsg = document.getElementById("card-message");
      const pText = document.getElementById("panel-text");
      const cBtns = document.getElementById("card-buttons");
      const pBtns = document.getElementById("panel-buttons");
      const cIssues = document.getElementById("card-issues");
      const pIssues = document.getElementById("panel-issues");

      if (!node) {{
        pTitle.textContent = selectedId;
        cMsg.style.display = "none";
        cBtns.style.display = "none";
        cIssues.style.display = "block";
        pIssues.innerHTML = `<div class="issue-item error">Коллбек не найден ни в одном обработчике кода.</div>`;
        return;
      }}

      pTitle.textContent = `Экран: ${{node.title}}`;
      cMsg.style.display = "block";
      pText.textContent = node.text_template || "(Пустой текст)";

      if (node.keyboard && node.keyboard.rows.length) {{
        cBtns.style.display = "block";
        pBtns.innerHTML = "";
        for (const row of node.keyboard.rows) {{
          for (const btn of row) {{
            const div = document.createElement("div");
            div.className = "btn-item";
            div.innerHTML = `<span>${{btn.text}}</span><span class="btn-cb">${{btn.callback_data || "no-cb"}}</span>`;
            pBtns.appendChild(div);
          }}
        }}
      }} else {{
        cBtns.style.display = "none";
      }}

      const nodeIssues = rawData.issues.filter(i => i.node_id === selectedId);
      if (nodeIssues.length) {{
        cIssues.style.display = "block";
        pIssues.innerHTML = nodeIssues.map(i => `<div class="issue-item ${{i.severity}}"><strong>[${{i.issue_type}}]</strong> ${{i.message}}</div>`).join("");
      }} else {{
        cIssues.style.display = "none";
      }}
    }});

    // Search filter
    document.getElementById("search-input").addEventListener("input", function(e) {{
      const query = e.target.value.toLowerCase().trim();
      if (!query) return;
      const found = visNodes.find(n => n.label.toLowerCase().includes(query) || n.id.toLowerCase().includes(query));
      if (found) {{
        network.focus(found.id, {{ scale: 1.2, animation: true }});
        network.selectNodes([found.id]);
      }}
    }});
  </script>
</body>
</html>
"""
        output_path.write_text(html_content, encoding="utf-8")
