/* meraki-usage-card: Sankey of today's internet usage (line \u2192 home \u2192 device \u2192 app) */
const MUC_VERSION = "0.1.1";

const DEVICE_COLORS = ["#4fc3f7", "#b39ddb", "#f06292", "#4db6ac", "#ffb74d", "#ff8a65",
  "#7986cb", "#aed581", "#e57373", "#9575cd", "#4dd0e1", "#dce775", "#a1887f", "#90a4ae",
  "#f48fb1", "#81c784", "#ba68c8", "#ffd54f", "#64b5f6", "#ff7043"];
const APP_COLORS = ["#26c6da", "#ef5350", "#ffca28", "#66bb6a", "#7e57c2", "#ec407a",
  "#26a69a", "#d4e157", "#ab47bc", "#42a5f5", "#ffa726"];
const LINE_COLORS = ["#ffb300", "#ef5350", "#42a5f5", "#ab47bc", "#66bb6a"];
const GREY = "#607d8b";

function fmt(b) {
  if (b >= 1e9) return (b / 1e9).toFixed(b >= 1e10 ? 0 : 1) + " GB";
  if (b >= 1e6) return Math.round(b / 1e6) + " MB";
  if (b >= 1e3) return Math.round(b / 1e3) + " KB";
  return Math.round(b) + " B";
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

class MerakiUsageCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("Set 'entity' to the Meraki usage sensor");
    this._config = { max_apps: 9, height: 460, days: 30, ...config };
    this._lastKey = null;
    this._stats = null;
    this._statsAt = 0;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  getCardSize() { return 10; }
  getGridOptions() { return { columns: "full", rows: "auto" }; }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    const key = st ? st.last_updated + st.state : "missing";
    if (Date.now() - this._statsAt > 15 * 60 * 1000) this._fetchStats();
    if (key === this._lastKey) return;
    this._lastKey = key;
    this._render();
  }

  async _fetchStats() {
    this._statsAt = Date.now();
    const days = this._config.days;
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    start.setDate(start.getDate() - (days - 1));
    try {
      const res = await this._hass.callWS({
        type: "recorder/statistics_during_period",
        start_time: start.toISOString(),
        statistic_ids: [this._config.entity],
        period: "day",
        types: ["change"],
        units: { data_size: "GB" },
      });
      this._stats = res[this._config.entity] || [];
    } catch (e) {
      this._stats = [];
    }
    this._render();
  }

  _model(a, total) {
    const maxApps = this._config.max_apps;
    // Column 0: internet lines
    let lines = (a.lines || []).map((l, i) => ({ name: l.name, v: l.down + l.up, color: LINE_COLORS[i % LINE_COLORS.length] }));
    if (!lines.length) lines = [{ name: "Internet", v: total, color: LINE_COLORS[0] }];
    lines = lines.filter((l) => l.v > 0);

    // Column 2: devices
    const devs = (a.devices || []).map((d, i) => ({
      name: d.name, v: d.down + d.up, down: d.down, up: d.up, apps: d.apps || [],
      color: DEVICE_COLORS[i % DEVICE_COLORS.length],
    }));
    const od = a.other_devices || {};
    if ((od.down || 0) + (od.up || 0) > 0)
      devs.push({ name: `Other devices (${od.count})`, v: od.down + od.up, down: od.down, up: od.up, apps: [], color: GREY, other: true });
    if ((a.not_broken_down || 0) > 0)
      devs.push({ name: "Not broken down", v: a.not_broken_down, apps: [], color: "#37474f", nbd: true });

    const lineSum = lines.reduce((s, l) => s + l.v, 0);
    const devSum = devs.reduce((s, d) => s + d.v, 0);
    const home = { name: "Home", v: Math.max(lineSum, devSum), color: "#eceff1" };

    // Column 3: apps (devices' app usage, scaled to device totals)
    const appTotals = new Map();
    const devApp = []; // [devIdx, appName, bytes]
    devs.forEach((d, di) => {
      if (d.nbd) return;
      let list = d.apps.map((x) => ({ ...x }));
      const s = list.reduce((t, x) => t + x.bytes, 0);
      if (s > d.v && s > 0) list.forEach((x) => (x.bytes *= d.v / s));
      const used = list.reduce((t, x) => t + x.bytes, 0);
      if (d.v - used > d.v * 0.01) list.push({ name: "Other apps", bytes: d.v - used });
      list.forEach((x) => {
        appTotals.set(x.name, (appTotals.get(x.name) || 0) + x.bytes);
        devApp.push([di, x.name, x.bytes]);
      });
    });
    const ranked = [...appTotals.entries()].filter(([n]) => n !== "Other apps").sort((p, q) => q[1] - p[1]);
    const keep = new Set(ranked.slice(0, maxApps).map(([n]) => n));
    const apps = ranked.slice(0, maxApps).map(([n, v], i) => ({ name: n, v, color: APP_COLORS[i % APP_COLORS.length] }));
    const otherApps = [...appTotals.entries()].filter(([n]) => !keep.has(n)).reduce((s, [, v]) => s + v, 0);
    if (otherApps > 0) apps.push({ name: "Other apps", v: otherApps, color: "#78909c" });
    const appIdx = new Map(apps.map((x, i) => [x.name, i]));
    const otherIdx = appIdx.get("Other apps");
    const merged = new Map();
    devApp.forEach(([di, n, b]) => {
      const ai = keep.has(n) ? appIdx.get(n) : otherIdx;
      const k = di + "|" + ai;
      merged.set(k, (merged.get(k) || 0) + b);
    });
    const devAppLinks = [...merged.entries()].map(([k, v]) => { const [s, t] = k.split("|").map(Number); return { s, t, v }; });

    return { lines, home, devs, apps, devAppLinks };
  }

  _sankey(m) {
    const W = 1000, H = this._config.height, NW = 12, PAD = 7;
    const X = [130, 370, 580, 790];
    const cols = [m.lines, [m.home], m.devs, m.apps];
    const total = m.home.v || 1;
    let k = Infinity;
    cols.forEach((c) => {
      const t = c.reduce((s, n) => s + n.v, 0);
      if (t > 0) k = Math.min(k, (H - PAD * Math.max(c.length - 1, 0)) / t);
    });
    if (!isFinite(k)) k = 0;
    this._info = {};
    cols.forEach((c, ci) => {
      const used = c.reduce((s, n) => s + Math.max(n.v * k, 2), 0) + PAD * (c.length - 1);
      let y = (H - used) / 2;
      c.forEach((n, i) => {
        n.key = `n${ci}_${i}`; n.x = X[ci]; n.y = y; n.h = Math.max(n.v * k, 2); n.out = 0; n.in = 0; y += n.h + PAD;
        let sub = `${fmt(n.v)} \u00b7 ${((n.v / total) * 100).toFixed(1)}% of today`;
        if (n.down != null && n.up != null) sub += `<br>\u2193 ${fmt(n.down)} &nbsp; \u2191 ${fmt(n.up)}`;
        if (n.nbd) sub += `<br>Counted on the uplinks, not tied to a client`;
        this._info[n.key] = { title: esc(n.name), sub, color: n.color };
      });
    });

    const path = (x0, y0, x1, y1, h, color, op, s, t, tip) => {
      const mx = (x0 + x1) / 2;
      return `<path class="lk" data-s="${s}" data-t="${t}" data-tip="${esc(tip)}" d="M${x0},${y0} C${mx},${y0} ${mx},${y1} ${x1},${y1} L${x1},${y1 + h} C${mx},${y1 + h} ${mx},${y0 + h} ${x0},${y0 + h} Z" fill="${color}" fill-opacity="${op}"/>`;
    };
    const band = (s, t, v, color) => {
      const h = v * k;
      if (h < 0.3) return "";
      const out = path(s.x + NW, s.y + s.out, t.x, t.y + t.in, h, color, 0.38, s.key, t.key,
        `${s.name} \u2192 ${t.name}|${fmt(v)} \u00b7 ${((v / total) * 100).toFixed(1)}%`);
      s.out += h; t.in += h;
      return out;
    };

    let links = "";
    m.lines.forEach((l) => (links += band(l, m.home, l.v, l.color)));
    m.devs.forEach((d) => (links += band(m.home, d, d.v, d.color)));
    const byDev = [...m.devAppLinks].sort((p, q) => p.s - q.s || p.t - q.t);
    const tOrder = [...byDev].sort((p, q) => p.t - q.t || p.s - q.s);
    const tOff = new Map();
    m.apps.forEach((a) => (a.in = 0));
    tOrder.forEach((l) => { const a = m.apps[l.t]; tOff.set(l, a.in); a.in += l.v * k; });
    byDev.forEach((l) => {
      const d = m.devs[l.s], a = m.apps[l.t];
      if (!d || !a) return;
      const h = l.v * k;
      if (h >= 0.3) links += path(d.x + NW, d.y + d.out, a.x, a.y + tOff.get(l), h, d.color, 0.32, d.key, a.key,
        `${d.name} \u2192 ${a.name}|${fmt(l.v)} \u00b7 ${((l.v / (d.v || 1)) * 100).toFixed(0)}% of ${d.name}`);
      d.out += h;
    });

    const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + "\u2026" : s);
    let nodes = "";
    cols.forEach((c, ci) => c.forEach((n) => {
      nodes += `<rect class="nd" data-n="${n.key}" x="${n.x}" y="${n.y}" width="${NW}" height="${n.h}" rx="2" fill="${n.color}"/>`;
      const big = n.h >= 14 || ci < 2;
      if (!big && n.h < 7) return;
      const fs = big ? 14 : 11;
      const left = ci === 0;
      const tx = left ? n.x - 8 : n.x + NW + 8;
      const label = ci >= 2 ? short(n.name, ci === 3 ? 22 : 26) : n.name;
      nodes += `<text class="lb" data-n="${n.key}" x="${tx}" y="${n.y + n.h / 2}" dy="0.35em" text-anchor="${left ? "end" : "start"}" font-size="${fs}"><tspan class="n">${esc(label)}</tspan> <tspan class="v">${fmt(n.v)}</tspan></text>`;
    }));

    const heads = ["INTERNET LINE", "HOME", "DEVICE", "APP"].map((t, i) =>
      `<text x="${X[i] + NW / 2}" y="-14" text-anchor="middle" class="head">${t}</text>`).join("");
    return `<svg viewBox="-10 -30 ${W + 10} ${H + 40}" preserveAspectRatio="xMidYMid meet">${heads}<g class="links">${links}</g>${nodes}</svg>`;
  }

  _bind() {
    const wrap = this.shadowRoot.querySelector(".sankey");
    if (!wrap) return;
    const svg = wrap.querySelector("svg");
    const tip = wrap.querySelector(".tip");
    let pinned = null;
    const clear = () => {
      svg.classList.remove("hl");
      svg.querySelectorAll(".on").forEach((e) => e.classList.remove("on"));
      tip.style.display = "none";
    };
    const show = (el, ev) => {
      svg.querySelectorAll(".on").forEach((e) => e.classList.remove("on"));
      svg.classList.add("hl");
      let title, sub, color;
      if (el.classList.contains("lk")) {
        el.classList.add("on");
        [el.dataset.s, el.dataset.t].forEach((n) => svg.querySelectorAll(`[data-n="${n}"]`).forEach((e) => e.classList.add("on")));
        [title, sub] = el.dataset.tip.split("|");
        color = el.getAttribute("fill");
      } else {
        const n = el.dataset.n;
        svg.querySelectorAll(`[data-n="${n}"]`).forEach((e) => e.classList.add("on"));
        svg.querySelectorAll(`.lk[data-s="${n}"], .lk[data-t="${n}"]`).forEach((p) => {
          p.classList.add("on");
          [p.dataset.s, p.dataset.t].forEach((o) => svg.querySelectorAll(`[data-n="${o}"]`).forEach((e) => e.classList.add("on")));
        });
        ({ title, sub, color } = this._info[n] || {});
      }
      tip.innerHTML = `<div class="tt"><span class="dot" style="background:${color}"></span>${title}</div><div class="ts">${sub}</div>`;
      tip.style.display = "block";
      const r = wrap.getBoundingClientRect();
      let x = ev.clientX - r.left + 14, y = ev.clientY - r.top + 14;
      if (x + tip.offsetWidth > r.width) x = ev.clientX - r.left - tip.offsetWidth - 14;
      if (y + tip.offsetHeight > r.height) y = ev.clientY - r.top - tip.offsetHeight - 14;
      tip.style.left = `${Math.max(0, x)}px`; tip.style.top = `${Math.max(0, y)}px`;
    };
    const target = (ev) => ev.target.closest(".lk, [data-n]");
    svg.addEventListener("mousemove", (ev) => { if (pinned) return; const el = target(ev); el ? show(el, ev) : clear(); });
    svg.addEventListener("mouseleave", () => { if (!pinned) clear(); });
    svg.addEventListener("click", (ev) => {
      const el = target(ev);
      if (!el || pinned === el) { pinned = null; clear(); return; }
      pinned = el; show(el, ev);
    });
  }

  _strip(todayGB) {
    const days = this._config.days;
    const map = new Map();
    (this._stats || []).forEach((r) => {
      const d = new Date(r.start);
      map.set(d.toDateString(), r.change);
    });
    const cells = [];
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - i);
      let v = map.get(d.toDateString());
      if (i === 0 && todayGB != null) v = todayGB;
      const has = v != null && v > 0;
      const val = has ? (v >= 10 ? Math.round(v) : v.toFixed(1)) : "\u2014";
      cells.push(`<div class="day ${i === 0 ? "today" : ""} ${has ? "has" : ""}" title="${d.toLocaleDateString()}${has ? ": " + v.toFixed(2) + " GB" : ""}"><span class="dn">${String(d.getDate()).padStart(2, "0")}</span><span class="dv">${val}</span></div>`);
    }
    return cells.join("");
  }

  _render() {
    if (!this._hass || !this.shadowRoot) return;
    const st = this._hass.states[this._config.entity];
    let body;
    if (!st) {
      body = `<div class="empty">Entity ${esc(this._config.entity)} not found</div>`;
    } else if (st.state === "unavailable" || st.state === "unknown") {
      body = `<div class="empty">Waiting for data from Meraki\u2026</div>`;
    } else {
      const a = st.attributes;
      const totalGB = parseFloat(st.state);
      const m = this._model(a, totalGB * 1e9);
      const upd = a.updated ? new Date(a.updated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
      const rows = m.devs.filter((d) => !d.nbd).map((d) => {
        const top = (d.apps || []).filter((x) => x.name !== "Other apps").slice(0, 3).map((x) => esc(x.name)).join(", ");
        return `<tr><td><span class="dot" style="background:${d.color}"></span>${esc(d.name)}</td><td>${fmt(d.down || 0)}</td><td>${fmt(d.up || 0)}</td><td class="apps">${top}</td></tr>`;
      }).join("");
      const nbd = (a.not_broken_down || 0) > 0
        ? `<div class="note">"Not broken down" is internet use the MX counted on its uplinks but couldn't tie to a client.</div>` : "";
      body = `
        <div class="sub">Internet lines: ${fmt(totalGB * 1e9)} today \u00b7 devices and apps since midnight \u00b7 updated ${esc(upd)}</div>
        <div class="sankey">${this._sankey(m)}<div class="tip"></div></div>
        ${nbd}
        <table><thead><tr><th>Device</th><th>\u2193 Down</th><th>\u2191 Up</th><th>Top apps</th></tr></thead><tbody>${rows}</tbody></table>
        <div class="sub">Last ${this._config.days} days \u00b7 GB per day</div>
        <div class="strip">${this._strip(totalGB)}</div>`;
    }
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        .title { font-size: 20px; font-weight: 600; color: var(--primary-text-color); }
        .sub { font-size: 12px; color: var(--secondary-text-color); margin: 2px 0 10px; }
        .sankey svg { width: 100%; height: auto; display: block; }
        .sankey text { fill: var(--primary-text-color); font-family: inherit; }
        .sankey text .v { fill: var(--secondary-text-color); font-size: 0.85em; }
        .sankey { position: relative; }
        .sankey .lk, .sankey .nd, .sankey .lb { cursor: pointer; transition: opacity .15s, fill-opacity .15s; }
        .sankey svg.hl .lk { fill-opacity: .07; }
        .sankey svg.hl .lk.on { fill-opacity: .6; }
        .sankey svg.hl .nd, .sankey svg.hl .lb { opacity: .25; }
        .sankey svg.hl .nd.on, .sankey svg.hl .lb.on { opacity: 1; }
        .tip { display: none; position: absolute; pointer-events: none; z-index: 2; background: var(--card-background-color, #1c1c1c); border: 1px solid var(--divider-color); border-radius: 8px; padding: 8px 10px; font-size: 12px; box-shadow: 0 4px 12px rgba(0,0,0,.35); max-width: 260px; }
        .tip .tt { font-weight: 600; color: var(--primary-text-color); margin-bottom: 2px; }
        .tip .ts { color: var(--secondary-text-color); line-height: 1.5; }
        .sankey text.head { fill: var(--secondary-text-color); font-size: 12px; letter-spacing: 1.5px; }
        .note { font-size: 12px; color: var(--secondary-text-color); background: var(--secondary-background-color); border-radius: 8px; padding: 8px 12px; margin: 10px 0; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; margin: 8px 0 16px; }
        th { text-align: left; font-weight: 500; color: var(--secondary-text-color); border-bottom: 1px solid var(--divider-color); padding: 6px 4px; }
        td { padding: 6px 4px; border-bottom: 1px solid var(--divider-color); color: var(--primary-text-color); }
        td:nth-child(2), td:nth-child(3) { font-weight: 600; white-space: nowrap; }
        td.apps { color: var(--secondary-text-color); }
        .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; }
        .strip { display: grid; grid-template-columns: repeat(15, 1fr); gap: 6px; }
        .day { border: 1px solid var(--divider-color); border-radius: 6px; padding: 4px 0; text-align: center; display: flex; flex-direction: column; opacity: .55; }
        .day.has { opacity: 1; border-color: #43a047; }
        .day.today { background: rgba(67,160,71,.15); }
        .dn { font-size: 10px; color: var(--secondary-text-color); }
        .dv { font-size: 15px; font-weight: 600; color: var(--primary-text-color); }
        .day.today .dv { color: #66bb6a; }
        .empty { padding: 24px; color: var(--secondary-text-color); }
      </style>
      <ha-card><div class="title">${esc(this._config.title || "Data usage today")}</div>${body}</ha-card>`;
    this._bind();
  }

  static getStubConfig() { return { entity: "sensor.meraki_data_usage_internet_usage_today" }; }
}

if (!customElements.get("meraki-usage-card")) {
  customElements.define("meraki-usage-card", MerakiUsageCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "meraki-usage-card", name: "Meraki Usage Sankey", description: "Today's internet usage by line, device and app" });
  console.info(`%c MERAKI-USAGE-CARD %c ${MUC_VERSION} `, "background:#00bceb;color:#fff", "");
}
