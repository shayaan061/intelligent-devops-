"""Figures for the EmergIN 2027 paper.

Writes fig1_architecture, fig2_results (MTTD + MTTR) and fig2_mttr (MTTR only, Paper A) (one SVG each, sized for one IEEE
column: 3.5 in = 336 CSS px) and renders them to PNG with headless Chrome at
4x (about 380 dpi). Fig. 2 reads the per-scenario scores that
`run_eval.py score` writes (eval_stage*_by_scenario.csv).

    python3 docs/paper/build/figures.py <by_scenario.csv> [out_dir]
"""
import csv
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SCALE = 7          # 336 CSS px x 7 = 2352 px across one 3.38 in column: about 700 dpi (EmergIN asks for >= 600)
FONT = "'Times New Roman', Times, serif"

# Categorical slots 1-3 of the dataviz reference palette (validated all-pairs,
# light mode). B2 also gets a hatch so the bars survive grayscale printing.
SERIES = [("B1", "B1 rules + runbooks", "#2a78d6"),
          ("B2", "B2 rules + LLM", "#eb6834"),
          ("S", "S full system", "#1baf7a")]
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#d9d8d4", "#ffffff"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def page(svg, w, h):
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>"
            f"html,body{{margin:0;padding:0;background:{SURFACE};}}"
            f"svg{{display:block}}</style></head><body>"
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' "
            f"viewBox='0 0 {w} {h}' font-family=\"{FONT}\">{svg}</svg></body></html>")


def render(html_path, png_path, w, h):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--force-device-scale-factor={SCALE}", f"--window-size={w},{h}",
                    f"--screenshot={png_path}", "file://" + html_path],
                   check=True, capture_output=True, timeout=60)


# ---------------------------------------------------------------- Fig. 1

def arch_svg():
    W = 336
    out = []

    def box(x, y, w, h, title, sub="", fill="#e8f2fc", stroke="#2a78d6", dash=False):
        d = ' stroke-dasharray="4 3"' if dash else ""
        fill, stroke = SURFACE, "#3a3a38"      # black and white: no colour coding (28 Oct 2026)
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{fill}" '
                   f'stroke="{stroke}" stroke-width="1"{d}/>')
        cy = y + h / 2 + (-3 if sub else 3.5)
        out.append(f'<text x="{x + w / 2}" y="{cy}" text-anchor="middle" font-size="10.5" '
                   f'font-weight="700" fill="{INK}">{esc(title)}</text>')
        if sub:
            out.append(f'<text x="{x + w / 2}" y="{cy + 11}" text-anchor="middle" '
                       f'font-size="9.5" fill="{MUTED}">{esc(sub)}</text>')

    def arrow(x1, y1, x2, y2, label="", dash=False, lx=None, ly=None, anchor="start"):
        d = ' stroke-dasharray="3 2"' if dash else ""
        out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#3a3a38" '
                   f'stroke-width="1" marker-end="url(#ah)"{d}/>')
        if label:
            out.append(f'<text x="{lx if lx is not None else x1 + 4}" y="{ly if ly is not None else (y1 + y2) / 2 + 3}" '
                       f'font-size="9" font-style="italic" fill="{MUTED}" text-anchor="{anchor}">{esc(label)}</text>')

    out.append('<defs><marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" '
               'markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" '
               'fill="#3a3a38"/></marker></defs>')

    L, R = 22, 248          # main column (left edge, right edge)
    MW = R - L
    side_x, side_w = 256, 76
    safe = ("#e9f6ee", "#1a8a4a")
    ai = ("#fdf0e8", "#d4622b")
    grey = ("#f3f2ee", "#898781")

    box(L, 4, MW, 32, "Services + Prometheus", "frontend → api-service → redis")
    half = (MW - 8) / 2
    box(L, 52, half, 32, "Alert rules", "Alertmanager")
    box(L + half + 8, 52, half, 32, "ML detector", "z-score + iForest")
    arrow(L + half / 2, 36, L + half / 2, 52)
    arrow(L + half * 1.5 + 8, 36, L + half * 1.5 + 8, 52)

    box(L, 100, MW, 32, "Event gateway", "grouping · context · history")
    arrow(L + half / 2, 84, L + half / 2, 100)
    arrow(L + half * 1.5 + 8, 84, L + half * 1.5 + 8, 100)
    box(side_x, 100, side_w, 32, "Incident store", "SQLite", *grey)
    arrow(R, 116, side_x, 116, dash=True)

    box(L, 148, half, 32, "LLM analyzer", "Llama 3.1 8B", *ai)
    box(L + half + 8, 148, half, 32, "Runbooks", "fallback", *ai, dash=True)
    arrow(L + half / 2, 132, L + half / 2, 148)
    arrow(L + half, 164, L + half + 8, 164, dash=True)

    box(L, 196, MW, 32, "Policy validator", "allowlist · confidence · cooldown · limits", *safe)
    arrow(L + half / 2, 180, L + half / 2, 196)
    arrow(L + half * 1.5 + 8, 180, L + half * 1.5 + 8, 196)
    box(side_x, 196, side_w, 32, "Human", "risky actions", "#fbf1d0", "#9a7400")
    arrow(R, 212, side_x, 212)

    box(L, 244, MW, 32, "Executor", "reset · restart · flush (approved)", *safe)
    arrow(L + MW / 2, 228, L + MW / 2, 244, label="permitted", lx=L + MW / 2 + 4)
    # approval -> executor
    out.append(f'<polyline points="{side_x + side_w / 2},228 {side_x + side_w / 2},260 {R + 1},260" '
               f'fill="none" stroke="#3a3a38" stroke-width="1" marker-end="url(#ah)"/>')

    box(L, 292, MW, 32, "Verifier", "after 45 s: alerts and anomalies cleared?", *safe)
    arrow(L + MW / 2, 276, L + MW / 2, 292)

    bw = (MW - 8) / 2
    box(L, 344, bw, 26, "Resolved", "")
    box(L + bw + 8, 344, bw, 26, "Escalate to human", "", "#fbe9e9", "#c03535")
    arrow(L + bw / 2, 324, L + bw / 2, 344, label="yes", lx=L + bw / 2 + 4, ly=338)
    arrow(L + bw * 1.5 + 8, 324, L + bw * 1.5 + 8, 344, label="3rd attempt", lx=L + bw * 1.5 + 12, ly=338)
    # re-analysis loop on the left
    out.append(f'<polyline points="{L},308 8,308 8,116 {L - 1},116" fill="none" stroke="#3a3a38" '
               f'stroke-width="1" marker-end="url(#ah)"/>')
    out.append(f'<text x="5" y="212" font-size="9" font-style="italic" fill="{MUTED}" '
               f'text-anchor="middle" transform="rotate(-90 5 212)">not resolved: re-analyze</text>')
    return "".join(out), W, 374


# ---------------------------------------------------------------- Fig. 2

def results_svg(rows, panels=("mttd", "mttr")):
    W = 336
    data = {(r["system"], int(r["scenario"])): r for r in rows}
    scen = sorted({int(r["scenario"]) for r in rows})
    out = ['<defs><pattern id="hatch" patternUnits="userSpaceOnUse" width="3" height="3" '
           'patternTransform="rotate(45)"><rect width="3" height="3" fill="#eb6834"/>'
           '<line x1="0" y1="0" x2="0" y2="3" stroke="#ffffff" stroke-width="1"/></pattern></defs>']

    # legend
    x = 30
    for key, label, color in SERIES:
        fill = "url(#hatch)" if key == "B2" else color
        out.append(f'<rect x="{x}" y="4" width="10" height="8" fill="{fill}"/>')
        out.append(f'<text x="{x + 13}" y="11.5" font-size="10" fill="{INK}">{esc(label)}</text>')
        x += 13 + len(label) * 4.6 + 12

    def panel(top, metric, title, ymax, ticks):
        left, right, h = 30, 332, 108
        pw = right - left
        out.append(f'<text x="{left}" y="{top - 4}" font-size="10.5" font-weight="700" '
                   f'fill="{INK}">{esc(title)}</text>')
        for t in ticks:
            y = top + h - h * t / ymax
            out.append(f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="{GRID}" stroke-width="0.6"/>')
            out.append(f'<text x="{left - 3}" y="{y + 3}" font-size="9.5" text-anchor="end" '
                       f'fill="{MUTED}">{t}</text>')
        gw = pw / len(scen)
        bw, gap = 7.5, 1.5
        for i, s in enumerate(scen):
            gx = left + i * gw + (gw - (3 * bw + 2 * gap)) / 2
            for j, (key, _, color) in enumerate(SERIES):
                r = data.get((key, s))
                if not r or not r[metric]:
                    continue
                v = float(r[metric])
                bh = h * min(v, ymax) / ymax
                fill = "url(#hatch)" if key == "B2" else color
                out.append(f'<rect x="{gx + j * (bw + gap):.2f}" y="{top + h - bh:.2f}" '
                           f'width="{bw}" height="{bh:.2f}" fill="{fill}"/>')
            out.append(f'<text x="{left + i * gw + gw / 2:.2f}" y="{top + h + 11}" font-size="9.5" '
                       f'text-anchor="middle" fill="{MUTED}">{s}</text>')
        out.append(f'<line x1="{left}" y1="{top + h}" x2="{right}" y2="{top + h}" stroke="{MUTED}" stroke-width="0.8"/>')

    spec = {"mttd": ("mttd_mean_s", "Mean time to detect (s)", 250, [0, 50, 100, 150, 200, 250]),
            "mttr": ("mttr_mean_s", "Mean time to recover (s)", 300, [0, 100, 200, 300])}
    top = 34
    for p in panels:
        panel(top, *spec[p])
        top += 150
    out.append(f'<text x="{(30 + 332) / 2}" y="{top - 16}" font-size="10" text-anchor="middle" '
               f'fill="{INK}">Fault scenario</text>')
    return "".join(out), W, top - 12


def main():
    by_scenario = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "figures")
    os.makedirs(out_dir, exist_ok=True)
    with open(by_scenario, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["system"] in {"B1", "B2", "S"}]
    for name, (svg, w, h) in {"fig1_architecture": arch_svg(),
                              "fig2_results": results_svg(rows),
                              "fig2_mttr": results_svg(rows, panels=("mttr",))}.items():
        html = os.path.abspath(os.path.join(out_dir, name + ".html"))
        with open(html, "w") as f:
            f.write(page(svg, w, h))
        render(html, os.path.abspath(os.path.join(out_dir, name + ".png")), w, h)
        print("wrote", os.path.relpath(os.path.join(out_dir, name + ".png")))


if __name__ == "__main__":
    main()
