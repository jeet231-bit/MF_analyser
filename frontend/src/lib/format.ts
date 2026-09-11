export type Grouping = "indian" | "international";

/**
 * Format a number with either Indian (12,34,567.00) or international (1,234,567.00) grouping.
 * Non-finite values render as an em dash so tables never show "NaN".
 */
export function formatNumber(
  value: number | null | undefined,
  { grouping = "indian", decimals = 2 }: { grouping?: Grouping; decimals?: number } = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const locale = grouping === "indian" ? "en-IN" : "en-US";
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/** Whole-number counts: grouped, no decimals. */
export function formatCount(value: number | null | undefined, grouping: Grouping = "indian"): string {
  return formatNumber(value, { grouping, decimals: 0 });
}

export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(d);
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(d);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatSeconds(seconds: number): string {
  return seconds < 10 ? `${seconds.toFixed(1)} s` : `${Math.round(seconds)} s`;
}

export interface FormatSettings {
  grouping: Grouping;
  decimals: number;
}

export const DEFAULT_FORMAT: FormatSettings = { grouping: "indian", decimals: 2 };

/** Excel serial day number -> ISO date (1900 date system, with Excel's 1900 leap-year quirk). */
export function serialToIsoDate(serial: number): string | null {
  if (!Number.isFinite(serial)) return null;
  const days = Math.floor(serial) - (serial >= 61 ? 25569 : 25568);
  const d = new Date(days * 86_400_000);
  return Number.isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10);
}

export function isoDateToSerial(iso: string): number | null {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  const days = Math.round(d.getTime() / 86_400_000);
  return days + (days + 25569 >= 61 ? 25569 : 25568);
}

export type CellFormat = "general" | "number" | "integer" | "percent" | "date" | "text";

/**
 * Render one workbook value the way its column asks: dates from serials, percentages, integers,
 * fixed decimals, or General (numbers with up to `decimals` places, no trailing noise).
 */
export function formatCell(
  value: number | string | boolean | null | undefined,
  format: CellFormat = "general",
  settings: FormatSettings = DEFAULT_FORMAT,
  type?: string,
): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  if (typeof value === "string") return value;
  if (!Number.isFinite(value)) return "—";
  if (format === "date" || type === "date") return serialToIsoDate(value) ? formatDate(serialToIsoDate(value)!) : String(value);
  if (format === "percent") return `${formatNumber(value * 100, { grouping: settings.grouping, decimals: settings.decimals })}%`;
  if (format === "integer") return formatNumber(value, { grouping: settings.grouping, decimals: 0 });
  if (format === "number") return formatNumber(value, { grouping: settings.grouping, decimals: settings.decimals });
  if (Number.isInteger(value)) return formatNumber(value, { grouping: settings.grouping, decimals: 0 });
  return formatNumber(value, { grouping: settings.grouping, decimals: settings.decimals });
}

/** Signed change with direction: "+1.25" / "−0.40" / "0.00". Direction is derived from the sign. */
export function formatDelta(
  delta: number,
  settings: FormatSettings = DEFAULT_FORMAT,
  decimals?: number,
): { text: string; direction: "up" | "down" | "flat" } {
  const places = decimals ?? (Number.isInteger(delta) ? 0 : settings.decimals);
  const magnitude = formatNumber(Math.abs(delta), { grouping: settings.grouping, decimals: places });
  if (delta > 0) return { text: `+${magnitude}`, direction: "up" };
  if (delta < 0) return { text: `−${magnitude}`, direction: "down" };
  return { text: magnitude, direction: "flat" };
}
