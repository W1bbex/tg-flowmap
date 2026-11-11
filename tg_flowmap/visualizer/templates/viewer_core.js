function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

const ICON_SYMBOLS = {
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
    };

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
    let isInteracting = false;

    function scheduleTransform(interacting = true) {
      if (interacting && !isInteracting) {
        isInteracting = true;
        world.style.willChange = "transform";
      }
      if (!isTransformPending) {
        isTransformPending = true;
        requestAnimationFrame(() => {
          updateTransform(isInteracting);
          isTransformPending = false;
        });
      }
    }

    function updateTransform(hardwareAccelerated = false) {
      const rx = Math.round(panX);
      const ry = Math.round(panY);
      if (hardwareAccelerated) {
        world.style.transform = `translate3d(${rx}px, ${ry}px, 0) scale(${scale})`;
      } else {
        world.style.willChange = "";
        world.style.transform = `translate(${rx}px, ${ry}px) scale(${scale})`;
        isInteracting = false;
      }
      if (scale < 0.25) {
        viewport.classList.add("zoomed-out");
      } else {
        viewport.classList.remove("zoomed-out");
      }
    }
    updateTransform(false);

    // Smooth Flying Animation Engine
    function smoothFlyTo(targetPanX, targetPanY, targetScale = scale, duration = 650) {
      if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
      }
      if (duration <= 0) {
        panX = targetPanX;
        panY = targetPanY;
        scale = targetScale;
        updateTransform(false);
        return;
      }

      const startPanX = panX;
      const startPanY = panY;
      const startScale = scale;
      const startTime = performance.now();

      function easeInOutCubic(t) {
        return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      }

      function frame(now) {
        const elapsed = now - startTime;
        const p = Math.min(1.0, elapsed / duration);
        const ease = easeInOutCubic(p);

        panX = startPanX + (targetPanX - startPanX) * ease;
        panY = startPanY + (targetPanY - startPanY) * ease;
        scale = startScale + (targetScale - startScale) * ease;

        if (p < 1.0) {
          updateTransform(true);
          animFrameId = requestAnimationFrame(frame);
        } else {
          animFrameId = null;
          updateTransform(false);
        }
      }

      world.style.willChange = "transform";
      animFrameId = requestAnimationFrame(frame);
    }

    // Pan & Zoom
    viewport.addEventListener("mousedown", (e) => {
      if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
      }
      if (e.target.closest(".tg-card") || e.target.closest(".hud-controls") || e.target.closest(".edge-label-pill")) return;
      isPanning = true;
      startX = e.clientX - panX;
      startY = e.clientY - panY;
      viewport.classList.add("panning");
      world.style.willChange = "transform";
    });

    window.addEventListener("mousemove", (e) => {
      if (!isPanning) return;
      panX = e.clientX - startX;
      panY = e.clientY - startY;
      scheduleTransform(true);
    });

    window.addEventListener("mouseup", () => {
      if (isPanning) {
        isPanning = false;
        viewport.classList.remove("panning");
        updateTransform(false);
      }
    });

    let wheelStopTimer = null;
    viewport.addEventListener("wheel", (e) => {
      e.preventDefault();
      if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
      }
      const zoomFactor = 1.15;
      const oldScale = scale;
      if (e.deltaY < 0) {
        scale = Math.min(2.5, scale * zoomFactor);
      } else {
        scale = Math.max(0.015, scale / zoomFactor);
      }
      const rect = viewport.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      panX = mouseX - (mouseX - panX) * (scale / oldScale);
      panY = mouseY - (mouseY - panY) * (scale / oldScale);
      scheduleTransform(true);
      if (wheelStopTimer) clearTimeout(wheelStopTimer);
      wheelStopTimer = setTimeout(() => {
        updateTransform(false);
      }, 100);
    }, { passive: false });

    document.getElementById("btn-zoom-in").addEventListener("click", () => {
      const cx = window.innerWidth / 2;
      const cy = window.innerHeight / 2;
      const targetScale = Math.min(2.5, scale * 1.3);
      const ratio = targetScale / scale;
      const targetPanX = cx - (cx - panX) * ratio;
      const targetPanY = cy - (cy - panY) * ratio;
      smoothFlyTo(targetPanX, targetPanY, targetScale, 300);
    });
    document.getElementById("btn-zoom-out").addEventListener("click", () => {
      const cx = window.innerWidth / 2;
      const cy = window.innerHeight / 2;
      const targetScale = Math.max(0.015, scale / 1.3);
      const ratio = targetScale / scale;
      const targetPanX = cx - (cx - panX) * ratio;
      const targetPanY = cy - (cy - panY) * ratio;
      smoothFlyTo(targetPanX, targetPanY, targetScale, 300);
    });
    document.getElementById("btn-reset").addEventListener("click", () => centerOnStart(650));

    function centerOnStart(duration = 650) {
      let targetNodeId = "cmd:/start";
      if (!nodePositions.has(targetNodeId)) {
        targetNodeId = nodePositions.has("cb:menu") ? "cb:menu" : (nodePositions.keys().next().value || null);
      }
      const startPos = targetNodeId ? (nodePositions.get(targetNodeId) || { x: 0, y: 0 }) : { x: 0, y: 0 };
      const targetScale = 0.8;
      const targetPanX = window.innerWidth / 2 - (startPos.x + CARD_W / 2) * targetScale;
      const targetPanY = 60;
      smoothFlyTo(targetPanX, targetPanY, targetScale, duration);
      if (targetNodeId) {
        highlightCard(targetNodeId);
      }
    }

    function centerOnHubMenu(duration = 650) {
      const hubPos = nodePositions.get("cb:menu") || { x: 0, y: 0 };
      const targetScale = 0.8;
      const targetPanX = window.innerWidth / 2 - (hubPos.x + CARD_W / 2) * targetScale;
      const targetPanY = window.innerHeight / 2 - (hubPos.y + 160) * targetScale;
      smoothFlyTo(targetPanX, targetPanY, targetScale, duration);
      highlightCard("cb:menu");
    }

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
    for (const [nodeId, node] of Object.entries(rawData.nodes)) {
      const incoming = rawData.edges.filter(e => e.to_node_id === nodeId);
      if (incoming.length >= 3) {
        const allUtility = incoming.every(e => {
          const t = (e.button_text || "").toLowerCase();
          return t.includes("отмена") || t.includes("попробовать") || t.includes("cancel") || t.includes("retry") || t.includes("закрыть") || t.includes("close") || t.includes("выйти");
        });
        if (allUtility) UTILITY_TARGETS.add(nodeId);
      }
    }

    // 1. Build Adjacency List (ignoring back buttons & utility popups)
    const forwardEdgesMap = new Map();
    for (const id of Object.keys(rawData.nodes)) {
      forwardEdgesMap.set(id, []);
    }

    if (isStartHubPair) {
      forwardEdgesMap.get(rootId).push(hubId);
    }

    for (const edge of rawData.edges) {
      if (edge.is_back) continue;
      if (edge.from_node_id === edge.to_node_id) continue;
      if (isStartHubPair && edge.from_node_id === rootId) continue;
      if (edge.from_node_id === rootId && edge.to_node_id === hubId) continue;
      if (UTILITY_TARGETS.has(edge.to_node_id)) continue;

      const list = forwardEdgesMap.get(edge.from_node_id);
      if (list && !list.includes(edge.to_node_id) && rawData.nodes[edge.to_node_id]) {
        list.push(edge.to_node_id);
      }
    }

    if (isStartHubPair) {
      forwardEdgesMap.set(rootId, [hubId]);
    }

    function getChildCategory(parentId, childId) {
      const node = rawData.nodes[parentId];
      if (!node || !node.keyboard || !node.keyboard.rows) return "left";
      const numRows = node.keyboard.rows.length;
      for (let r = 0; r < numRows; r++) {
        const row = node.keyboard.rows[r];
        for (let c = 0; c < row.length; c++) {
          const btn = row[c];
          const match = rawData.edges.some(e =>
            e.from_node_id === parentId &&
            e.to_node_id === childId &&
            ((btn.callback_data && e.callback_data === btn.callback_data) || e.button_text === btn.text)
          );
          if (match) {
            if (row.length > 2) {
              if (c === 0) return "left";
              if (c === row.length - 1) return "right";
              return "bottom";
            } else if (row.length === 2) {
              return c === 0 ? "left" : "right";
            } else {
              // Full-width (row.length === 1):
              // If bottom row (or in lower half of rows): goes bottom/center!
              if (r === numRows - 1 || r >= Math.ceil(numRows / 2)) {
                return "bottom";
              } else {
                return "left";
              }
            }
          }
        }
      }
      return "left";
    }

    // Sort children so "left" comes first, "bottom" comes second, "right" comes third
    const CATEGORY_ORDER = { left: 0, bottom: 1, right: 2 };
    for (const [id, kids] of forwardEdgesMap.entries()) {
      const node = rawData.nodes[id];
      if (node && node.keyboard && node.keyboard.rows && node.keyboard.rows.some(r => r.length > 1)) {
        kids.sort((a, b) => {
          const catA = CATEGORY_ORDER[getChildCategory(id, a)] ?? 0;
          const catB = CATEGORY_ORDER[getChildCategory(id, b)] ?? 0;
          return catA - catB;
        });
      }
    }

    // 2. Build Strict BFS Spanning Forest
    const treeChildren = new Map();
    for (const id of Object.keys(rawData.nodes)) {
      treeChildren.set(id, []);
    }

    const visitedNodes = new Set();
    const nodeToRoot = new Map();
    const forestRoots = [];

    function exploreBfsTree(startRoot) {
      if (!rawData.nodes[startRoot] || visitedNodes.has(startRoot) || UTILITY_TARGETS.has(startRoot)) return;
      visitedNodes.add(startRoot);
      forestRoots.push(startRoot);
      nodeToRoot.set(startRoot, startRoot);
      const queue = [startRoot];

      while (queue.length > 0) {
        const curr = queue.shift();
        const children = forwardEdgesMap.get(curr) || [];
        for (const childId of children) {
          if (UTILITY_TARGETS.has(childId)) continue;
          if (!visitedNodes.has(childId)) {
            visitedNodes.add(childId);
            nodeToRoot.set(childId, startRoot);
            treeChildren.get(curr).push(childId);
            queue.push(childId);
          }
        }
      }
    }

    // Explore main bot tree
    exploreBfsTree(rootId);
    if (!visitedNodes.has(hubId)) exploreBfsTree(hubId);

    // Classification helper for the 4 core types
    function getNodeType(nodeId, node) {
      if (node && node.node_type) return node.node_type;
      if (nodeId.startsWith("cmd:") || (node && node.trigger_type === "command")) return "command";
      if (UTILITY_TARGETS.has(nodeId) || (node && node.is_alert)) return "popup";
      if (node && node.keyboard && node.keyboard.rows && node.keyboard.rows.length > 0) return "message";
      return "callback";
    }

    // 3. Exact Subtree Width on the Spanning Tree with Trifurcation Support (Left / Bottom-Center / Right)
    function computeSubtreeWidth(nodeId) {
      const children = treeChildren.get(nodeId) || [];
      if (children.length === 0) return CARD_W;

      const isHub = (nodeId === hubId);
      if (isHub) {
        const leftKids = children.filter(c => getChildCategory(nodeId, c) === "left");
        const bottomKids = children.filter(c => getChildCategory(nodeId, c) === "bottom");
        const rightKids = children.filter(c => getChildCategory(nodeId, c) === "right");

        if (leftKids.length > 0 || rightKids.length > 0 || bottomKids.length > 0) {
          let leftW = 0;
          for (let i = 0; i < leftKids.length; i++) {
            if (i > 0) leftW += SIBLING_GAP_X;
            leftW += computeSubtreeWidth(leftKids[i]);
          }

          let bottomW = 0;
          for (let i = 0; i < bottomKids.length; i++) {
            if (i > 0) bottomW += SIBLING_GAP_X;
            bottomW += computeSubtreeWidth(bottomKids[i]);
          }

          let rightW = 0;
          for (let i = 0; i < rightKids.length; i++) {
            if (i > 0) rightW += SIBLING_GAP_X;
            rightW += computeSubtreeWidth(rightKids[i]);
          }

          const centerBlockW = Math.max(CARD_W, bottomW);
          const gapLeft = (leftW > 0) ? Math.max(SIBLING_GAP_X, 80) : 0;
          const gapRight = (rightW > 0) ? Math.max(SIBLING_GAP_X, 80) : 0;

          return leftW + gapLeft + centerBlockW + gapRight + rightW;
        }
      }

      let totalW = 0;
      for (let i = 0; i < children.length; i++) {
        if (i > 0) totalW += SIBLING_GAP_X;
        totalW += computeSubtreeWidth(children[i]);
      }
      return Math.max(CARD_W, totalW);
    }

    function shiftSubtree(nodeId, dx) {
      if (dx === 0) return;
      const pos = nodePositions.get(nodeId);
      if (pos) pos.x += dx;
      const kids = treeChildren.get(nodeId) || [];
      for (const kid of kids) shiftSubtree(kid, dx);
    }

    function placeTreeNode(nodeId, leftX, levelY) {
      const children = treeChildren.get(nodeId) || [];
      const isHub = (nodeId === hubId);

      if (isHub) {
        const leftKids = children.filter(c => getChildCategory(nodeId, c) === "left");
        const bottomKids = children.filter(c => getChildCategory(nodeId, c) === "bottom");
        const rightKids = children.filter(c => getChildCategory(nodeId, c) === "right");

        if (leftKids.length > 0 || rightKids.length > 0 || bottomKids.length > 0) {
          let leftW = 0;
          for (let i = 0; i < leftKids.length; i++) {
            if (i > 0) leftW += SIBLING_GAP_X;
            leftW += computeSubtreeWidth(leftKids[i]);
          }

          let bottomW = 0;
          for (let i = 0; i < bottomKids.length; i++) {
            if (i > 0) bottomW += SIBLING_GAP_X;
            bottomW += computeSubtreeWidth(bottomKids[i]);
          }

          let rightW = 0;
          for (let i = 0; i < rightKids.length; i++) {
            if (i > 0) rightW += SIBLING_GAP_X;
            rightW += computeSubtreeWidth(rightKids[i]);
          }

          const centerBlockW = Math.max(CARD_W, bottomW);
          const gapLeft = (leftW > 0) ? Math.max(SIBLING_GAP_X, 80) : 0;
          const gapRight = (rightW > 0) ? Math.max(SIBLING_GAP_X, 80) : 0;

          const centerBlockX = leftX + (leftW > 0 ? leftW + gapLeft : 0);
          const myX = centerBlockX + (centerBlockW - CARD_W) / 2;
          nodePositions.set(nodeId, { x: myX, y: levelY });

          // 1. Place leftKids
          let childLeftX = leftX;
          for (const childId of leftKids) {
            const childW = computeSubtreeWidth(childId);
            placeTreeNode(childId, childLeftX, levelY + CARD_H + LEVEL_GAP_Y);
            childLeftX += childW + SIBLING_GAP_X;
          }

          // 2. Place bottomKids (centered directly under parent card!)
          let childBottomX = centerBlockX + (centerBlockW - bottomW) / 2;
          for (const childId of bottomKids) {
            const childW = computeSubtreeWidth(childId);
            placeTreeNode(childId, childBottomX, levelY + CARD_H + LEVEL_GAP_Y);
            childBottomX += childW + SIBLING_GAP_X;
          }

          // If single bottom kid, align its card center directly under parent card center!
          if (bottomKids.length === 1) {
            const bKid = bottomKids[0];
            const bPos = nodePositions.get(bKid);
            if (bPos) shiftSubtree(bKid, myX - bPos.x);
          }

          // 3. Place rightKids
          let childRightX = centerBlockX + centerBlockW + gapRight;
          for (const childId of rightKids) {
            const childW = computeSubtreeWidth(childId);
            placeTreeNode(childId, childRightX, levelY + CARD_H + LEVEL_GAP_Y);
            childRightX += childW + SIBLING_GAP_X;
          }
          return;
        }
      }

      const subtreeW = computeSubtreeWidth(nodeId);
      const myX = leftX + (subtreeW - CARD_W) / 2;
      nodePositions.set(nodeId, { x: myX, y: levelY });

      let childLeftX = leftX;
      for (const childId of children) {
        const childW = computeSubtreeWidth(childId);
        placeTreeNode(childId, childLeftX, levelY + CARD_H + LEVEL_GAP_Y);
        childLeftX += childW + SIBLING_GAP_X;
      }
    }

    // 4. Place Main Tree
    placeTreeNode(rootId, 0, 0);
    if (isStartHubPair && nodePositions.has(rootId) && nodePositions.has(hubId)) {
      nodePositions.get(rootId).x = nodePositions.get(hubId).x;
    }

    const mainTreeWidth = computeSubtreeWidth(rootId);

    function estimateCardHeight(nodeId) {
      const node = rawData.nodes[nodeId];
      if (!node) return 260;
      let h = 55;
      const txt = node.text_template || "";
      const lines = txt.split("\n").length;
      h += Math.max(65, Math.min(450, lines * 19 + 35));
      if (node.keyboard && node.keyboard.rows) {
        h += node.keyboard.rows.length * 44 + 16;
      }
      return Math.max(220, h);
    }

    function layoutDeck(nodeIds, cols, startX, startY, colGap = 60, rowGap = 50) {
      if (!nodeIds || nodeIds.length === 0) {
        return { box: null, maxX: startX, maxY: startY, nodeIds: [], cols, startX, startY, rowGap, colGap };
      }

      const numRows = Math.ceil(nodeIds.length / cols);
      const rowHeights = new Array(numRows).fill(0);

      nodeIds.forEach((id, idx) => {
        const r = Math.floor(idx / cols);
        const estH = estimateCardHeight(id);
        rowHeights[r] = Math.max(rowHeights[r], estH);
      });

      const rowY = [startY];
      for (let r = 0; r < numRows; r++) {
        rowY.push(rowY[r] + rowHeights[r] + rowGap);
      }

      let maxX = startX;
      nodeIds.forEach((id, idx) => {
        const c = idx % cols;
        const r = Math.floor(idx / cols);
        const gx = startX + c * (CARD_W + colGap);
        const gy = rowY[r];
        nodePositions.set(id, { x: gx, y: gy });
        maxX = Math.max(maxX, gx + CARD_W);
      });

      const maxY = rowY[numRows];
      return {
        box: {
          x: startX - 20,
          y: startY - 20,
          w: maxX - startX + 40,
          h: maxY - startY + 40,
          count: nodeIds.length,
        },
        maxX,
        maxY,
        nodeIds,
        cols,
        startX,
        startY,
        rowGap,
        colGap
      };
    }

    // 5. Place Secondary Commands in a Dynamic Multi-Row Deck
    const secondaryCmds = Object.keys(rawData.nodes).filter(k => k.startsWith("cmd:") && !nodePositions.has(k));
    const cmdStartX = mainTreeWidth + 120;
    const cmdLayout = layoutDeck(secondaryCmds, 3, cmdStartX, 0, 60, 50);
    const cmdBox = cmdLayout.box;
    const maxCmdX = cmdLayout.maxX;
    const maxCmdY = cmdLayout.maxY;

    // 6. Place Utility / Popups in a Dynamic Multi-Row Deck
    const utilNodesList = Object.keys(rawData.nodes).filter(k => UTILITY_TARGETS.has(k) && !nodePositions.has(k));
    const utilStartX = maxCmdX + 70;
    const utilLayout = layoutDeck(utilNodesList, 2, utilStartX, 0, 60, 50);
    const utilBox = utilLayout.box;
    const maxUtilX = utilLayout.maxX;
    const maxUtilY = utilLayout.maxY;

    // 7. Place Remaining Handlers in a Dynamic Multi-Row Deck below
    const unvisited = Object.keys(rawData.nodes).filter(k => !nodePositions.has(k));
    const remStartX = mainTreeWidth + 120;
    const remStartY = Math.max(maxCmdY, maxUtilY) + 80;
    const remLayout = layoutDeck(unvisited, 4, remStartX, remStartY, 60, 50);
    const remBox = remLayout.box;

    // Render Canvas Zone Boxes
    if (cmdBox) {
      const z = document.createElement("div");
      z.className = "canvas-zone zone-commands";
      z.style.left = `${cmdBox.x}px`;
      z.style.top = `${cmdBox.y}px`;
      z.style.width = `${cmdBox.w}px`;
      z.style.height = `${cmdBox.h}px`;
      z.innerHTML = `
        <div class="canvas-zone-header">
          <span class="zone-icon">⚡</span>
          <span>Слэш-команды Telegram (${cmdBox.count})</span>
          <span class="zone-sub">// вводятся в чат через /</span>
        </div>
      `;
      nodesContainer.appendChild(z);
    }

    if (utilBox) {
      const z = document.createElement("div");
      z.className = "canvas-zone zone-popups";
      z.style.left = `${utilBox.x}px`;
      z.style.top = `${utilBox.y}px`;
      z.style.width = `${utilBox.w}px`;
      z.style.height = `${utilBox.h}px`;
      z.innerHTML = `
        <div class="canvas-zone-header">
          <span class="zone-icon">🔔</span>
          <span>Всплывающие окна и диалоги (${utilBox.count})</span>
          <span class="zone-sub">// answerCallbackQuery</span>
        </div>
      `;
      nodesContainer.appendChild(z);
    }

    if (remBox) {
      const z = document.createElement("div");
      z.className = "canvas-zone zone-handlers";
      z.style.left = `${remBox.x}px`;
      z.style.top = `${remBox.y}px`;
      z.style.width = `${remBox.w}px`;
      z.style.height = `${remBox.h}px`;
      z.innerHTML = `
        <div class="canvas-zone-header">
          <span class="zone-icon">📦</span>
          <span>Дополнительные сценарии и обработчики (${remBox.count})</span>
          <span class="zone-sub">// вспомогательные действия и подсистемы</span>
        </div>
      `;
      nodesContainer.appendChild(z);
    }

    // Pass 2: Exact DOM-measured height refinement to ensure zero collisions
    function refineDeckWithDomHeights(deckLayout, zoneClass, customStartY = null) {
      if (!deckLayout || !deckLayout.nodeIds || deckLayout.nodeIds.length === 0) return (customStartY !== null ? customStartY : 0);
      const { nodeIds, cols, startX, rowGap, colGap } = deckLayout;
      const startY = (customStartY !== null) ? customStartY : deckLayout.startY;
      const numRows = Math.ceil(nodeIds.length / cols);
      const measuredRowH = new Array(numRows).fill(0);

      nodeIds.forEach((id, idx) => {
        const r = Math.floor(idx / cols);
        const cardEl = nodeElements.get(id);
        const h = cardEl ? (cardEl.offsetHeight || 260) : 260;
        measuredRowH[r] = Math.max(measuredRowH[r], h);
      });

      const rowY = [startY];
      for (let r = 0; r < numRows; r++) {
        rowY.push(rowY[r] + measuredRowH[r] + rowGap);
      }

      let maxX = startX;
      nodeIds.forEach((id, idx) => {
        const c = idx % cols;
        const r = Math.floor(idx / cols);
        const gx = startX + c * (CARD_W + (colGap || 60));
        const gy = rowY[r];
        nodePositions.set(id, { x: gx, y: gy });
        const cardEl = nodeElements.get(id);
        if (cardEl) {
          cardEl.style.left = `${gx}px`;
          cardEl.style.top = `${gy}px`;
        }
        maxX = Math.max(maxX, gx + CARD_W);
      });

      const maxY = rowY[numRows];
      const zoneEl = document.querySelector(`.${zoneClass}`);
      if (zoneEl) {
        zoneEl.style.top = `${startY - 20}px`;
        zoneEl.style.width = `${maxX - startX + 40}px`;
        zoneEl.style.height = `${maxY - startY + 40}px`;
      }
      return maxY;
    }

    function formatMessageText(text) {
      if (!text) return "";
      let res = String(text);
      // Temporarily stash Telegram premium emojis
      if (rawData.custom_emojis) {
        res = res.replace(/<tg-emoji[^>]*emoji-id=['"](\d+)['"][^>]*>.*?<\/tg-emoji>/gi, (match, id) => {
          if (rawData.custom_emojis[id]) {
            return `__TG_EMOJI_${id}__`;
          }
          return match;
        });
      }
      // Escape raw HTML entities to eliminate Stored DOM XSS
      res = escapeHtml(res);
      // Whitelist safe Telegram markdown/HTML formatting tags
      res = res
        .replace(/&lt;(\/)?(b|i|code|pre|s|u|tg-spoiler)&gt;/gi, '<$1$2>')
        .replace(/&lt;a\s+href=(&quot;|&#039;)(https?:\/\/[^&]+)\1&gt;(.*?)&lt;\/a&gt;/gi, '<a href="$2" target="_blank" rel="noopener">$3</a>');
      // Restore cached Telegram premium emojis with verified data URIs
      if (rawData.custom_emojis) {
        res = res.replace(/__TG_EMOJI_(\d+)__/g, (match, id) => {
          const safeSrc = escapeHtml(rawData.custom_emojis[id] || "");
          return `<img class="tg-premium-emoji" src="${safeSrc}" alt="emoji" />`;
        });
      }
      return res;
    }

    function getButtonColorClass(btn) {
      if (btn.style) return `style-${btn.style.toLowerCase()}`;
      const tLow = (btn.text || "").toLowerCase();
      if (tLow.includes("питание") || tLow.includes("включить") || tLow.includes("разблокировать")) return "style-success";
      if (tLow.includes("выключить") || tLow.includes("отмена") || tLow.includes("удалить")) return "style-danger";
      if (tLow.includes("скриншот") || tLow.includes("программы") || tLow.includes("звук") || tLow.includes("настройки")) return "style-primary";
      return "";
    }

    function getButtonHexColor(btn) {
      const cls = getButtonColorClass(btn);
      if (cls === "style-success") return "#31b545";
      if (cls === "style-danger") return "#df3f40";
      if (cls === "style-primary") return "#2ea6ff";
      return "#38bdf8";
    }
