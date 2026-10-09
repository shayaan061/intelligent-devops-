"use client";

// One metric per chart (never two y-axes), one line per service in a fixed
// colour per service, crosshair tooltip listing every service at that time,
// a legend, and each line's current value beside the chart.
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { TooltipProps } from "recharts";

export const SERVICE_COLOR: Record<string, string> = {
  frontend: "var(--series-frontend)",
  "api-service": "var(--series-api)",
  redis: "var(--series-redis)",
};

type Point = { x: number; [service: string]: number | null };

interface Props {
  series: Record<string, [number, number | null][] | undefined>; // service -> [x, value]
  format: (v: number | null) => string;
  xFormat: (x: number) => string;
  threshold?: { value: number; label: string };
  height?: number;
  domainMax?: number;
  /** Upper bound the axis never needs to exceed (1 for fractions shown as %). */
  cap?: number;
}

/** Round an axis maximum up to 1, 2, 2.5 or 5 times a power of ten, so ticks are round numbers. */
function niceCeil(v: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  return ([1, 2, 2.5, 5, 10].find((m) => m * p >= v) ?? 10) * p;
}

function merge(series: Props["series"]): Point[] {
  const byX = new Map<number, Point>();
  for (const [svc, pts] of Object.entries(series)) {
    for (const [x, v] of pts ?? []) {
      const p = byX.get(x) ?? { x };
      p[svc] = v;
      byX.set(x, p);
    }
  }
  return [...byX.values()].sort((a, b) => a.x - b.x);
}

function ChartTooltip({ active, payload, label, format, xFormat }: TooltipProps<number, string> & {
  format: Props["format"]; xFormat: Props["xFormat"];
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line px-3 py-2 text-xs shadow-sm" style={{ background: "var(--tooltip-bg)" }}>
      <div className="mb-1 text-muted">{xFormat(Number(label))}</div>
      {payload.map((p) => (
        <div key={String(p.dataKey)} className="flex items-center gap-2">
          <span className="inline-block h-0.5 w-3" style={{ background: SERVICE_COLOR[String(p.dataKey)] }} />
          <span className="tabular font-semibold">{format(p.value as number | null)}</span>
          <span className="text-muted">{String(p.dataKey)}</span>
        </div>
      ))}
    </div>
  );
}

export function Legend({ services }: { services: string[] }) {
  return (
    <div className="flex flex-wrap gap-3 text-xs text-muted">
      {services.map((s) => (
        <span key={s} className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: SERVICE_COLOR[s] }} />
          {s}
        </span>
      ))}
    </div>
  );
}

export function ServiceLineChart({ series, format, xFormat, threshold, height = 160, domainMax, cap }: Props) {
  const data = merge(series);
  const services = Object.keys(series).filter((s) => series[s]?.some(([, v]) => v !== null));
  if (!services.length) {
    return <div className="flex items-center justify-center text-xs text-muted" style={{ height }}>no data</div>;
  }
  // Y range from the data, and always tall enough to show the alert threshold
  let max = 0;
  for (const p of data) for (const s of services) { const v = p[s]; if (typeof v === "number" && v > max) max = v; }
  if (threshold) max = Math.max(max, threshold.value);
  let yMax = domainMax ?? niceCeil(max > 0 ? max * 1.1 : 1);
  if (cap !== undefined && max <= cap) yMax = Math.min(yMax, cap);
  // Current value of each line, beside the chart, top to bottom in the same
  // order as the line ends, each keyed by its line colour (text stays ink)
  const latest = services
    .map((s) => {
      for (let i = data.length - 1; i >= 0; i--) {
        const v = data[i][s];
        if (typeof v === "number") return { s, v };
      }
      return { s, v: null as number | null };
    })
    .sort((a, b) => (b.v ?? -Infinity) - (a.v ?? -Infinity));

  return (
    <div className="flex items-stretch gap-2" style={{ height }}>
      <div className="min-w-0 flex-1">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} strokeWidth={1} />
          <XAxis dataKey="x" type="number" domain={["dataMin", "dataMax"]} tickFormatter={xFormat} tickCount={4}
            tickLine={false} axisLine={false} minTickGap={24} />
          <YAxis tickFormatter={(v) => format(v)} width={56} tickLine={false} axisLine={false} tickCount={5}
            domain={[0, yMax]} allowDataOverflow={false} />
          {threshold && (
            <ReferenceLine y={threshold.value} stroke="var(--axis)" strokeDasharray="4 4"
              label={{ value: threshold.label, position: "insideBottomLeft", fill: "var(--axis)", fontSize: 10, dy: -2 }} />
          )}
          <Tooltip content={<ChartTooltip format={format} xFormat={xFormat} />}
            cursor={{ stroke: "var(--axis)", strokeWidth: 1 }} isAnimationActive={false} />
          {services.map((s) => (
            <Line key={s} dataKey={s} stroke={SERVICE_COLOR[s]} strokeWidth={2} dot={false} connectNulls={false}
              isAnimationActive={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "rgb(var(--card))" }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
      </div>
      <div className="flex w-16 shrink-0 flex-col justify-center gap-1 pb-5 text-xs" aria-label="Current values">
        {latest.map(({ s, v }) => (
          <div key={s} className="flex items-center gap-1.5" title={s}>
            <span className="inline-block h-0.5 w-3 shrink-0 rounded" style={{ background: SERVICE_COLOR[s] }} />
            <span className="tabular font-semibold">{format(v)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Tiny single-series trend with no axes, for the service map. */
export function Sparkline({ points, color }: { points: (number | null)[]; color: string }) {
  const data = points.map((v, i) => ({ i, v }));
  if (!points.some((v) => v !== null)) return <div className="h-8" />;
  return (
    <div className="h-8">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
          <YAxis hide domain={[0, "auto"]} />
          <Line dataKey="v" stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
