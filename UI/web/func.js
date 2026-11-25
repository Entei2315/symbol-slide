(() => {
  "use strict";

  const STORAGE_KEY = "symbol_slide_progress_v1";
  const DRAG_THRESHOLD_PX = 18;
  const SLIDE_DURATION_MS = 160;
  const WIN_MODAL_DELAY_MS = 210;

  const DIRECTION_VECTORS = {
    U: [-1, 0],
    D: [1, 0],
    L: [0, -1],
    R: [0, 1],
  };

  const DIRECTION_NAMES = {
    U: "Up",
    D: "Down",
    L: "Left",
    R: "Right",
  };

  const SYMBOL_META = {
    diamond: {
      label: "Diamond",
      color: "#a33737",
      svg: `<polygon points="50,12 86,50 50,88 14,50" />`,
    },
    circle: {
      label: "Circle",
      color: "#2e786c",
      svg: `<circle cx="50" cy="50" r="32" />`,
    },
    star: {
      label: "Star",
      color: "#b37d27",
      svg: `<polygon points="50,10 61,37 90,39 67,58 75,87 50,71 25,87 33,58 10,39 39,37" />`,
    },
    cross: {
      label: "Cross",
      color: "#3e5585",
      svg: `<path d="M39,14 H61 V39 H86 V61 H61 V86 H39 V61 H14 V39 H39 Z" />`,
    },
    pentagon: {
      label: "Pentagon",
      color: "#6e4575",
      svg: `<polygon points="50,11 87,38 73,83 27,83 13,38" />`,
    },
    triangle: {
      label: "Triangle",
      color: "#517044",
      svg: `<polygon points="50,14 86,82 14,82" />`,
    },
  };

  const els = {
    levelSelect: document.getElementById("level-select"),
    prevBtn: document.getElementById("prev-level-btn"),
    nextBtn: document.getElementById("next-level-btn"),
    modeBadge: document.getElementById("mode-badge"),
    movesValue: document.getElementById("moves-value"),
    parValue: document.getElementById("par-value"),
    bestValue: document.getElementById("best-value"),
    liveStars: document.getElementById("live-stars"),
    undoBtn: document.getElementById("undo-btn"),
    resetBtn: document.getElementById("reset-btn"),
    hintBtn: document.getElementById("hint-btn"),
    board: document.getElementById("board"),
    boardGrid: document.getElementById("board-grid"),
    tileLayer: document.getElementById("tile-layer"),
    statusBanner: document.getElementById("status-banner"),
    victoryModal: document.getElementById("victory-modal"),
    victoryStars: document.getElementById("victory-stars"),
    victorySummary: document.getElementById("victory-summary"),
    modalReplayBtn: document.getElementById("modal-replay-btn"),
    modalNextBtn: document.getElementById("modal-next-btn"),
  };

  const state = {
    levels: [],
    currentIndex: 0,
    currentLevel: null,
    symbols: [],
    tiles: {},
    history: [],
    moves: 0,
    selectedSymbol: null,
    solved: false,
    hint: null,
    progress: loadProgress(),
    tileEls: new Map(),
    cellEls: new Map(),
    drag: null,
    winModalTimer: null,
  };

  function clearWinModalTimer() {
    if (state.winModalTimer !== null) {
      window.clearTimeout(state.winModalTimer);
      state.winModalTimer = null;
    }
  }

  function loadProgress() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  function saveProgress() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.progress));
    } catch {
      // Ignore storage failures in restricted contexts
    }
  }

  function cloneTiles(tiles) {
    const copy = {};
    for (const [sym, pos] of Object.entries(tiles)) {
      copy[sym] = [pos[0], pos[1]];
    }
    return copy;
  }

  function computeStars(moves, level) {
    const optimal = level.optimal_moves || level.par_moves || 1;
    const twoStarLimit =
      (level.star_thresholds && level.star_thresholds.two_star) ||
      optimal + Math.max(2, Math.ceil(optimal * 0.35));
    if (moves <= optimal) return 3;
    if (moves <= twoStarLimit) return 2;
    return 1;
  }

  function formatStars(count) {
    return "★".repeat(count) + "☆".repeat(3 - count);
  }

  function setStatus(message, tone = "") {
    els.statusBanner.textContent = message;
    els.statusBanner.className = "status-banner" + (tone ? ` ${tone}` : "");
  }

  function createSvg(symbol, isTarget = false) {
    const meta = SYMBOL_META[symbol] || SYMBOL_META.diamond;
    const fill = isTarget ? "none" : meta.color;
    const stroke = isTarget ? "#d7b97d" : "rgba(25, 20, 15, 0.35)";
    const strokeWidth = isTarget ? "6" : "3";
    return `
      <svg class="${isTarget ? "target-glyph" : "tile-svg"}" viewBox="0 0 100 100" aria-hidden="true">
        <g fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-linejoin="round">
          ${meta.svg}
        </g>
      </svg>
    `;
  }

  function populateLevelSelector() {
    els.levelSelect.innerHTML = "";
    state.levels.forEach((lvl, idx) => {
      const saved = state.progress[lvl.id];
      const stars = saved ? ` [${"★".repeat(saved.stars)}]` : "";
      const opt = document.createElement("option");
      opt.value = String(idx);
      opt.textContent = `${idx + 1}. ${lvl.name} (${lvl.rows}×${lvl.cols})${stars}`;
      els.levelSelect.appendChild(opt);
    });
    els.levelSelect.value = String(state.currentIndex);
  }

  function updateBoardSizing(level) {
    const maxDim = Math.max(level.rows, level.cols);
    const isNarrow = window.innerWidth <= 560;
    const cellSize = isNarrow
      ? maxDim >= 6
        ? 46
        : 54
      : maxDim >= 6
      ? 66
      : maxDim === 5
      ? 72
      : 82;
    const gap = isNarrow ? 4 : 6;
    els.board.style.setProperty("--rows", String(level.rows));
    els.board.style.setProperty("--cols", String(level.cols));
    els.board.style.setProperty("--cell-size", `${cellSize}px`);
    els.board.style.setProperty("--gap", `${gap}px`);
  }

  function buildBoardDOM(level) {
    updateBoardSizing(level);
    els.boardGrid.innerHTML = "";
    els.tileLayer.innerHTML = "";
    state.tileEls.clear();
    state.cellEls.clear();

    const wallSet = new Set((level.walls || []).map(([r, c]) => `${r},${c}`));
    const targetAtCell = new Map();
    for (const [sym, [r, c]] of Object.entries(level.targets)) {
      targetAtCell.set(`${r},${c}`, sym);
    }

    for (let r = 0; r < level.rows; r += 1) {
      for (let c = 0; c < level.cols; c += 1) {
        const key = `${r},${c}`;
        const cell = document.createElement("div");
        cell.className = "cell";
        if (wallSet.has(key)) {
          cell.classList.add("wall");
        } else {
          if (targetAtCell.has(key)) {
            const sym = targetAtCell.get(key);
            cell.classList.add("target");
            cell.dataset.targetSymbol = sym;
            cell.innerHTML = createSvg(sym, true);
          }
          cell.addEventListener("click", () => onCellClick(r, c));
        }
        els.boardGrid.appendChild(cell);
        state.cellEls.set(key, cell);
      }
    }

    state.symbols.forEach((sym, index) => {
      const tile = document.createElement("div");
      tile.className = "tile";
      tile.dataset.symbol = sym;
      tile.setAttribute("role", "button");
      tile.setAttribute("aria-label", `${SYMBOL_META[sym]?.label || sym} tile`);
      tile.innerHTML = `<span class="tile-badge">${index + 1}</span>${createSvg(sym, false)}`;

      tile.addEventListener("pointerdown", (e) => onTilePointerDown(e, sym));
      els.tileLayer.appendChild(tile);
      state.tileEls.set(sym, tile);
    });
  }

  function getBoardMetrics() {
    const cellSize = parseFloat(getComputedStyle(els.board).getPropertyValue("--cell-size")) || 76;
    const gap = parseFloat(getComputedStyle(els.board).getPropertyValue("--gap")) || 6;
    return { cellSize, gap, stride: cellSize + gap };
  }

  function render() {
    const level = state.currentLevel;
    if (!level) return;

    const { stride } = getBoardMetrics();

    for (const cell of state.cellEls.values()) {
      cell.classList.remove("hint-dest");
    }

    if (state.hint && state.hint.to_pos) {
      const destCell = state.cellEls.get(`${state.hint.to_pos[0]},${state.hint.to_pos[1]}`);
      if (destCell) destCell.classList.add("hint-dest");
    }

    for (const sym of state.symbols) {
      const el = state.tileEls.get(sym);
      const [r, c] = state.tiles[sym];
      const [tr, tc] = level.targets[sym];
      if (!state.drag || state.drag.symbol !== sym) {
        el.style.transform = `translate3d(${c * stride}px, ${r * stride}px, 0)`;
      }
      el.classList.toggle("selected", state.selectedSymbol === sym && !state.solved);
      el.classList.toggle("locked", r === tr && c === tc);
      el.classList.toggle("hint-source", Boolean(state.hint && state.hint.symbol === sym));
    }

    els.movesValue.textContent = String(state.moves);
    const par = level.par_moves || level.optimal_moves || "–";
    els.parValue.textContent = String(par);

    const saved = state.progress[level.id];
    els.bestValue.textContent = saved ? `${saved.bestMoves}` : "–";

    const projected = computeStars(Math.max(1, state.moves), level);
    els.liveStars.textContent = formatStars(state.moves === 0 ? 3 : projected);

    els.undoBtn.disabled = state.history.length === 0;
    els.prevBtn.disabled = state.currentIndex <= 0;
    els.nextBtn.disabled = state.currentIndex >= state.levels.length - 1;

    const isSingle = level.slide_mode === "single_step";
    els.modeBadge.textContent = isSingle ? "Single Step" : "Full Slide";
    els.modeBadge.classList.toggle("single-step", isSingle);
  }

  function loadLevel(index) {
    if (index < 0 || index >= state.levels.length) return;
    clearWinModalTimer();
    state.currentIndex = index;
    const level = state.levels[index];
    state.currentLevel = level;
    state.symbols = Object.keys(level.tiles).sort();
    state.tiles = cloneTiles(level.tiles);
    state.history = [];
    state.moves = 0;
    state.solved = false;
    state.hint = null;
    state.selectedSymbol = state.symbols[0] || null;

    els.victoryModal.classList.add("hidden");
    populateLevelSelector();
    buildBoardDOM(level);
    render();
    setStatus("Drag a tile or select one (1–6) and press Arrow keys to slide.");
  }

  function checkSolved() {
    const targets = state.currentLevel.targets;
    return state.symbols.every((sym) => {
      const pos = state.tiles[sym];
      const tgt = targets[sym];
      return pos[0] === tgt[0] && pos[1] === tgt[1];
    });
  }

  function computeDestination(symbol, direction) {
    const level = state.currentLevel;
    const [dr, dc] = DIRECTION_VECTORS[direction];
    let [r, c] = state.tiles[symbol];

    const walls = new Set((level.walls || []).map(([wr, wc]) => `${wr},${wc}`));
    const occupied = new Set();
    for (const [otherSym, [or, oc]] of Object.entries(state.tiles)) {
      if (otherSym !== symbol) occupied.add(`${or},${oc}`);
    }

    const isFree = (nr, nc) =>
      nr >= 0 &&
      nr < level.rows &&
      nc >= 0 &&
      nc < level.cols &&
      !walls.has(`${nr},${nc}`) &&
      !occupied.has(`${nr},${nc}`);

    if (level.slide_mode === "single_step") {
      if (isFree(r + dr, c + dc)) {
        r += dr;
        c += dc;
      }
    } else {
      while (isFree(r + dr, c + dc)) {
        r += dr;
        c += dc;
      }
    }
    return [r, c];
  }

  function attemptSlide(symbol, direction) {
    if (state.solved || !symbol || !DIRECTION_VECTORS[direction]) return false;

    const [fromR, fromC] = state.tiles[symbol];
    const [toR, toC] = computeDestination(symbol, direction);
    if (fromR === toR && fromC === toC) {
      setStatus(`${SYMBOL_META[symbol]?.label || symbol} cannot slide ${DIRECTION_NAMES[direction]}.`);
      return false;
    }

    state.history.push(cloneTiles(state.tiles));
    state.tiles[symbol] = [toR, toC];
    state.moves += 1;
    state.selectedSymbol = symbol;
    state.hint = null;

    if (checkSolved()) {
      state.solved = true;
      onLevelSolved();
    } else {
      setStatus(`Slid ${SYMBOL_META[symbol]?.label || symbol} ${DIRECTION_NAMES[direction]}.`);
    }

    render();
    return true;
  }

  function onLevelSolved() {
    const level = state.currentLevel;
    const stars = computeStars(state.moves, level);
    const existing = state.progress[level.id];
    if (!existing || state.moves < existing.bestMoves || stars > existing.stars) {
      state.progress[level.id] = {
        bestMoves: existing ? Math.min(existing.bestMoves, state.moves) : state.moves,
        stars: existing ? Math.max(existing.stars, stars) : stars,
      };
      saveProgress();
      populateLevelSelector();
    }

    const par = level.par_moves || level.optimal_moves || state.moves;
    els.victoryStars.textContent = formatStars(stars);
    els.victorySummary.textContent = `Solved "${level.name}" in ${state.moves} move${
      state.moves === 1 ? "" : "s"
    } (Par ${par}).`;
    els.modalNextBtn.style.display =
      state.currentIndex < state.levels.length - 1 ? "inline-flex" : "none";
    setStatus(`Solved in ${state.moves} moves!`, "hint");

    clearWinModalTimer();
    const solvedLevelId = level.id;
    state.winModalTimer = window.setTimeout(() => {
      state.winModalTimer = null;
      if (state.solved && state.currentLevel && state.currentLevel.id === solvedLevelId) {
        els.victoryModal.classList.remove("hidden");
      }
    }, Math.max(WIN_MODAL_DELAY_MS, SLIDE_DURATION_MS + 40));
  }

  function undoMove() {
    if (state.history.length === 0) return;
    clearWinModalTimer();
    state.tiles = state.history.pop();
    state.moves = Math.max(0, state.moves - 1);
    state.solved = false;
    state.hint = null;
    els.victoryModal.classList.add("hidden");
    setStatus("Undid last move.");
    render();
  }

  function resetLevel() {
    loadLevel(state.currentIndex);
    setStatus("Board reset.");
  }

  async function requestHint() {
    if (!state.currentLevel || state.solved) return;
    els.hintBtn.disabled = true;
    setStatus("Consulting the solver…");
    try {
      const resp = await fetch("/api/hint", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          level_id: state.currentLevel.id,
          tiles: state.tiles,
        }),
      });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const data = await resp.json();
      if (data.solved) {
        setStatus("Puzzle is already solved!");
        return;
      }
      if (!data.solvable || !data.next_move) {
        state.hint = null;
        render();
        setStatus(
          "No solution reachable from this position — try Undo or Reset.",
          "warn"
        );
        return;
      }

      state.hint = data.next_move;
      state.selectedSymbol = data.next_move.symbol;
      render();
      const label = SYMBOL_META[data.next_move.symbol]?.label || data.next_move.symbol;
      const dir = DIRECTION_NAMES[data.next_move.direction] || data.next_move.direction;
      setStatus(
        `Hint: Slide ${label} ${dir} (${data.remaining_moves} optimal move${
          data.remaining_moves === 1 ? "" : "s"
        } remaining).`,
        "hint"
      );
    } catch (err) {
      setStatus(`Hint unavailable: ${err.message}`, "warn");
    } finally {
      els.hintBtn.disabled = false;
    }
  }

  function onCellClick(r, c) {
    if (state.solved || !state.selectedSymbol) return;
    const [tr, tc] = state.tiles[state.selectedSymbol];
    if (r === tr && c === tc) return;
    if (r === tr) {
      attemptSlide(state.selectedSymbol, c > tc ? "R" : "L");
    } else if (c === tc) {
      attemptSlide(state.selectedSymbol, r > tr ? "D" : "U");
    }
  }

  function onTilePointerDown(event, symbol) {
    if (event.button !== 0 && event.pointerType === "mouse") return;
    state.selectedSymbol = symbol;
    if (state.solved) {
      render();
      return;
    }
    const el = event.currentTarget;
    const { stride } = getBoardMetrics();
    const [r, c] = state.tiles[symbol];
    el.classList.add("dragging");
    state.drag = {
      symbol,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      baseX: c * stride,
      baseY: r * stride,
      stride,
      lastDir: null,
      lastDist: 0,
      el,
    };
    el.setPointerCapture(event.pointerId);
    render();
  }

  window.addEventListener("pointermove", (event) => {
    const drag = state.drag;
    if (!drag || drag.pointerId !== event.pointerId) return;

    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    const horiz = Math.abs(dx) >= Math.abs(dy);
    const delta = horiz ? dx : dy;
    const absDelta = Math.abs(delta);

    if (absDelta < 3) {
      drag.lastDir = null;
      drag.lastDist = absDelta;
      drag.el.style.transform = `translate3d(${drag.baseX}px, ${drag.baseY}px, 0)`;
      return;
    }

    const dir = horiz ? (dx > 0 ? "R" : "L") : dy > 0 ? "D" : "U";
    const [r, c] = state.tiles[drag.symbol];
    const [toR, toC] = computeDestination(drag.symbol, dir);
    const cellsTravel = Math.abs(toR - r) + Math.abs(toC - c);
    const maxPx = cellsTravel * drag.stride;

    const clamped =
      maxPx > 0
        ? Math.min(absDelta, maxPx)
        : Math.min(absDelta * 0.18, 6);
    const signed = delta >= 0 ? clamped : -clamped;
    const ox = horiz ? signed : 0;
    const oy = horiz ? 0 : signed;

    drag.lastDir = dir;
    drag.lastDist = absDelta;
    drag.el.style.transform = `translate3d(${drag.baseX + ox}px, ${drag.baseY + oy}px, 0)`;
  });

  function finishDrag(event, commit) {
    const drag = state.drag;
    if (!drag || drag.pointerId !== event.pointerId) return;
    state.drag = null;
    drag.el.classList.remove("dragging");
    // Flush layout so transition from dragging -> 160ms glide/snap-back applies cleanly.
    void drag.el.offsetWidth;

    if (commit && drag.lastDist >= DRAG_THRESHOLD_PX && drag.lastDir) {
      const moved = attemptSlide(drag.symbol, drag.lastDir);
      if (!moved) render();
    } else {
      render();
    }
  }

  window.addEventListener("pointerup", (event) => finishDrag(event, true));
  window.addEventListener("pointercancel", (event) => finishDrag(event, false));

  window.addEventListener("keydown", (event) => {
    if (event.target && ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName)) {
      return;
    }

    const key = event.key;
    if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === "z") {
      event.preventDefault();
      undoMove();
      return;
    }

    if (key >= "1" && key <= "6") {
      const idx = Number(key) - 1;
      if (idx < state.symbols.length) {
        state.selectedSymbol = state.symbols[idx];
        render();
      }
      return;
    }

    if (key === "Tab" && state.symbols.length > 0) {
      event.preventDefault();
      const idx = Math.max(0, state.symbols.indexOf(state.selectedSymbol));
      const nextIdx = (idx + (event.shiftKey ? -1 : 1) + state.symbols.length) % state.symbols.length;
      state.selectedSymbol = state.symbols[nextIdx];
      render();
      return;
    }

    const keyToDir = {
      ArrowUp: "U",
      w: "U",
      W: "U",
      ArrowDown: "D",
      s: "D",
      S: "D",
      ArrowLeft: "L",
      a: "L",
      A: "L",
      ArrowRight: "R",
      d: "R",
      D: "R",
    };

    if (keyToDir[key]) {
      event.preventDefault();
      attemptSlide(state.selectedSymbol, keyToDir[key]);
      return;
    }

    if (key.toLowerCase() === "z") {
      undoMove();
    } else if (key.toLowerCase() === "r") {
      resetLevel();
    } else if (key.toLowerCase() === "h") {
      requestHint();
    }
  });

  window.addEventListener("resize", () => {
    if (state.currentLevel) {
      updateBoardSizing(state.currentLevel);
      render();
    }
  });

  els.levelSelect.addEventListener("change", () => {
    loadLevel(Number(els.levelSelect.value));
  });
  els.prevBtn.addEventListener("click", () => loadLevel(state.currentIndex - 1));
  els.nextBtn.addEventListener("click", () => loadLevel(state.currentIndex + 1));
  els.undoBtn.addEventListener("click", undoMove);
  els.resetBtn.addEventListener("click", resetLevel);
  els.hintBtn.addEventListener("click", requestHint);
  els.modalReplayBtn.addEventListener("click", resetLevel);
  els.modalNextBtn.addEventListener("click", () => loadLevel(state.currentIndex + 1));

  async function init() {
    try {
      const resp = await fetch("/api/levels");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const payload = await resp.json();
      state.levels = payload.levels || [];
      if (state.levels.length === 0) {
        setStatus("No levels found in levels.json.", "warn");
        return;
      }
      loadLevel(0);
    } catch (err) {
      setStatus(`Failed to load levels: ${err.message}`, "warn");
    }
  }

  init();
})();
