import { useRef, useState } from "react";
import { interpretWorkbook, uploadWorkbook } from "@/api/workbooks";
import { Button, EmptyState } from "@/components";
import { describeError } from "@/lib/useAsync";

/** Upload a master workbook copy and interpret it. Used by the empty state and the sidebar. */
export function UploadPanel({
  onBusy,
  onDone,
  compact = false,
}: {
  onBusy: (busy: boolean, label?: string) => void;
  onDone: (versionId: string) => void;
  compact?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);

  const run = async (file: File) => {
    setError(null);
    onBusy(true, "Uploading workbook");
    try {
      setStage(`Parsing ${file.name}… about a minute for a large master.`);
      const version = await uploadWorkbook(file);
      setStage("Interpreting formulas…");
      onBusy(true, "Interpreting workbook");
      await interpretWorkbook(version.id);
      onDone(version.id);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setStage(null);
      onBusy(false);
    }
  };

  const picker = (
    <>
      <input
        ref={input}
        type="file"
        accept=".xlsx,.xlsm"
        className="hidden"
        data-testid="upload-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void run(file);
          e.target.value = "";
        }}
      />
      <Button variant={compact ? "ghost" : "primary"} size={compact ? "sm" : "md"} onClick={() => input.current?.click()} disabled={stage !== null}>
        {compact ? "Upload new version" : "Choose an .xlsx file"}
      </Button>
    </>
  );

  if (compact) {
    return (
      <div className="space-y-1">
        {picker}
        {stage && <p className="text-[11px] text-muted">{stage}</p>}
        {error && (
          <p role="alert" className="text-[11px] text-negative">
            {error}
          </p>
        )}
      </div>
    );
  }

  return (
    <EmptyState
      title="No workbook yet"
      description={
        <>
          Save a copy of the master workbook (close it in Excel first) and upload it here. The analyser parses every cell, dedupes the formulas into templates and builds the sheet dependency graph.
          {stage && <span className="mt-1 block text-ink">{stage}</span>}
          {error && (
            <span role="alert" className="mt-1 block text-negative">
              {error}
            </span>
          )}
        </>
      }
      action={picker}
    />
  );
}
