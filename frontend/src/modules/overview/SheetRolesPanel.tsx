import { useState } from "react";
import { setSheetRole } from "@/api/model";
import { SHEET_ROLES, type SheetModel, type SheetRole } from "@/api/workbooks";
import { DataTable, Pill, Select, type Column } from "@/components";
import { describeError } from "@/lib/useAsync";

const sourceTone = { heuristic: "neutral", config: "accent", override: "accent" } as const;
const sourceLabel = { heuristic: "inferred", config: "config", override: "you set this" } as const;

/**
 * The researcher's verification surface: one select per sheet, saved on change.
 * Changing a role calls the override endpoint and then asks the page to reload the model.
 */
export function SheetRolesPanel({
  versionId,
  sheets,
  onChanged,
}: {
  versionId: string;
  sheets: SheetModel[];
  onChanged: () => void;
}) {
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [local, setLocal] = useState<Record<string, SheetRole>>({});

  const change = async (sheet: SheetModel, role: SheetRole) => {
    setLocal((m) => ({ ...m, [sheet.name]: role }));
    setSaving(sheet.name);
    setError(null);
    try {
      await setSheetRole(versionId, sheet.name, role, "set on the overview page");
      onChanged();
    } catch (err) {
      setError(`${sheet.name}: ${describeError(err)}`);
      setLocal((m) => {
        const next = { ...m };
        delete next[sheet.name];
        return next;
      });
    } finally {
      setSaving(null);
    }
  };

  const columns: Column<SheetModel>[] = [
    { key: "name", header: "Sheet", render: (s) => <span className="font-medium">{s.name}</span> },
    {
      key: "role",
      header: "Role",
      width: "11rem",
      render: (s) => (
        <Select
          aria-label={`Role for ${s.name}`}
          value={local[s.name] ?? s.role}
          disabled={saving === s.name}
          onChange={(e) => void change(s, e.target.value as SheetRole)}
        >
          {SHEET_ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </Select>
      ),
    },
    {
      key: "source",
      header: "Source",
      render: (s) =>
        saving === s.name ? (
          <Pill tone="accent">saving…</Pill>
        ) : (
          <Pill tone={sourceTone[s.role_source]}>{sourceLabel[s.role_source]}</Pill>
        ),
    },
    { key: "formula_cells", header: "Formulas", numeric: true },
    { key: "input_cells", header: "Inputs", numeric: true },
    { key: "output_cells", header: "Outputs", numeric: true },
    {
      key: "flow",
      header: "Reads → feeds",
      render: (s) => (
        <span className="text-xs text-muted">
          {s.reads.length ? s.reads.join(", ") : "—"} → {s.feeds.length ? s.feeds.join(", ") : "—"}
        </span>
      ),
    },
    { key: "reason", header: "Why", render: (s) => <span className="text-xs text-muted">{s.role_reason ?? ""}</span> },
  ];

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted">
        Roles decide how sheets are grouped in the dashboard. Correct any that read wrong; your choice is stored with this version and survives re-interpretation.
      </p>
      {error && (
        <p role="alert" className="text-xs text-negative">
          {error}
        </p>
      )}
      <DataTable columns={columns} rows={sheets} rowKey={(s) => s.name} dense maxHeight="40rem" />
    </div>
  );
}
