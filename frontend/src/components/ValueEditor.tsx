import { useState } from "react";
import type { CellValue } from "@/api/runs";
import { cn } from "@/lib/cn";
import { isoDateToSerial, serialToIsoDate } from "@/lib/format";

export interface ValueEditorProps {
  id?: string;
  label: string;
  type: string; // number | text | bool | date | empty | error
  value: CellValue;
  /** The value in the draft, if any; null when unchanged. */
  draft?: CellValue | null;
  onChange: (value: CellValue | null) => void;
  disabled?: boolean;
  className?: string;
}

/** Typed control for one input cell; edits go to the draft, invalid text never leaves the field. */
export function ValueEditor({ id, label, type, value, draft, onChange, disabled, className }: ValueEditorProps) {
  const current = draft ?? value;
  const [text, setText] = useState(() => toText(current, type));
  const [invalid, setInvalid] = useState(false);
  const [seen, setSeen] = useState(current);
  const changed = draft !== undefined && draft !== null && draft !== value;

  // Derived state: when the underlying value changes (a run, a reset), the field follows it.
  if (seen !== current) {
    setSeen(current);
    setText(toText(current, type));
    setInvalid(false);
  }

  const commit = (raw: string) => {
    const parsed = parse(raw, type);
    if (parsed === undefined) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    onChange(parsed === value ? null : parsed);
  };

  const base = cn(
    "w-full rounded-sm border bg-surface px-2 py-1 text-sm text-ink focus:border-accent focus:outline-none disabled:opacity-50",
    invalid ? "border-negative" : changed ? "border-accent" : "border-hairline",
    type === "number" && "tabular text-right",
    className,
  );

  if (type === "bool") {
    return (
      <select
        id={id}
        aria-label={label}
        disabled={disabled}
        value={String(Boolean(current))}
        onChange={(e) => onChange(e.target.value === "true" === value ? null : e.target.value === "true")}
        className={base}
      >
        <option value="true">TRUE</option>
        <option value="false">FALSE</option>
      </select>
    );
  }
  if (type === "date") {
    return (
      <input
        id={id}
        type="date"
        aria-label={label}
        disabled={disabled}
        value={typeof current === "number" ? (serialToIsoDate(current) ?? "") : ""}
        onChange={(e) => {
          const serial = e.target.value ? isoDateToSerial(e.target.value) : null;
          onChange(serial === value ? null : serial);
        }}
        className={base}
      />
    );
  }
  return (
    <input
      id={id}
      type="text"
      inputMode={type === "number" ? "decimal" : undefined}
      aria-label={label}
      aria-invalid={invalid || undefined}
      disabled={disabled}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => commit(text)}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit(text);
        if (e.key === "Escape") {
          setText(toText(current, type));
          setInvalid(false);
        }
      }}
      className={base}
    />
  );
}

function toText(v: CellValue, type: string): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "TRUE" : "FALSE";
  if (typeof v === "number") return type === "date" ? (serialToIsoDate(v) ?? String(v)) : String(v);
  return v;
}

/** undefined = invalid; null = cleared. */
function parse(raw: string, type: string): CellValue | undefined {
  const s = raw.trim();
  if (type === "number") {
    if (s === "") return null;
    const n = Number(s.replace(/,/g, ""));
    return Number.isFinite(n) ? n : undefined;
  }
  if (type === "text" || type === "empty" || type === "error") return s === "" ? null : s;
  return s;
}
