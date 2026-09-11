import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import type { Series } from "@/api/views";
import { formatDate, formatNumber } from "@/lib/format";
import { useFormat } from "@/lib/FormatContext";

const STROKES = ["--accent", "--positive", "--warning", "--negative"];

function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** A quiet line chart for a dated series; colours come from the theme tokens, never literals. */
export function SeriesChart({ series, width = 720, height = 220 }: { series: Series; width?: number; height?: number }) {
  const settings = useFormat();
  const [theme, setTheme] = useState(0);
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme((n) => n + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  void theme;

  const data = series.columns[0].points.map(([x], i) => {
    const row: Record<string, string | number | null> = { x: String(x) };
    for (const col of series.columns) row[col.label] = col.points[i]?.[1] ?? null;
    return row;
  });
  const ink = cssVar("--muted") || undefined;
  const hairline = cssVar("--hairline") || undefined;

  return (
    <figure className="space-y-1">
      <LineChart width={width} height={height} data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
        <CartesianGrid stroke={hairline} vertical={false} />
        <XAxis
          dataKey="x"
          tick={{ fill: ink, fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: hairline }}
          tickFormatter={(v: string) => (series.x_type === "date" ? formatDate(v) : v)}
          minTickGap={48}
        />
        <YAxis
          tick={{ fill: ink, fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={56}
          tickFormatter={(v: number) => formatNumber(v, { grouping: settings.grouping, decimals: Math.abs(v) < 10 ? 2 : 0 })}
        />
        <Tooltip
          contentStyle={{ background: cssVar("--surface") || undefined, border: `1px solid ${hairline}`, borderRadius: 8, fontSize: 12 }}
          labelFormatter={(v) => (series.x_type === "date" ? formatDate(String(v)) : String(v))}
          formatter={(v) => (typeof v === "number" ? formatNumber(v, { grouping: settings.grouping, decimals: settings.decimals }) : String(v))}
        />
        {series.columns.map((col, i) => (
          <Line
            key={col.label}
            type="monotone"
            dataKey={col.label}
            stroke={cssVar(STROKES[i % STROKES.length]) || undefined}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        ))}
      </LineChart>
      <figcaption className="text-xs text-muted">
        {series.columns.map((c) => c.label).join(", ")} over {series.x_label ?? "time"} · {series.rows} rows
      </figcaption>
    </figure>
  );
}
