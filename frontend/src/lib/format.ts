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

export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(d);
}
