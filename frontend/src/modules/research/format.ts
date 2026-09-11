import type { MeasureMeta } from "@/api/research";
import { formatNumber, type FormatSettings } from "@/lib/format";

/** Indian currency for amounts held in crore: ₹39.1 lakh crore, ₹86,785 crore, ₹45.3 crore. */
export function formatInrCrore(value: number, grouping: FormatSettings["grouping"] = "indian"): string {
  const sign = value < 0 ? "-" : "";
  const a = Math.abs(value);
  if (a >= 1e5) return `${sign}₹${formatNumber(a / 1e5, { grouping, decimals: 1 })} lakh crore`;
  if (a >= 100) return `${sign}₹${formatNumber(a, { grouping, decimals: 0 })} crore`;
  return `${sign}₹${formatNumber(a, { grouping, decimals: 1 })} crore`;
}

/**
 * Render one measure the way its config asks (mirrors the backend's fmt_measure): ranks and
 * quartiles as integers, percentages, Indian currency, otherwise the number with its unit.
 * The workbook's "--" (a null value with a raw text) renders as that text.
 */
export function formatMeasure(
  value: number | null | undefined,
  meta: Pick<MeasureMeta, "role" | "format" | "unit" | "decimals"> | undefined,
  settings: FormatSettings,
  raw?: unknown,
): string {
  if (value === null || value === undefined) return typeof raw === "string" ? raw : "—";
  if (!Number.isFinite(value)) return "—";
  if (!meta) return formatNumber(value, { grouping: settings.grouping, decimals: Number.isInteger(value) ? 0 : settings.decimals });
  if (meta.format === "inr_crore") return formatInrCrore(value, settings.grouping);
  const decimals = meta.decimals ?? (meta.format === "integer" || meta.role === "rank" || meta.role === "quartile" ? 0 : settings.decimals);
  if (meta.format === "percent") return `${formatNumber(value * 100, { grouping: settings.grouping, decimals })}%`;
  const text = formatNumber(value, { grouping: settings.grouping, decimals });
  return meta.unit ? `${text}${meta.unit}` : text;
}

/** "▲ 4" / "▼ 16" / "—" for a signed rank change (positive = moved up). */
export function formatRankDelta(delta: number | null | undefined): { text: string; direction: "up" | "down" | "flat" } {
  if (delta === null || delta === undefined) return { text: "—", direction: "flat" };
  if (delta > 0) return { text: `▲ ${delta}`, direction: "up" };
  if (delta < 0) return { text: `▼ ${-delta}`, direction: "down" };
  return { text: "—", direction: "flat" };
}

export function quartileLabel(q: number | null | undefined, unrankedValue = "--"): string {
  return q === null || q === undefined ? unrankedValue : `Q${q}`;
}

/** Columns worth a table: the primaries, then returns and secondary scores, capped for width. */
export function tableMeasures(measures: MeasureMeta[]): MeasureMeta[] {
  const primary = measures.filter((m) => m.primary);
  const returns = measures.filter((m) => m.role === "return" && !m.primary).slice(0, 4);
  const scores = measures.filter((m) => m.role === "score" && !m.primary).slice(0, 2);
  return [...primary, ...returns, ...scores];
}
