// Generates Fig. 1 (architecture) and Fig. 2 (workflow) as standalone HTML/SVG
// pages; render.sh screenshots them to PNG with headless Chrome.
const fs = require("fs");

const C = {
  ink: "#0b0b0b", muted: "#52514e", line: "#3a3a38",
  box: "#e8f2fc", boxStroke: "#2a78d6",
  safe: "#e9f6ee", safeStroke: "#1a8a4a",
  ai: "#fdf0e8", aiStroke: "#d4622b",
  dec: "#fbf1d0", decStroke: "#9a7400",
  side: "#f3f2ee", sideStroke: "#898781",
  esc: "#fbe9e9", escStroke: "#c03535",
  term: "#e6e6e3",
};

function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

let T = 18, S = 14.5; // title / subtitle font size, set per figure
function box(x, y, w, h, title, sub, kind = "box", opts = {}) {
  const fill = C[kind] ?? C.box, stroke = C[kind + "Stroke"] ?? C.boxStroke;
  const lines = Array.isArray(sub) ? sub : sub ? [sub] : [];
  const gap = S * 1.3;
  const total = T * 1.2 + lines.length * gap;
  let ty = y + h / 2 - total / 2 + T * 0.95;
  let out = `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="10" fill="${fill}" stroke="${stroke}" stroke-width="2"${opts.dash ? ' stroke-dasharray="7 5"' : ""}/>`;
  out += `<text x="${x + w / 2}" y="${ty}" text-anchor="middle" font-size="${T}" font-weight="700" fill="${C.ink}">${esc(title)}</text>`;
  ty += T * 0.25;
  for (const l of lines) { ty += gap; out += `<text x="${x + w / 2}" y="${ty}" text-anchor="middle" font-size="${S}" fill="${C.muted}">${esc(l)}</text>`; }
  return out;
}

function diamond(cx, cy, w, h, lines) {
  const pts = `${cx},${cy - h / 2} ${cx + w / 2},${cy} ${cx},${cy + h / 2} ${cx - w / 2},${cy}`;
  let out = `<polygon points="${pts}" fill="${C.dec}" stroke="${C.decStroke}" stroke-width="2"/>`;
  const g = T * 1.15;
  let ty = cy - ((lines.length - 1) * g) / 2 + T * 0.35;
  for (const l of lines) { out += `<text x="${cx}" y="${ty}" text-anchor="middle" font-size="${T - 2}" font-weight="700" fill="${C.ink}">${esc(l)}</text>`; ty += g; }
  return out;
}

function terminal(cx, cy, label) {
  return `<ellipse cx="${cx}" cy="${cy}" rx="105" ry="32" fill="${C.term}" stroke="${C.line}" stroke-width="2"/>` +
    `<text x="${cx}" y="${cy + 8}" text-anchor="middle" font-size="${T}" font-weight="700" fill="${C.ink}">${label}</text>`;
}

// Polyline arrow through points [[x,y],...]
function arrow(pts, opts = {}) {
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join(" ");
  return `<path d="${d}" fill="none" stroke="${C.line}" stroke-width="2.2"${opts.dash ? ' stroke-dasharray="6 5"' : ""}${opts.noHead ? "" : ' marker-end="url(#ah)"'}/>`;
}

function label(x, y, text, opts = {}) {
  const anchor = opts.anchor ?? "middle";
  const fs = opts.fs ?? 17;
  const w = text.length * fs * 0.52 + 12;
  const bx = anchor === "middle" ? x - w / 2 : anchor === "start" ? x - 6 : x - w + 6;
  const g = opts.rotate ? ` transform="rotate(${opts.rotate} ${x} ${y - 5})"` : "";
  return `<g${g}>${opts.bg === false ? "" : `<rect x="${bx}" y="${y - fs}" width="${w}" height="${fs * 1.45}" rx="4" fill="#ffffff"/>`}` +
    `<text x="${x}" y="${y}" text-anchor="${anchor}" font-size="${fs}" font-style="italic" fill="${C.ink}">${esc(text)}</text></g>`;
}

function page(w, h, body) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:#fff}svg{display:block;font-family:Helvetica,Arial,sans-serif}</style></head><body>
<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${C.line}"/></marker></defs>
<rect width="${w}" height="${h}" fill="#fff"/>
${body}
</svg></body></html>`;
}

// ---------------- Fig. 1: architecture (portrait, sized for an A4 page) ----------------
function fig1() {
  T = 24; S = 19;
  const L = 140, W = 700, R = L + W, CX = L + W / 2; // main column
  const SL = 900, SW = 240, SCX = SL + SW / 2;       // side column
  let b = "";
  b += box(L, 30, W, 96, "Monitored Infrastructure", ["containerized services and their dependencies", "(e.g. frontend → api-service → redis)"]);
  b += box(L, 176, W, 120, "Prometheus: Metric Collection", ["application and container metrics (cAdvisor)", "dependency exporters · service-to-service latency"]);
  b += box(L, 346, 330, 120, "Rule-Based Detection", ["alert rules +", "Alertmanager"]);
  b += box(L + 370, 346, 330, 120, "ML Anomaly Detector", ["Isolation Forest + z-score", "(scikit-learn)"]);
  b += box(L, 516, W, 140, "Event Gateway (FastAPI)", ["common incident format · grouping", "dependency-aware context builder", "WebSocket channels · REST API"]);
  b += box(L, 716, 440, 140, "LLM Analysis Engine", ["structured, schema-validated plan:", "root cause · confidence ·", "recommended + fallback action"], "ai");
  b += box(L + 470, 716, 230, 140, "Runbooks", ["deterministic", "fallback when the", "LLM fails or is unsure"], "ai", { dash: true });
  b += box(L, 916, W, 140, "Policy / Safety Validator", ["allowlist · known target · confidence ≥ threshold", "cooldown · per-incident action limit", "re-check that the conditions are still active"], "safe");
  b += box(L, 1116, W, 120, "Action Executor (Docker SDK)", ["predefined actions only: reset faulty component,", "restart container, flush cache (approved)"], "safe");
  b += box(L, 1296, W, 96, "Verifier", ["re-evaluates the triggering conditions"], "safe");
  b += box(L, 1452, 320, 96, "Resolved", ["close incident ·", "record resolution time"]);
  b += box(L + 380, 1452, 320, 96, "Escalate to Human", ["after the maximum", "number of attempts"], "esc");
  b += box(SL, 516, SW, 140, "Incident Store", ["SQLite: every event,", "plan, action and", "verification result"], "side");
  b += box(SL, 716, SW, 140, "Web Dashboard", ["Next.js + TypeScript", "Tailwind CSS + Recharts", "incidents · approvals"], "side");
  b += box(SL, 916, SW, 140, "Human Approval", ["risky or low-confidence", "approve → execute", "reject → operator"], "dec");

  b += arrow([[CX, 126], [CX, 176]]);
  b += arrow([[L + 165, 296], [L + 165, 346]]);
  b += arrow([[L + 535, 296], [L + 535, 346]]);
  b += arrow([[L + 165, 466], [L + 165, 516]]);
  b += arrow([[L + 535, 466], [L + 535, 516]]);
  b += arrow([[L + 220, 656], [L + 220, 716]]);
  b += label(L + 232, 692, "WebSocket", { anchor: "start" });
  b += arrow([[L + 440, 786], [L + 470, 786]], { dash: true });
  b += arrow([[L + 220, 856], [L + 220, 916]]);
  b += arrow([[L + 585, 856], [L + 585, 916]]);
  b += arrow([[CX, 1056], [CX, 1116]]);
  b += label(CX, 1092, "permitted");
  b += arrow([[CX, 1236], [CX, 1296]]);
  b += arrow([[L + 160, 1392], [L + 160, 1452]]);
  b += label(L + 160, 1428, "resolved");
  b += arrow([[L + 540, 1392], [L + 540, 1452]]);
  b += label(L + 540, 1428, "attempts exhausted");
  // re-analysis loop
  b += arrow([[L, 1344], [80, 1344], [80, 786], [L, 786]]);
  b += label(62, 1065, "not resolved: re-analyze with history (max 3)", { rotate: -90, bg: false });
  // side column
  b += arrow([[R, 586], [SL, 586]], { dash: true });
  b += arrow([[SCX, 656], [SCX, 716]], { dash: true, noHead: true });
  b += arrow([[SCX, 856], [SCX, 916]], { dash: true, noHead: true });
  b += arrow([[R, 986], [SL, 986]]);
  b += arrow([[SCX, 1056], [SCX, 1166], [R, 1166]]);
  b += label(SCX, 1110, "approved");
  // the action changes the infrastructure, which Prometheus keeps monitoring
  b += arrow([[R, 1206], [1160, 1206], [1160, 78], [R, 78]], { dash: true });
  b += label(1182, 640, "action applied · monitoring and verification continue", { rotate: -90, bg: false });
  return page(1200, 1580, b);
}

// ---------------- Fig. 2: workflow ----------------
function fig2() {
  T = 23; S = 19;
  const CX = 600, BL = 340, BW = 520;
  let b = "";
  b += terminal(CX, 50, "START");
  b += box(BL, 100, BW, 90, "Monitor infrastructure", ["Prometheus collects application,", "container and dependency metrics"]);
  b += box(BL, 240, 250, 90, "Rule alert fires", ["threshold rule +", "Alertmanager"]);
  b += box(BL + 270, 240, 250, 90, "ML anomaly", ["persists for", "≥ 2 windows"]);
  b += box(BL, 380, BW, 100, "Build incident", ["group related events · settle wait", "dependency-aware context + history"]);
  b += box(BL, 530, BW, 80, "Send incident via WebSocket", ["to the LLM Analysis Engine"]);
  b += box(BL, 660, BW, 80, "LLM generates response plan", ["root cause · confidence · action · fallback"], "ai");
  b += diamond(CX, 830, 380, 130, ["LLM output valid", "and confident?"]);
  b += box(960, 790, 340, 80, "Runbook plan", ["deterministic fallback"], "ai");
  b += diamond(CX, 1020, 380, 130, ["Passes policy", "validator?"]);
  b += box(960, 980, 340, 80, "Human approval", ["risky or low confidence"], "dec");
  b += box(30, 980, 250, 80, "Escalate to human", ["no valid action"], "esc");
  b += box(BL, 1140, BW, 80, "Re-check, then execute", ["predefined action (Docker SDK)"], "safe");
  b += box(BL, 1270, BW, 80, "Verify after settle period", ["re-evaluate triggering conditions"], "safe");
  b += diamond(CX, 1440, 360, 130, ["Incident", "resolved?"]);
  b += diamond(1130, 1440, 320, 130, ["Attempts", "< max (3)?"]);
  b += box(960, 1250, 340, 90, "Re-analyze", ["attempt + 1 ·", "previous actions included"], "ai");
  b += box(BL, 1560, BW, 80, "Record resolution · store incident", []);
  b += box(980, 1560, 300, 80, "Escalate to human", ["operator"], "esc");
  b += terminal(CX, 1700, "END");

  b += arrow([[CX, 82], [CX, 100]]);
  b += arrow([[465, 190], [465, 240]]);
  b += arrow([[735, 190], [735, 240]]);
  b += arrow([[465, 330], [465, 380]]);
  b += arrow([[735, 330], [735, 380]]);
  b += arrow([[CX, 480], [CX, 530]]);
  b += arrow([[CX, 610], [CX, 660]]);
  b += arrow([[CX, 740], [CX, 765]]);
  // D1
  b += arrow([[CX + 190, 830], [960, 830]]);
  b += label(875, 820, "No");
  b += arrow([[1130, 870], [1130, 925], [CX, 925], [CX, 955]]);
  b += arrow([[CX, 895], [CX, 925]], { noHead: true });
  b += label(CX - 34, 918, "Yes");
  // D2
  b += arrow([[CX + 190, 1020], [960, 1020]]);
  b += label(875, 1008, "risky / unsure");
  b += arrow([[CX - 190, 1020], [280, 1020]]);
  b += label(345, 1008, "not allowed");
  b += arrow([[CX, 1085], [CX, 1140]]);
  b += label(CX - 48, 1118, "allowed");
  b += arrow([[1130, 1060], [1130, 1105], [820, 1105], [820, 1140]]);
  b += label(1130, 1092, "approved");
  b += arrow([[155, 1060], [155, 1700], [CX - 105, 1700]]);
  // execute → verify → D3
  b += arrow([[CX, 1220], [CX, 1270]]);
  b += arrow([[CX, 1350], [CX, 1375]]);
  b += arrow([[CX, 1505], [CX, 1560]]);
  b += label(CX - 36, 1538, "Yes");
  b += arrow([[CX + 180, 1440], [970, 1440]]);
  b += label(875, 1428, "No");
  b += arrow([[1130, 1375], [1130, 1340]]);
  b += label(1170, 1366, "Yes");
  b += arrow([[1300, 1295], [1360, 1295], [1360, 700], [860, 700]]);
  b += label(1382, 1000, "back to the LLM with history", { rotate: -90, bg: false });
  b += arrow([[1130, 1505], [1130, 1560]]);
  b += label(1096, 1538, "No");
  b += arrow([[CX, 1640], [CX, 1668]]);
  b += arrow([[1130, 1640], [1130, 1700], [CX + 105, 1700]]);
  return page(1400, 1760, b);
}

fs.writeFileSync("fig1.html", fig1());
fs.writeFileSync("fig2.html", fig2());
console.log("ok");
