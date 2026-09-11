import type { CSSProperties, ReactNode } from "react";
import { Button } from "@/components";
import { cn } from "@/lib/cn";
import { formatCount } from "@/lib/format";
import { quartileLabel } from "./format";

/* Shared research-console pieces. Design from docs/research-console-mockup.html; colours only
   through tokens (bg-q1 … text-hero-ink); 20 px card radius (rounded-xl). */

const quartileClass: Record<number, string> = {
  1: "bg-q1 text-q1-ink",
  2: "bg-q2 text-q2-ink",
  3: "bg-q3 text-q3-ink",
  4: "bg-q4 text-q4-ink",
};

export function QuartilePill({ q, size = "sm", label, className }: { q: number | null | undefined; size?: "sm" | "md"; label?: string; className?: string }) {
  const known = q !== null && q !== undefined && quartileClass[q];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-sm font-heading font-bold",
        size === "sm" ? "px-2 py-0.5 text-[11.5px]" : "px-3 py-1 text-[12.5px]",
        known ? quartileClass[q as number] : "bg-hairline text-muted",
        className,
      )}
    >
      {label ?? quartileLabel(q)}
    </span>
  );
}

/** Flex-weighted Q1..Q4 segments with counts; the whole bar is one image for screen readers. */
export function QuartileBar({ counts, height = 34, className }: { counts: Record<string, number>; height?: number; className?: string }) {
  const parts = [1, 2, 3, 4].map((q) => ({ q, n: counts[String(q)] ?? 0 }));
  const total = parts.reduce((s, p) => s + p.n, 0);
  const label = `Quartile distribution: ${parts.map((p) => `Q${p.q} ${formatCount(p.n)} funds`).join(", ")}`;
  return (
    <div role="img" aria-label={label} className={cn("flex gap-0.5 overflow-hidden rounded-sm", className)} style={{ height }}>
      {parts.map((p) => (
        <span
          key={p.q}
          className={cn("tabular grid place-items-center font-heading text-[11.5px] font-bold", quartileClass[p.q])}
          style={{ flex: total > 0 ? Math.max(p.n, total * 0.04) : 1 }}
        >
          {p.n > 0 ? formatCount(p.n) : ""}
        </span>
      ))}
    </div>
  );
}

export function QuartileLegend() {
  return (
    <div className="flex flex-wrap gap-3 text-xs text-ink-2">
      {[
        ["bg-q1", "Q1 · top"],
        ["bg-q2", "Q2"],
        ["bg-q3", "Q3"],
        ["bg-q4", "Q4 · bottom"],
      ].map(([bg, text]) => (
        <span key={text} className="flex items-center gap-1.5">
          <span className={cn("h-2.5 w-2.5 rounded-[3px]", bg)} aria-hidden />
          {text}
        </span>
      ))}
    </div>
  );
}

export function PageHead({ title, sub, actions, back }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode; back?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {back}
        <h1 className="m-0 font-heading text-[25px] font-semibold tracking-[-0.02em] text-ink">{title}</h1>
        {sub && <div className="mt-1 text-[13px] text-muted">{sub}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function RCard({ title, sub, action, className, children, ...rest }: { title?: ReactNode; sub?: ReactNode; action?: ReactNode; className?: string; children: ReactNode; style?: CSSProperties }) {
  return (
    <section className={cn("min-w-0 rounded-xl border border-hairline bg-surface px-5 py-[19px]", className)} {...rest}>
      {(title || action) && (
        <header className="mb-3.5 flex items-start justify-between gap-2.5">
          <div>
            {title && <h3 className="m-0 font-heading text-[14.5px] font-semibold text-ink">{title}</h3>}
            {sub && <p className="m-0 mt-0.5 text-xs text-muted">{sub}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function LinkButton({ children, className, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" className={cn("bg-transparent p-0 text-left font-heading text-[12.5px] font-semibold text-accent hover:underline", className)} {...rest}>
      {children}
    </button>
  );
}

const toneClass = { up: "text-positive", down: "text-negative", muted: "text-muted", warn: "text-warning" } as const;

/** The research stat tile: small label, 27 px figure, one line under it. */
export function StatCard({ label, value, note, tone = "muted", className }: { label: string; value: ReactNode; note?: ReactNode; tone?: keyof typeof toneClass; className?: string }) {
  return (
    <div className={cn("rounded-xl border border-hairline bg-surface px-5 py-[19px]", className)}>
      <div className="text-[11.5px] font-medium text-muted">{label}</div>
      <div className="tabular mt-0.5 font-heading text-[27px] font-semibold leading-[1.15] tracking-[-0.02em] text-ink" data-testid="stat-value">
        {value}
      </div>
      {note && <div className={cn("mt-0.5 text-xs font-semibold", toneClass[tone])}>{note}</div>}
    </div>
  );
}

export function Hero({ eyebrow, big, bigSuffix, sub, children, className }: { eyebrow: string; big: ReactNode; bigSuffix?: ReactNode; sub?: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div
      className={cn("flex flex-col gap-4 rounded-xl border border-hero-line p-[22px] text-hero-ink", className)}
      style={{ background: "linear-gradient(152deg, var(--hero-a) 0%, var(--hero) 58%)" }}
    >
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-hero-muted">{eyebrow}</div>
        <div className="tabular font-heading text-[42px] font-semibold leading-none tracking-[-0.03em]">
          {big}
          {bigSuffix && <span className="text-xl font-medium text-hero-muted"> {bigSuffix}</span>}
        </div>
        {sub && <div className="mt-1 text-[12.5px] text-hero-muted">{sub}</div>}
      </div>
      {children}
    </div>
  );
}

export function HeroTiles({ tiles }: { tiles: { value: ReactNode; label: string }[] }) {
  return (
    <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${tiles.length}, minmax(0, 1fr))` }}>
      {tiles.map((t) => (
        <div key={t.label} className="rounded-[11px] bg-hero-tile px-3 py-[11px]">
          <div className="tabular font-heading text-[19px] font-semibold leading-[1.1]">{t.value}</div>
          <div className="mt-0.5 text-[10.5px] text-hero-muted">{t.label}</div>
        </div>
      ))}
    </div>
  );
}

/** Numbers in a computed sentence are set in ink so the eye lands on them. */
export function Narrative({ text, className, onHero = false }: { text: string | null | undefined; className?: string; onHero?: boolean }) {
  if (!text) return null;
  const parts = text.split(/(₹?\d[\d,.]*(?:\s?(?:lakh crore|crore|%))?)/g);
  return (
    <p className={cn("m-0 text-[13px] leading-[1.55]", onHero ? "text-hero-muted" : "text-ink-2", className)}>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <b key={i} className={cn("tabular font-semibold", onHero ? "text-hero-ink" : "text-ink")}>
            {p}
          </b>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </p>
  );
}

export function SectionHeader({ icon, title, sub }: { icon: string; title: string; sub?: string }) {
  return (
    <div className="mb-4 mt-[30px] flex items-center gap-[11px] first:mt-0">
      <div className="grid h-8 w-8 flex-none place-items-center rounded-[10px] bg-accent-soft text-[15px] text-accent" aria-hidden>
        {icon}
      </div>
      <div>
        <h2 className="m-0 font-heading text-xs font-bold uppercase tracking-[0.1em] text-ink">{title}</h2>
        {sub && <p className="m-0 mt-px text-xs text-muted">{sub}</p>}
      </div>
    </div>
  );
}

export function ConfidentialFooter({ text }: { text?: string | null }) {
  return (
    <p className="mt-10 border-t border-hairline pt-[18px] text-center text-[10.5px] font-semibold uppercase tracking-[0.09em] text-muted">
      {text ?? "Private & confidential"}
    </p>
  );
}

export function MoverRow({ name, context, right, delta, highlight, onClick }: { name: ReactNode; context?: ReactNode; right?: ReactNode; delta?: { text: string; direction: "up" | "down" | "flat" }; highlight?: boolean; onClick?: () => void }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      type={onClick ? "button" : undefined}
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-[11px] border-b border-hairline py-2.5 text-left last:border-b-0",
        highlight && "rounded-sm bg-accent-soft px-2",
        onClick && "hover:bg-surface-lifted",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className={cn("truncate text-[13px] font-semibold", highlight ? "text-accent" : "text-ink")}>{name}</div>
        {context && <div className="truncate text-[11.5px] text-muted">{context}</div>}
      </div>
      {right}
      {delta && (
        <div className={cn("tabular min-w-[44px] text-right text-[11.5px] font-bold", delta.direction === "up" ? "text-positive" : delta.direction === "down" ? "text-negative" : "text-muted")}>
          {delta.text}
        </div>
      )}
    </Tag>
  );
}

export function BarList({ rows, onSelect }: { rows: { key: string; label: string; value: number; valueLabel: string }[]; onSelect?: (key: string) => void }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 0);
  return (
    <div className="flex flex-col gap-[11px]">
      {rows.map((r) => (
        <div key={r.key} className="grid grid-cols-[1fr_auto] gap-1">
          {onSelect ? (
            <button type="button" onClick={() => onSelect(r.key)} className="truncate text-left text-[12.5px] text-ink-2 hover:text-accent">
              {r.label}
            </button>
          ) : (
            <span className="truncate text-[12.5px] text-ink-2">{r.label}</span>
          )}
          <span className="tabular text-[12.5px] font-semibold text-ink">{r.valueLabel}</span>
          <span className="col-span-full flex h-[7px] overflow-hidden rounded-sm border border-hairline bg-surface-lifted">
            <span className="block h-full rounded-[3px] bg-accent" style={{ width: max > 0 ? `${(Math.abs(r.value) / max) * 100}%` : "0%" }} />
          </span>
        </div>
      ))}
    </div>
  );
}

export function Chip({ pressed, children, onClick, className }: { pressed: boolean; children: ReactNode; onClick: () => void; className?: string }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "rounded-[7px] border px-[11px] py-1.5 text-xs font-semibold transition-colors",
        pressed ? "border-transparent bg-accent-soft text-accent" : "border-hairline bg-surface text-ink-2 hover:border-accent",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Chips({ label, options, value, onChange }: { label: string; options: { value: string; label: string }[]; value: string[]; onChange: (next: string[]) => void }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value.includes(o.value);
        return (
          <Chip key={o.value} pressed={on} onClick={() => onChange(on ? value.filter((v) => v !== o.value) : [...value, o.value])}>
            {o.label}
          </Chip>
        );
      })}
    </div>
  );
}

/** Bull/bear phases: the fund's bar over the category-average bar, per phase. */
export function PhaseBars({ phases, unit }: { phases: { group: string; groupLabel: string; label: string; value: number | null; categoryMean: number | null }[]; unit?: string | null }) {
  const max = Math.max(...phases.flatMap((p) => [Math.abs(p.value ?? 0), Math.abs(p.categoryMean ?? 0)]), 0);
  const fmt = (v: number | null) => (v === null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}${unit ?? ""}`);
  return (
    <div>
      <div className="mb-2.5 flex gap-3.5 text-xs text-ink-2">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-3 rounded-[2px] bg-q2" aria-hidden /> This fund
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-3 rounded-[2px] bg-muted opacity-50" aria-hidden /> Category average
        </span>
      </div>
      <ul className="m-0 list-none p-0">
        {phases.map((p, i) => (
          <li key={`${p.group}-${i}`} className="grid grid-cols-[118px_1fr] items-center gap-3 py-[5px]" title={`${p.groupLabel} ${p.label}: fund ${fmt(p.value)}, category ${fmt(p.categoryMean)}`}>
            <div className="text-[11.5px] text-ink-2">
              <b className="block text-[10.5px] font-semibold uppercase tracking-[0.06em] text-muted">{p.groupLabel}</b>
              {p.label}
            </div>
            <div>
              <div className="flex h-[22px] items-center gap-0.5">
                <span className="h-[9px] rounded-[3px] bg-q2" style={{ width: max > 0 ? `${(Math.abs(p.value ?? 0) / max) * 100}%` : 0 }} />
                <span className="tabular ml-1.5 text-[11.5px] font-semibold text-ink">{fmt(p.value)}</span>
              </div>
              <div className="flex h-3.5 items-center gap-0.5">
                <span className="h-1.5 rounded-[3px] bg-muted opacity-45" style={{ width: max > 0 ? `${(Math.abs(p.categoryMean ?? 0) / max) * 100}%` : 0 }} />
                <span className="tabular ml-1.5 text-[11.5px] font-medium text-muted">{fmt(p.categoryMean)}</span>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start gap-2.5 rounded-r-[11px] border border-l-[3px] border-hairline border-l-accent bg-surface-lifted px-[15px] py-3 text-[12.5px] text-ink-2", className)}>
      <span aria-hidden>◆</span>
      <div>{children}</div>
    </div>
  );
}

/** The research map is absent or does not resolve: say what to fix and where. */
export function NotConfigured({ problems, onOpenAdmin }: { problems: string[]; onOpenAdmin?: () => void }) {
  return (
    <RCard title="Research views are not set up for this workbook" sub="The semantic map lives in dashboard.config.json under research; the platform reads it, never code.">
      <ul className="m-0 list-disc space-y-1 pl-5 text-[13px] text-ink-2">
        {problems.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
      {onOpenAdmin && (
        <Button className="mt-4" onClick={onOpenAdmin}>
          Open admin
        </Button>
      )}
    </RCard>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy="true" className="space-y-3">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-24 animate-pulse rounded-xl border border-hairline bg-surface" />
      ))}
    </div>
  );
}
