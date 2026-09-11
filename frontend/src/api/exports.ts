import { ApiError, apiGet, qs } from "./client";

export type ExportFormat = "xlsx" | "csv" | "pdf";

export interface ExportJob {
  id: string;
  run_id: string;
  format: string;
  status: "running" | "ok" | "failed";
  error: string | null;
  filename: string | null;
  created_at: string;
  finished_at: string | null;
}

export function runExportUrl(
  runId: string,
  format: ExportFormat,
  options: { scope?: "outputs" | "all" | "sheet"; sheet?: string; window?: string; formulas?: boolean; background?: "auto" | "true" | "false" } = {},
): string {
  return `/api/runs/${runId}/export${qs({
    format,
    scope: options.scope,
    sheet: options.sheet,
    window: options.window,
    formulas: options.formulas ? "true" : undefined,
    background: options.background,
  })}`;
}

export function diffExportUrl(baseId: string, targetId: string, format: "xlsx" | "csv"): string {
  return `/api/workbooks/${baseId}/diff/${targetId}/export${qs({ format })}`;
}

export function getExportJob(jobId: string): Promise<ExportJob> {
  return apiGet<ExportJob>(`/exports/${jobId}`);
}

/** Poll interval for background export jobs; tests shorten it. */
export const exportPolling = { ms: 1000 };

function filenameFrom(disposition: string | null): string | undefined {
  if (!disposition) return undefined;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (star) return decodeURIComponent(star[1]);
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1] : undefined;
}

/** Start a browser download without leaving the page. */
export function triggerDownload(href: string, filename?: string): void {
  const a = document.createElement("a");
  a.href = href;
  if (filename) a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * Fetch an export URL. A 200 is downloaded at once; a 202 is a background job that is polled
 * until it settles and then downloaded from its file URL. Errors surface as ApiError.
 */
export async function downloadExport(url: string, onStatus?: (text: string) => void): Promise<void> {
  onStatus?.("Preparing…");
  const response = await fetch(url, { headers: { Accept: "*/*" } });
  if (response.status === 202) {
    const job = (await response.json()) as ExportJob;
    onStatus?.("Export running in the background…");
    let latest = job;
    while (latest.status === "running") {
      await new Promise((resolve) => setTimeout(resolve, exportPolling.ms));
      latest = await getExportJob(job.id);
    }
    if (latest.status !== "ok") throw new ApiError(500, latest.error ?? "Export failed");
    triggerDownload(`/api/exports/${latest.id}/file`, latest.filename ?? undefined);
    onStatus?.("Download started");
    return;
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, detail);
  }
  const blob = await response.blob();
  const name = filenameFrom(response.headers.get("content-disposition"));
  const objectUrl = typeof URL.createObjectURL === "function" ? URL.createObjectURL(blob) : url;
  triggerDownload(objectUrl, name);
  if (objectUrl !== url) setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000);
  onStatus?.("Download started");
}
