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
