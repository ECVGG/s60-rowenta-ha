/* Map card for the s60_rowenta integration. No external dependencies. */
const TEXT = {
  es: { live: "En directo", replay: "Repetición", heat: "Mapa de calor", compare: "Comparar",
    start: "Iniciar", pause: "Pausar", dock: "Volver a base", fit: "Centrar", play: "Reproducir",
    stop: "Detener", empty: "Aún no hay mapas guardados", onlyA: "Solo A", onlyB: "Solo B",
    both: "Ambas", few: "Pocas veces", many: "Muchas veces", error: "No se pudo cargar el mapa",
    incident: "Incidencia", session: "Limpieza", zoomIn: "Acercar", zoomOut: "Alejar" },
  en: { live: "Live", replay: "Replay", heat: "Heat map", compare: "Compare",
    start: "Start", pause: "Pause", dock: "Return to dock", fit: "Fit", play: "Play",
    stop: "Stop", empty: "No saved maps yet", onlyA: "Only A", onlyB: "Only B",
    both: "Both", few: "Rarely", many: "Often", error: "Could not load the map",
    incident: "Incident", session: "Cleaning", zoomIn: "Zoom in", zoomOut: "Zoom out" },
};
const COLORS = { cleaned: "#82beff", obstacle: "#e65050", wall: "#5a5a5a", cliff: "#aa3caa",
  other: "#aaaaaa", path: "#2563c9", dock: "#28aa46", robot: "#ffbe00", a: "#e8833a",
  b: "#3c82e6", both: "#3fa45b", incident: "#d11f1f" };

class S60RowentaMapCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity || !config.entity.startsWith("vacuum.")) {
      throw new Error("Set 'entity' to your vacuum entity");
    }
    this._config = config;
    this._mode = "live";
    this._view = { zoom: 1, x: 0, y: 0 };
    this._pointers = new Map();
    this._shown = 0;
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find((id) => id.startsWith("vacuum."));
    return { entity: entity || "vacuum.robot" };
  }

  getCardSize() { return 8; }

  set hass(hass) {
    this._hass = hass;
    if (!this._root) this._build();
    const state = hass.states[this._config.entity];
    // Refetch when the robot reports something new, at most every 5 s
    const stamp = state ? `${state.state}|${state.last_updated}` : "";
    const due = Date.now() - (this._fetched || 0) >= (this._data?.active ? 5000 : 30000);
    if (!this._data || stamp !== this._stamp || due) {
      if (!this._loading && Date.now() - (this._fetched || 0) >= 5000) {
        this._stamp = stamp;
        this._load();
      }
    }
  }

  connectedCallback() {
    this._timer = setInterval(() => {
      if (this._hass && this._data?.active && !document.hidden) this._load();
    }, 10000);
    if (this._canvas) {
      this._observer = new ResizeObserver(() => this._draw());
      this._observer.observe(this._canvas);
    }
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    cancelAnimationFrame(this._frame);
    this._playing = false;
    this._observer?.disconnect();
  }

  get _t() { return TEXT[(this._hass?.language || "en").slice(0, 2)] || TEXT.en; }

  _el(tag, props = {}, parent) {
    const el = Object.assign(document.createElement(tag), props);
    if (parent) parent.appendChild(el);
    return el;
  }

  _button(label, parent, onClick) {
    const button = this._el("button", { type: "button", textContent: label }, parent);
    button.addEventListener("click", onClick);
    return button;
  }

  _build() {
    const t = this._t;
    this._root = this.attachShadow({ mode: "open" });
    this._el("style", { textContent: `
      ha-card, .card { display:block; padding:12px; background:var(--ha-card-background,var(--card-background-color,#fff)); color:var(--primary-text-color,#212121); }
      .row { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin:6px 0; }
      button, select { font:inherit; padding:6px 10px; border-radius:8px; border:1px solid var(--divider-color,#ccc); background:transparent; color:inherit; cursor:pointer; }
      button[aria-pressed="true"] { background:var(--primary-color,#03a9f4); color:var(--text-primary-color,#fff); }
      option { color:#212121; }
      canvas { width:100%; aspect-ratio:1/1; max-height:70vh; touch-action:none; display:block; border-radius:8px; background:var(--secondary-background-color,#f2f2f2); }
      input[type=range] { flex:1; min-width:120px; }
      .dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:4px; }
      [hidden] { display:none !important; }` }, this._root);
    const card = this._el(customElements.get("ha-card") ? "ha-card" : "div", { className: "card" }, this._root);

    const tabs = this._el("div", { className: "row" }, card);
    this._tabs = {};
    for (const mode of ["live", "replay", "heat", "compare"]) {
      this._tabs[mode] = this._button(t[mode], tabs, () => this._setMode(mode));
    }

    this._pickers = this._el("div", { className: "row" }, card);
    this._selectA = this._el("select", { title: `${t.session} A` }, this._pickers);
    this._selectB = this._el("select", { title: `${t.session} B` }, this._pickers);
    for (const select of [this._selectA, this._selectB]) {
      select.addEventListener("change", () => { this._resetReplay(); this._draw(); });
    }

    this._canvas = this._el("canvas", {}, card);
    this._bindGestures();
    this._observer = new ResizeObserver(() => this._draw());
    this._observer.observe(this._canvas);

    this._replayRow = this._el("div", { className: "row" }, card);
    this._playButton = this._button(t.play, this._replayRow, () => this._togglePlay());
    this._slider = this._el("input", { type: "range", min: 0, max: 0, value: 0 }, this._replayRow);
    this._slider.addEventListener("input", () => { this._playing = false; this._playButton.textContent = this._t.play; this._draw(); });

    this._legend = this._el("div", { className: "row" }, card);
    this._message = this._el("div", { className: "row" }, card);

    const actions = this._el("div", { className: "row" }, card);
    for (const [label, service] of [[t.start, "start"], [t.pause, "pause"], [t.dock, "return_to_base"]]) {
      this._button(label, actions, () => this._hass.callService("vacuum", service, { entity_id: this._config.entity }));
    }
    this._button("+", actions, () => this._zoom(1.4)).title = t.zoomIn;
    this._button("−", actions, () => this._zoom(1 / 1.4)).title = t.zoomOut;
    this._button(t.fit, actions, () => { this._view = { zoom: 1, x: 0, y: 0 }; this._draw(); });
    this._setMode("live");
  }

  async _load() {
    this._loading = true;
    this._fetched = Date.now();
    try {
      const data = await this._hass.callWS({ type: "s60_rowenta/map", entity_id: this._config.entity });
      const previous = this._data?.current;
      this._data = data;
      this._failed = false;
      this._fillSelects();
      const count = data.current.points.length;
      // Animate only the points added to the map already on screen
      if (previous && previous.id === data.current.id && count > this._shown) this._animate(count);
      else this._shown = count;
    } catch (err) {
      this._failed = true;
    } finally {
      this._loading = false;
      this._draw();
    }
  }

  _animate(target) {
    cancelAnimationFrame(this._frame);
    const from = this._shown;
    const began = performance.now();
    const step = (now) => {
      const progress = Math.min(1, (now - began) / 4000);
      this._shown = Math.round(from + (target - from) * progress);
      this._draw();
      if (progress < 1) this._frame = requestAnimationFrame(step);
    };
    this._frame = requestAnimationFrame(step);
  }

  _fillSelects() {
    for (const [index, select] of [this._selectA, this._selectB].entries()) {
      const chosen = select.value;
      select.replaceChildren(...this._data.sessions.map((s) => {
        const date = new Date(s.start);
        const label = Number.isNaN(date.getTime()) ? s.id : date.toLocaleString(this._hass.language, { dateStyle: "short", timeStyle: "short" });
        return new Option(label, s.id);
      }));
      if (this._data.sessions.some((s) => s.id === chosen)) select.value = chosen;
      else if (this._data.sessions[index]) select.value = this._data.sessions[index].id;
    }
  }

  _setMode(mode) {
    this._mode = mode;
    for (const [name, button] of Object.entries(this._tabs)) button.setAttribute("aria-pressed", String(name === mode));
    this._pickers.hidden = mode !== "replay" && mode !== "compare";
    this._selectB.hidden = mode !== "compare";
    this._replayRow.hidden = mode !== "replay";
    this._resetReplay();
    this._draw();
  }

  _session(select) { return this._data?.sessions.find((s) => s.id === select.value)?.points || []; }

  _resetReplay() {
    this._playing = false;
    if (!this._slider) return;
    this._playButton.textContent = this._t.play;
    const length = this._session(this._selectA).length;
    this._slider.max = length;
    this._slider.value = length;
  }

  _togglePlay() {
    this._playing = !this._playing;
    this._playButton.textContent = this._playing ? this._t.stop : this._t.play;
    if (!this._playing) return;
    const max = Number(this._slider.max);
    if (Number(this._slider.value) >= max) this._slider.value = 0;
    let position = Number(this._slider.value);
    let last = performance.now();
    const step = (now) => {
      if (!this._playing) return;
      // A whole cleaning plays in about 20 s
      position = Math.min(max, position + (max * (now - last)) / 20000);
      last = now;
      this._slider.value = Math.round(position);
      this._draw();
      if (position < max) requestAnimationFrame(step);
      else { this._playing = false; this._playButton.textContent = this._t.play; }
    };
    requestAnimationFrame(step);
  }

  _zoom(factor) {
    const zoom = Math.min(12, Math.max(0.5, this._view.zoom * factor));
    const ratio = zoom / this._view.zoom;
    this._view = { zoom, x: this._view.x * ratio, y: this._view.y * ratio };
    this._draw();
  }

  _bindGestures() {
    const canvas = this._canvas;
    const spread = () => { const [a, b] = [...this._pointers.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };
    canvas.addEventListener("wheel", (e) => { e.preventDefault(); this._zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15); }, { passive: false });
    canvas.addEventListener("pointerdown", (e) => {
      canvas.setPointerCapture(e.pointerId);
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    });
    canvas.addEventListener("pointermove", (e) => {
      const old = this._pointers.get(e.pointerId);
      if (!old) return;
      const before = this._pointers.size === 2 ? spread() : 0;
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (this._pointers.size === 2 && before) this._zoom(spread() / before);
      else if (this._pointers.size === 1) {
        this._view.x += e.clientX - old.x;
        this._view.y += e.clientY - old.y;
        this._draw();
      }
    });
    for (const name of ["pointerup", "pointercancel"]) canvas.addEventListener(name, (e) => this._pointers.delete(e.pointerId));
  }

  _category(type) {
    return Object.keys(this._data.types).find((name) => this._data.types[name].includes(type)) || "other";
  }

  _legendItems(items) {
    this._legend.replaceChildren(...items.map(([color, label]) => {
      const item = this._el("span");
      this._el("span", { className: "dot" }, item).style.background = color;
      item.append(label);
      return item;
    }));
  }

  _draw() {
    const canvas = this._canvas;
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    this._legend.replaceChildren();
    this._message.textContent = this._failed ? this._t.error : "";
    const data = this._data;
    if (!data) return;

    let points = [];
    if (this._mode === "live") points = data.current.points.slice(0, this._shown);
    else if (this._mode === "replay") points = this._session(this._selectA).slice(0, Number(this._slider.value));
    else if (this._mode === "compare") points = [...this._session(this._selectA), ...this._session(this._selectB)];
    else points = data.sessions.flatMap((s) => s.points);

    // The frame uses the whole map, so it does not jump during a replay
    const frame = this._mode === "live" ? data.current.points : this._mode === "replay" ? this._session(this._selectA) : points;
    if (!frame.length) { this._message.textContent = this._failed ? this._t.error : this._t.empty; return; }

    const bounds = [data.origin[0], data.origin[0], data.origin[1], data.origin[1]];
    for (const [x, y] of frame) {
      bounds[0] = Math.min(bounds[0], x); bounds[1] = Math.max(bounds[1], x);
      bounds[2] = Math.min(bounds[2], y); bounds[3] = Math.max(bounds[3], y);
    }
    const [minX, maxX, minY, maxY] = bounds;
    const cell = (Math.min(width / (maxX - minX + 5), height / (maxY - minY + 5))) * this._view.zoom;
    const px = (x) => width / 2 + this._view.x + (x - (minX + maxX) / 2) * cell;
    const py = (y) => height / 2 + this._view.y - (y - (minY + maxY) / 2) * cell;
    const square = (x, y, color) => { ctx.fillStyle = color; ctx.fillRect(px(x) - cell / 2, py(y) - cell / 2, cell + 0.5, cell + 0.5); };
    const circle = (x, y, radius, color) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(px(x), py(y), radius, 0, 7); ctx.fill(); };
    const visited = (list) => new Set(list.filter(([, , type]) => ["cleaned", "path"].includes(this._category(type))).map(([x, y]) => `${x},${y}`));

    if (this._mode === "heat") {
      const counts = new Map();
      for (const session of data.sessions) for (const key of visited(session.points)) counts.set(key, (counts.get(key) || 0) + 1);
      const max = Math.max(1, ...counts.values());
      const heat = (share) => `hsl(${Math.round(220 - 220 * share)} 80% 55%)`;
      for (const [key, count] of counts) square(...key.split(",").map(Number), heat(max === 1 ? 1 : (count - 1) / (max - 1)));
      this._legendItems([[heat(0), this._t.few], [heat(1), `${this._t.many} (${max})`]]);
    } else if (this._mode === "compare") {
      const a = visited(this._session(this._selectA)), b = visited(this._session(this._selectB));
      for (const key of new Set([...a, ...b])) square(...key.split(",").map(Number), a.has(key) && b.has(key) ? COLORS.both : a.has(key) ? COLORS.a : COLORS.b);
      this._legendItems([[COLORS.a, this._t.onlyA], [COLORS.b, this._t.onlyB], [COLORS.both, this._t.both]]);
    } else {
      for (const [x, y, type] of points) {
        const category = this._category(type);
        square(x, y, COLORS[category === "path" ? "cleaned" : category]);
      }
      const path = points.filter(([, , type]) => this._category(type) === "path");
      ctx.strokeStyle = COLORS.path;
      ctx.lineWidth = Math.max(1.5, cell / 5);
      ctx.lineJoin = ctx.lineCap = "round";
      ctx.beginPath();
      path.forEach(([x, y], i) => (i ? ctx.lineTo(px(x), py(y)) : ctx.moveTo(px(x), py(y))));
      ctx.stroke();
      const id = this._mode === "live" ? data.current.id : this._selectA.value;
      const marks = data.incidents.filter((i) => i.map_id === id && i.position);
      for (const mark of marks) circle(...mark.position, Math.max(4, cell * 0.6), COLORS.incident);
      if (marks.length) this._legendItems([[COLORS.incident, `${this._t.incident}: ${[...new Set(marks.map((m) => m.code))].join(", ")}`]]);
      const robot = path[path.length - 1];
      if (robot) {
        const size = Math.max(6, cell * 0.9);
        circle(robot[0], robot[1], size, COLORS.robot);
        const before = path.slice(0, -1).reverse().find(([x, y]) => x !== robot[0] || y !== robot[1]);
        if (before) {
          const angle = Math.atan2(-(robot[1] - before[1]), robot[0] - before[0]);
          ctx.strokeStyle = "#282828";
          ctx.beginPath();
          ctx.moveTo(px(robot[0]), py(robot[1]));
          ctx.lineTo(px(robot[0]) + Math.cos(angle) * size, py(robot[1]) + Math.sin(angle) * size);
          ctx.stroke();
        }
      }
    }

    // Dock
    const s = Math.max(6, cell * 0.9), x = px(data.origin[0]), y = py(data.origin[1]);
    ctx.fillStyle = COLORS.dock;
    ctx.beginPath();
    ctx.moveTo(x, y - s);
    for (const [dx, dy] of [[1, 0], [0.7, 0], [0.7, 0.8], [-0.7, 0.8], [-0.7, 0], [-1, 0]]) ctx.lineTo(x + dx * s, y + dy * s);
    ctx.fill();
  }
}

if (!customElements.get("s60-rowenta-map-card")) {
  customElements.define("s60-rowenta-map-card", S60RowentaMapCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "s60-rowenta-map-card", name: "Rowenta S60 Map", description: "Live map, replay, heat map and comparison" });
}
