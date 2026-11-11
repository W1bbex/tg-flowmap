    function createCard(nodeId, node) {
      const pos = nodePositions.get(nodeId) || { x: 0, y: 0 };
      const card = document.createElement("div");
      card.className = "tg-card";
      const nodeType = getNodeType(nodeId, node);
      card.dataset.nodeType = nodeType;
      card.classList.add(`card-type-${nodeType}`);


      if (nodeId === "cmd:/start") card.classList.add("is-root-start");
      if (nodeId === "cb:menu") card.classList.add("is-hub-menu");
      if (nodeType === "popup") card.classList.add("is-utility-card");
      if (unvisited.includes(nodeId)) card.classList.add("is-orphan-card");
      card.id = `card-${nodeId}`;
      card.style.left = `${pos.x}px`;
      card.style.top = `${pos.y}px`;

      // Top Port for incoming arrows
      const topPort = document.createElement("div");
      topPort.className = "card-top-port";
      card.appendChild(topPort);

      // Card Header
      const header = document.createElement("div");
      header.className = "tg-card-header";
      const srcName = node.source_file ? node.source_file.split(/[/\\\\]/).pop() : "";
      const lineStr = node.line_number ? `:${node.line_number}` : "";

      let icon = "💬";
      let badgeHtml = "";
      if (nodeId === "cmd:/start") {
        icon = "⭐";
        badgeHtml = `<span class="badge-type badge-type-entry">⭐ Вход</span>`;
      } else if (nodeId === "cb:menu") {
        icon = "🏠";
        badgeHtml = `<span class="badge-type badge-type-hub">🏠 Меню</span>`;
      } else if (nodeType === "command") {
        icon = "⚡";
        badgeHtml = `<span class="badge-type badge-type-command">⚡ Команда</span>`;
      } else if (nodeType === "popup") {
        icon = "🔔";
        badgeHtml = `<span class="badge-type badge-type-popup">🔔 Всплывающее</span>`;
      } else if (nodeType === "callback") {
        icon = "🔘";
        badgeHtml = `<span class="badge-type badge-type-callback">🔘 Действие</span>`;
      } else {
        icon = "💬";
        badgeHtml = `<span class="badge-type badge-type-message">💬 Экран</span>`;
      }

      if (node.aliases && node.aliases.length > 0) {
        for (const alias of node.aliases) {
          if (alias.startsWith("/") || alias.startsWith("cmd:/")) {
            const rawClean = alias.startsWith("cmd:/") ? alias.slice(4) : alias;
            const cleanCmd = escapeHtml(rawClean);
            badgeHtml += ` <span class="badge-type badge-type-command" title="Альтернативная команда вызова: ${cleanCmd}">⚡ ${cleanCmd}</span>`;
          }
        }
      }

      const cleanTitle = (node.title || "").replace(/^cb:/, "").replace(/^cmd:[/]*/, "/");
      const displayTitle = nodeType === "command" ? (nodeId.startsWith("cmd:/") ? nodeId.slice(4) : "/" + nodeId.slice(4)) : cleanTitle;
      const safeTitle = escapeHtml(displayTitle);
      const safeSrcName = escapeHtml(srcName);

      header.innerHTML = `
        <div class="card-title-group">
          <span style="font-size:13px;">${icon}</span>
          <span class="card-screen-title" title="${safeTitle}">${safeTitle}</span>
          ${badgeHtml}
        </div>
        <div class="card-meta">${safeSrcName}${lineStr}</div>
      `;
      card.appendChild(header);

      // Message Body / Custom Box Mockup
      const isStartHub = (isStartHubPair && nodeId === rootId);
      if (isStartHub) {
        const body = document.createElement("div");
        body.className = "tg-card-body";
        body.innerHTML = formatMessageText(node.text_template || "<i>(Точка входа)</i>");
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
      } else if (nodeType === "popup") {
        const body = document.createElement("div");
        body.className = "tg-card-body";
        body.innerHTML = `
          <div class="popup-modal-mockup">
            <div class="popup-modal-icon">🔔</div>
            <div class="popup-modal-content">
              <div class="popup-modal-title">Всплывающее окно</div>
              <div class="popup-modal-text">${formatMessageText(node.text_template || "Уведомление answerCallbackQuery")}</div>
            </div>
          </div>
          <div class="popup-modal-footer">
            <div class="popup-modal-btn">OK</div>
          </div>
        `;
        card.appendChild(body);
      } else if (nodeType === "command") {
        const body = document.createElement("div");
        body.className = "tg-card-body";
        const rawCmd = nodeId.startsWith("cmd:/") ? nodeId.slice(5) : nodeId.slice(4);
        const cmdName = escapeHtml(rawCmd);
        body.innerHTML = `
          <div class="command-box">
            <div class="command-box-prompt"><code>/${cmdName}</code></div>
            <div class="command-box-text">${formatMessageText(node.text_template || "Команда Telegram-чата")}</div>
          </div>
        `;
        card.appendChild(body);
      } else if (nodeType === "callback" && (!node.keyboard || !node.keyboard.rows || !node.keyboard.rows.length)) {
        const body = document.createElement("div");
        body.className = "tg-card-body";
        const cbName = escapeHtml(nodeId.replace(/^cb:/, ''));
        body.innerHTML = `
          <div class="callback-action-box">
            <div class="callback-action-header">🔘 Действие: <code>${cbName}</code></div>
            <div class="callback-action-text">${formatMessageText(node.text_template || "Обрабатывает нажатие инлайн-кнопки")}</div>
          </div>
        `;
        card.appendChild(body);
      } else {
        const body = document.createElement("div");
        body.className = "tg-card-body";
        body.innerHTML = formatMessageText(node.text_template || "<i>(Пустой текст)</i>");
        card.appendChild(body);
      }

      // Keyboard with Colored Buttons
      if (node.keyboard && node.keyboard.rows && node.keyboard.rows.length) {
        const kbDiv = document.createElement("div");
        kbDiv.className = "tg-keyboard";

        node.keyboard.rows.forEach((row, rowIdx) => {
          const rowDiv = document.createElement("div");
          rowDiv.className = "tg-row";

          row.forEach((btn, btnIdx) => {
            const btnEl = document.createElement("div");
            btnEl.className = "tg-btn";
            btnEl.id = `btn-${nodeId}-${rowIdx}-${btnIdx}`;
            btnEl.dataset.btnText = btn.text;
            if (btn.callback_data) btnEl.dataset.callbackData = btn.callback_data;

            // Color Class
            const btnStyle = getButtonColorClass(btn);
            if (btnStyle) btnEl.classList.add(btnStyle);

            // Dead end
            const isDead = rawData.edges.some(e => e.from_node_id === nodeId && e.button_text === btn.text && e.status === "dead_end");
            if (isDead) {
              btnEl.classList.add("dead-end-btn");
              btnEl.title = `❌ ТУПИК: коллбек '${btn.callback_data}' не найден!`;
            }

            let iconHtml = "";
            const customEmojiUrl = (rawData.custom_emojis && btn.icon_custom_emoji_id && rawData.custom_emojis[btn.icon_custom_emoji_id]);
            if (customEmojiUrl) {
              iconHtml = `<img class="tg-premium-emoji" src="${escapeHtml(customEmojiUrl)}" alt="icon" />`;
            } else if (btn.icon_custom_emoji_id && ICON_SYMBOLS[btn.icon_custom_emoji_id]) {
              iconHtml = `<span>${ICON_SYMBOLS[btn.icon_custom_emoji_id]} </span>`;
            } else {
              const tLow = (btn.text || "").toLowerCase();
              for (const [k, sym] of Object.entries(ICON_SYMBOLS)) {
                if (tLow.includes(k)) { iconHtml = `<span>${sym} </span>`; break; }
              }
            }

            btnEl.innerHTML = `<span>${iconHtml}${escapeHtml(btn.text)}</span>`;

            btnEl.addEventListener("mouseenter", () => {
              highlightEdgeBranch(nodeId, btn.text);
              showTempTargetArrow(nodeId, btn.text);
            });
            btnEl.addEventListener("mouseleave", () => {
              resetEdgeHighlights();
              removeTempReturnArrow();
            });
            btnEl.addEventListener("click", (e) => {
              e.stopPropagation();
              const edge = rawData.edges.find(e => 
                e.from_node_id === nodeId && 
                ((btn.callback_data && e.callback_data === btn.callback_data) || e.button_text === btn.text)
              );
              if (edge && edge.to_node_id) {
                pulseEdgeBranch(nodeId, edge.to_node_id, btn.text);
                focusOnCard(edge.to_node_id, 700);
              }
            });

            rowDiv.appendChild(btnEl);
          });

          kbDiv.appendChild(rowDiv);
        });

        card.appendChild(kbDiv);
      }

      setupCardDrag(card, header, nodeId);
      nodesContainer.appendChild(card);
      nodeElements.set(nodeId, card);
    }

    function setupCardDrag(card, handle, nodeId) {
      let dragStartX, dragStartY, cardStartX, cardStartY;

      const onMouseMove = (e) => {
        const dx = (e.clientX - dragStartX) / scale;
        const dy = (e.clientY - dragStartY) / scale;
        const newX = Math.round(cardStartX + dx);
        const newY = Math.round(cardStartY + dy);
        card.style.left = `${newX}px`;
        card.style.top = `${newY}px`;
        nodePositions.set(nodeId, { x: newX, y: newY });
        renderConnectors();
      };

      const onMouseUp = () => {
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
      };

      handle.addEventListener("mousedown", (e) => {
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        const pos = nodePositions.get(nodeId);
        cardStartX = pos.x;
        cardStartY = pos.y;
        e.stopPropagation();

        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
      });
    }

    for (const [nodeId, node] of Object.entries(rawData.nodes)) {
      createCard(nodeId, node);
    }

    const realCmdMaxY = refineDeckWithDomHeights(cmdLayout, "zone-commands");
    const realUtilMaxY = refineDeckWithDomHeights(utilLayout, "zone-popups");
    const realRemStartY = Math.max(realCmdMaxY, realUtilMaxY) + 100;
    refineDeckWithDomHeights(remLayout, "zone-handlers", realRemStartY);

    // ==========================================
    // RENDER COLORED & LABELED ARROWS WITH BUNDLING
    // ==========================================
    const renderedEdgePaths = [];
    let showBackEdges = false;
    let tempReturnPath = null;

    function isReturnOrCross(edge, fromPos, toPos) {
      if (edge.is_back) return true;
      if (toPos.y <= fromPos.y) return true;
      const fromRoot = nodeToRoot.get(edge.from_node_id);
      const toRoot = nodeToRoot.get(edge.to_node_id);
      if ((toRoot === rootId || toRoot === hubId) && fromRoot !== toRoot) {
        return true;
      }
      return false;
    }

    function renderConnectors() {
      const edgesGroup = document.getElementById("edges-group");
      if (!edgesGroup) return;
      edgesGroup.innerHTML = "";
      labelsContainer.innerHTML = "";
      renderedEdgePaths.length = 0;
      removeTempReturnArrow();
      document.querySelectorAll(".card-edge-port").forEach(p => p.remove());

      // Dynamically size SVG layer to match graph bounds
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const pos of nodePositions.values()) {
        minX = Math.min(minX, pos.x);
        minY = Math.min(minY, pos.y);
        maxX = Math.max(maxX, pos.x + CARD_W);
        maxY = Math.max(maxY, pos.y + CARD_H);
      }
      const worldW = Math.max(2000, maxX - minX + 600);
      const worldH = Math.max(2000, maxY - minY + 600);
      svgLayer.setAttribute("width", worldW);
      svgLayer.setAttribute("height", worldH);
      svgLayer.style.width = worldW + "px";
      svgLayer.style.height = worldH + "px";

      // Special entry connector: /start -> cb:menu
      if (isStartHubPair) {
        drawDirectArrow(rootId, hubId, "Запуск бота", "/start", "#10b981", false);
      }

      // Group edges by (from_node_id, to_node_id, is_back) to eliminate duplicate fans
      const bundles = new Map();
      for (const edge of rawData.edges) {
        if (isStartHubPair && edge.from_node_id === rootId) continue;
        if (edge.from_node_id === edge.to_node_id) continue;
        if (UTILITY_TARGETS.has(edge.to_node_id)) continue;

        const fromPos = nodePositions.get(edge.from_node_id);
        const toPos = nodePositions.get(edge.to_node_id);
        if (!fromPos || !toPos) continue;

        const isRet = isReturnOrCross(edge, fromPos, toPos);
        if (isRet && !showBackEdges) continue;

        const bKey = `${edge.from_node_id}:::${edge.to_node_id}:::${!!isRet}`;
        if (!bundles.has(bKey)) {
          bundles.set(bKey, {
            from_node_id: edge.from_node_id,
            to_node_id: edge.to_node_id,
            is_back: !!isRet,
            status: edge.status,
            edges: []
          });
        }
        bundles.get(bKey).edges.push(edge);
      }

      for (const bundle of bundles.values()) {
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

        if (bundle.status === "dead_end") {
          strokeColor = "#ef4444";
          markerId = "url(#arrow-dead)";
        } else if (bundle.is_back) {
          strokeColor = "#64748b";
          markerId = "url(#arrow-back)";
        } else if (btnEl) {
          if (btnEl.classList.contains("style-success")) { strokeColor = "#31b545"; markerId = "url(#arrow-green)"; }
          else if (btnEl.classList.contains("style-danger")) { strokeColor = "#df3f40"; markerId = "url(#arrow-red)"; }
          else if (btnEl.classList.contains("style-primary")) { strokeColor = "#2ea6ff"; markerId = "url(#arrow-blue)"; }
        }

        const toX = toPos.x + CARD_W / 2;
        const toY = toPos.y;
        let fromX = fromPos.x + CARD_W / 2;
        let fromY = fromPos.y + (fromCard.offsetHeight || CARD_H);
        let portDirection = "down";

        if (btnEl) {
          let cur = btnEl;
          let offLeft = 0;
          let offTop = 0;
          while (cur && cur !== fromCard) {
            offLeft += cur.offsetLeft;
            offTop += cur.offsetTop;
            cur = cur.offsetParent;
          }
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
          const fromCardBottom = fromPos.y + (fromCard.offsetHeight || CARD_H);
          const isDirectlyBelow = (toY >= fromCardBottom - 50 && Math.abs(toCenterX - fromCardCenterX) <= CARD_W * 0.85);

          if (bundle.is_back || toY <= fromPos.y) {
            portDirection = "return";
            fromX = fromPos.x + CARD_W;
            fromY = fromPos.y + btnCenterY;
          } else if (isDirectlyBelow) {
            portDirection = "down";
            fromX = fromPos.x + (isLeftCol ? CARD_W * 0.35 : (isRightCol ? CARD_W * 0.65 : CARD_W * 0.5));
            fromY = fromCardBottom;
          } else if (toCenterX < fromCardCenterX - 30) {
            portDirection = "left";
            fromX = fromPos.x;
            fromY = fromPos.y + btnCenterY;
          } else if (toCenterX > fromCardCenterX + 30) {
            portDirection = "right";
            fromX = fromPos.x + CARD_W;
            fromY = fromPos.y + btnCenterY;
          } else {
            portDirection = "down";
            fromX = fromPos.x + offLeft + bW / 2;
            fromY = fromCardBottom;
          }

          let portEl = fromCard.querySelector(`.card-edge-port[data-btn-id="${btnEl.id}"]`);
          if (!portEl) {
            portEl = document.createElement("div");
            portEl.className = `card-edge-port port-${portDirection}`;
            portEl.dataset.btnId = btnEl.id;
            portEl.style.color = strokeColor;
            portEl.style.backgroundColor = strokeColor;
            if (portDirection === "left" || portDirection === "right" || portDirection === "return") {
              portEl.style.top = `${btnCenterY}px`;
            } else if (portDirection === "down") {
              portEl.style.left = `${fromX - fromPos.x}px`;
            }
            fromCard.appendChild(portEl);
          }
        }

        const topPort = toCard.querySelector(".card-top-port");
        if (topPort && !bundle.is_back) {
          topPort.style.backgroundColor = strokeColor;
          topPort.style.color = strokeColor;
        }

        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        let d, midX, midY;
        const fromCardBottomY = fromPos.y + (fromCard.offsetHeight || CARD_H);

        if (portDirection === "return" || bundle.is_back || toY <= fromY) {
          const loop = Math.max(50, Math.min(120, Math.abs(toX - fromX) * 0.4));
          d = `M ${fromX} ${fromY} C ${fromX + loop} ${fromY}, ${toX - loop} ${toY - 50}, ${toX} ${toY}`;
          midX = (fromX + toX) / 2 + loop / 2;
          midY = (fromY + toY) / 2 - 25;
        } else if (portDirection === "left") {
          const cdx = Math.min(100, Math.max(35, Math.abs(fromX - toX) * 0.35));
          const cdy = Math.max(40, (toY - fromY) * 0.4);
          if (toX >= fromX && toY >= fromCardBottomY - 20) {
            d = `M ${fromX} ${fromY} C ${fromX - cdx} ${fromY}, ${fromX - cdx} ${fromCardBottomY + 20}, ${toX} ${toY}`;
          } else {
            d = `M ${fromX} ${fromY} C ${fromX - cdx} ${fromY}, ${toX} ${toY - cdy}, ${toX} ${toY}`;
          }
          midX = (fromX + toX) / 2 - cdx * 0.3;
          midY = (fromY + toY) / 2;
        } else if (portDirection === "right") {
          const cdx = Math.min(100, Math.max(35, Math.abs(toX - fromX) * 0.35));
          const cdy = Math.max(40, (toY - fromY) * 0.4);
          if (toX <= fromX && toY >= fromCardBottomY - 20) {
            d = `M ${fromX} ${fromY} C ${fromX + cdx} ${fromY}, ${fromX + cdx} ${fromCardBottomY + 20}, ${toX} ${toY}`;
          } else {
            d = `M ${fromX} ${fromY} C ${fromX + cdx} ${fromY}, ${toX} ${toY - cdy}, ${toX} ${toY}`;
          }
          midX = (fromX + toX) / 2 + cdx * 0.3;
          midY = (fromY + toY) / 2;
        } else {
          const dy = Math.max(35, (toY - fromY) * 0.5);
          d = `M ${fromX} ${fromY} C ${fromX} ${fromY + dy}, ${toX} ${toY - dy}, ${toX} ${toY}`;
          midX = (fromX + toX) / 2;
          midY = (fromY + toY) / 2;
        }

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
        if (showLabels && !bundle.is_back) {
          const pill = document.createElement("div");
          pill.className = "edge-label-pill";
          pill.style.left = `${midX}px`;
          pill.style.top = `${midY}px`;
          pill.style.borderColor = strokeColor;

          if (bundle.edges.length > 1) {
            const targetTitle = (rawData.nodes[bundle.to_node_id] ? rawData.nodes[bundle.to_node_id].title : bundle.to_node_id.replace(/^cb:/, ''));
            pill.innerHTML = `<span style="color:${strokeColor}; font-weight:700;">×${bundle.edges.length} кнопок</span> <code>${escapeHtml(targetTitle)}</code>`;
          } else {
            pill.innerHTML = `<span style="color:${strokeColor}">${escapeHtml(firstEdge.button_text)}</span> <code>${escapeHtml(firstEdge.callback_data)}</code>`;
          }

          pill.addEventListener("mouseenter", () => highlightEdgeBranch(bundle.from_node_id, firstEdge.button_text));
          pill.addEventListener("mouseleave", () => resetEdgeHighlights());
          pill.addEventListener("click", () => {
            pulseEdgeBranch(bundle.from_node_id, bundle.to_node_id, firstEdge.button_text);
            focusOnCard(bundle.to_node_id, 700);
          });

          labelsContainer.appendChild(pill);
        }
      }
    }

    function drawDirectArrow(fromId, toId, text, cb, color, isBack) {
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
      if (!portEl) {
        portEl = document.createElement("div");
        portEl.className = "card-edge-port port-down";
        portEl.style.color = color;
        portEl.style.backgroundColor = color;
        portEl.style.left = "50%";
        fromCard.appendChild(portEl);
      }
      const topPort = toCard.querySelector(".card-top-port");
      if (topPort) {
        topPort.style.backgroundColor = color;
        topPort.style.color = color;
      }

      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      const d = `M ${fromX} ${fromY} C ${fromX} ${fromY + 50}, ${toX} ${toY - 50}, ${toX} ${toY}`;
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

      if (showLabels) {
        const pill = document.createElement("div");
        pill.className = "edge-label-pill";
        pill.style.left = `${(fromX + toX) / 2}px`;
        pill.style.top = `${(fromY + toY) / 2}px`;
        pill.style.borderColor = color;
        pill.innerHTML = `<span style="color:${color}">${escapeHtml(text)}</span> <code>${escapeHtml(cb)}</code>`;
        pill.addEventListener("mouseenter", () => highlightEdgeBranch(fromId, text));
        pill.addEventListener("mouseleave", () => resetEdgeHighlights());
        pill.addEventListener("click", () => {
          pulseEdgeBranch(fromId, toId, text);
          focusOnCard(toId, 700);
        });
        labelsContainer.appendChild(pill);
      }
    }

    function showTempTargetArrow(fromId, btnText) {
      removeTempTargetArrow();
      const edge = rawData.edges.find(e => 
        e.from_node_id === fromId && 
        (e.button_text === btnText || (btnText && e.button_text && btnText.includes(e.button_text)))
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

      const toX = toPos.x + CARD_W / 2;
      const toY = toPos.y;

      let fromX = fromPos.x + CARD_W / 2;
      let fromY = fromPos.y + (fromCard.offsetHeight || CARD_H);
      const btnEl = Array.from(fromCard.querySelectorAll(".tg-btn")).find(b => b.dataset.btnText === btnText);
      if (btnEl) {
        let cur = btnEl;
        let offLeft = 0;
        let offTop = 0;
        while (cur && cur !== fromCard) {
          offLeft += cur.offsetLeft;
          offTop += cur.offsetTop;
          cur = cur.offsetParent;
        }
        const bH = btnEl.offsetHeight || 34;
        const btnCenterY = offTop + bH / 2;
        const rowEl = btnEl.closest(".tg-row");
        const rowButtons = rowEl ? Array.from(rowEl.querySelectorAll(".tg-btn")) : [btnEl];
        const btnIdxInRow = rowButtons.indexOf(btnEl);
        const isLeftCol = (rowButtons.length > 1 && btnIdxInRow === 0);
        const isRightCol = (rowButtons.length > 1 && btnIdxInRow === rowButtons.length - 1);
        const toCenterX = toPos.x + CARD_W / 2;
        const fromCardCenterX = fromPos.x + CARD_W / 2;
        const fromCardBottom = fromPos.y + (fromCard.offsetHeight || CARD_H);
        const isDirectlyBelow = (toY >= fromCardBottom - 50 && Math.abs(toCenterX - fromCardCenterX) <= CARD_W * 0.85);

        if (isDirectlyBelow) {
          fromX = fromPos.x + (isLeftCol ? CARD_W * 0.35 : (isRightCol ? CARD_W * 0.65 : CARD_W * 0.5));
          fromY = fromCardBottom;
        } else if (isLeftCol) {
          fromX = fromPos.x;
          fromY = fromPos.y + btnCenterY;
        } else if (isRightCol) {
          fromX = fromPos.x + CARD_W;
          fromY = fromPos.y + btnCenterY;
        } else {
          fromX = fromPos.x + offLeft + (btnEl.offsetWidth || 140) / 2;
          fromY = fromCardBottom;
        }
      }

      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      let d;
      if (toY <= fromY) {
        const loop = 80;
        d = `M ${fromX} ${fromY} C ${fromX - loop} ${fromY - 50}, ${toX + loop} ${toY + 50}, ${toX} ${toY}`;
      } else {
        const dy = Math.max(30, (toY - fromY) * 0.5);
        d = `M ${fromX} ${fromY} C ${fromX + 40} ${fromY + dy}, ${toX} ${toY - dy}, ${toX} ${toY}`;
      }

      path.setAttribute("d", d);
      path.setAttribute("class", "flow-edge back highlighted edge-pulse");
      path.setAttribute("stroke", isUtil ? "#ef4444" : "#94a3b8");
      path.setAttribute("stroke-width", "3.6");
      path.setAttribute("stroke-dasharray", "6, 4");
      path.setAttribute("fill", "none");
      path.setAttribute("marker-end", isUtil ? "url(#arrow-dead)" : "url(#arrow-back)");
      
      const edgesGroup = document.getElementById("edges-group");
      if (edgesGroup) {
        edgesGroup.appendChild(path);
        tempReturnPath = path;
      }
      toCard.classList.add("highlighted");
    }

    function removeTempTargetArrow() {
      if (tempReturnPath && tempReturnPath.parentNode) {
        tempReturnPath.parentNode.removeChild(tempReturnPath);
        tempReturnPath = null;
      }
    }
    const removeTempReturnArrow = removeTempTargetArrow;

    setTimeout(renderConnectors, 60);
    setTimeout(renderConnectors, 250);
    window.addEventListener("load", renderConnectors);

    function pulseEdgeBranch(fromId, toId, btnText) {
      highlightEdgeBranch(fromId, btnText);
      for (const p of renderedEdgePaths) {
        if ((p.dataset.from === fromId && p.dataset.to === toId) || (p.dataset.from === fromId && p.dataset.btn === btnText)) {
          p.classList.add("edge-pulse");
          setTimeout(() => p.classList.remove("edge-pulse"), 1400);
        }
      }
    }

    function highlightEdgeBranch(fromId, btnText) {
      for (const p of renderedEdgePaths) {
        let match = false;
        if (p.dataset.from === fromId) {
          if (p.dataset.btn === btnText) {
            match = true;
          } else if (p.dataset.buttonList) {
            try {
              const list = JSON.parse(p.dataset.buttonList);
              if (Array.isArray(list) && list.includes(btnText)) match = true;
            } catch (_) {
              if (p.dataset.buttonList === btnText) match = true;
            }
          }
        }
        if (match) {
          p.classList.add("highlighted");
          const targetCard = nodeElements.get(p.dataset.to);
          if (targetCard) targetCard.classList.add("highlighted");
        } else {
          p.classList.add("dimmed");
        }
      }
    }

    function resetEdgeHighlights() {
      for (const p of renderedEdgePaths) {
        p.classList.remove("highlighted", "dimmed");
      }
      document.querySelectorAll(".tg-card.highlighted").forEach(c => c.classList.remove("highlighted"));
    }

    function highlightCard(nodeId) {
      document.querySelectorAll(".tg-card.highlighted").forEach(c => c.classList.remove("highlighted"));
      const card = nodeElements.get(nodeId);
      if (card) card.classList.add("highlighted");
    }

    function focusOnCard(nodeId, duration = 650) {
      const pos = nodePositions.get(nodeId);
      if (!pos) return;
      highlightCard(nodeId);
      const targetPanX = window.innerWidth / 2 - (pos.x + CARD_W / 2) * scale;
      const targetPanY = window.innerHeight / 2 - (pos.y + 160) * scale;
      smoothFlyTo(targetPanX, targetPanY, scale, duration);
    }

    // Search Input
    document.getElementById("search-input").addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase().trim();
      if (!q) return;

      for (const [id, node] of Object.entries(rawData.nodes)) {
        const titleMatch = (node.title || "").toLowerCase().includes(q) || id.toLowerCase().includes(q);
        const btnMatch = node.keyboard && node.keyboard.rows.some(r => r.some(b => (b.text || "").toLowerCase().includes(q) || (b.callback_data && b.callback_data.toLowerCase().includes(q))));
        if (titleMatch || btnMatch) {
          focusOnCard(id, 700);
          break;
        }
      }
    });

    // Type Filters Engine
    let currentFilterType = "all";
    const filterChips = document.querySelectorAll(".filter-chip");

    // Populate live counts
    const typeCounts = { all: Object.keys(rawData.nodes).length, command: 0, message: 0, callback: 0, popup: 0 };
    for (const [id, node] of Object.entries(rawData.nodes)) {
      const t = getNodeType(id, node);
      if (typeCounts[t] !== undefined) typeCounts[t]++;
    }
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

    filterChips.forEach(chip => {
      const type = chip.dataset.type;

      chip.addEventListener("mouseenter", () => {
        if (type === "all") return;
        document.querySelectorAll(".tg-card").forEach(c => {
          if (c.dataset.nodeType === type) {
            c.classList.add("type-highlighted");
            c.classList.remove("dimmed");
          } else {
            c.classList.remove("type-highlighted");
            c.classList.add("dimmed");
          }
        });
      });

      chip.addEventListener("mouseleave", () => {
        if (currentFilterType !== "all") {
          applyFilter(currentFilterType, false);
        } else {
          document.querySelectorAll(".tg-card").forEach(c => {
            c.classList.remove("type-highlighted", "dimmed");
          });
        }
      });

      chip.addEventListener("click", () => {
        filterChips.forEach(ch => ch.classList.remove("active"));
        chip.classList.add("active");
        currentFilterType = type;
        applyFilter(type, true);
      });
    });

    function applyFilter(type, shouldFly = false) {
      if (type === "all") {
        document.querySelectorAll(".tg-card").forEach(c => {
          c.classList.remove("dimmed", "type-highlighted");
        });
        if (shouldFly) centerOnStart(600);
        return;
      }

      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      let matchedCount = 0;

      document.querySelectorAll(".tg-card").forEach(c => {
        if (c.dataset.nodeType === type) {
          c.classList.remove("dimmed");
          c.classList.add("type-highlighted");
          matchedCount++;
          const nodeId = c.id.replace(/^card-/, "");
          const pos = nodePositions.get(nodeId);
          if (pos) {
            minX = Math.min(minX, pos.x);
            minY = Math.min(minY, pos.y);
            maxX = Math.max(maxX, pos.x + CARD_W);
            maxY = Math.max(maxY, pos.y + CARD_H);
          }
        } else {
          c.classList.add("dimmed");
          c.classList.remove("type-highlighted");
        }
      });

      if (shouldFly && matchedCount > 0 && isFinite(minX)) {
        const boxW = maxX - minX + 240;
        const boxH = maxY - minY + 240;
        const targetScale = Math.min(1.0, Math.max(0.15, Math.min(window.innerWidth / boxW, window.innerHeight / boxH)));
        const targetPanX = (window.innerWidth - (maxX + minX) * targetScale) / 2;
        const targetPanY = (window.innerHeight - (maxY + minY) * targetScale) / 2;
        smoothFlyTo(targetPanX, targetPanY, targetScale, 700);
      }
    }

    // Toggle Labels
    document.getElementById("btn-labels").addEventListener("click", function() {
      showLabels = !showLabels;
      this.classList.toggle("active", showLabels);
      renderConnectors();
    });

    // Toggle Back Edges
    document.getElementById("btn-back-edges").addEventListener("click", function() {
      showBackEdges = !showBackEdges;
      this.classList.toggle("active", showBackEdges);
      renderConnectors();
    });

    // Toggle Orphans
    let showOrphans = true;
    const btnOrphans = document.getElementById("btn-orphans");
    if (btnOrphans) {
      btnOrphans.addEventListener("click", function() {
        showOrphans = !showOrphans;
        this.classList.toggle("active", showOrphans);
        world.classList.toggle("hide-orphans", !showOrphans);
        renderConnectors();
      });
    }

    // Fit View
    function fitView(duration = 700) {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const [id, pos] of nodePositions.entries()) {
        if (!showOrphans && unvisited.includes(id)) continue;
        minX = Math.min(minX, pos.x);
        minY = Math.min(minY, pos.y);
        maxX = Math.max(maxX, pos.x + CARD_W);
        maxY = Math.max(maxY, pos.y + CARD_H);
      }
      if (!isFinite(minX)) {
        minX = 0; minY = 0; maxX = 1200; maxY = 800;
      }
      const worldW = maxX - minX + 240;
      const worldH = maxY - minY + 240;
      const targetScale = Math.min(1.0, Math.max(0.015, Math.min(window.innerWidth / worldW, window.innerHeight / worldH)));
      const targetPanX = (window.innerWidth - (maxX + minX) * targetScale) / 2;
      const targetPanY = 40;
      smoothFlyTo(targetPanX, targetPanY, targetScale, duration);
    }

    document.getElementById("btn-fit").addEventListener("click", () => fitView(700));

    window.addEventListener("resize", () => {
      renderConnectors();
    });

    // Initial View on load
    if (window.location.hash === "#fit") {
      fitView(0);
    } else {
      centerOnStart(0);
    }
