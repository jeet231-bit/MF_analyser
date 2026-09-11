import { apiGet, apiSend, qs } from "./client";
import type { BusinessRule, LogicModel, SheetModel, SheetRole } from "./workbooks";

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  depth: number;
  data: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight: number;
  label: string | null;
}

export interface GraphResponse {
  level: "sheet" | "block" | "cell";
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export function getModel(versionId: string, sheet?: string): Promise<LogicModel> {
  return apiGet<LogicModel>(`/workbooks/${versionId}/model${qs({ sheet })}`);
}

export function getSheetGraph(versionId: string): Promise<GraphResponse> {
  return apiGet<GraphResponse>(`/workbooks/${versionId}/graph?level=sheet`);
}

export function getRules(versionId: string, sheet?: string, kind?: string): Promise<BusinessRule[]> {
  return apiGet<BusinessRule[]>(`/workbooks/${versionId}/rules${qs({ sheet, kind })}`);
}

export function setSheetRole(versionId: string, sheet: string, role: SheetRole, reason?: string): Promise<SheetModel> {
  return apiSend<SheetModel>("PATCH", `/workbooks/${versionId}/model/sheets/${encodeURIComponent(sheet)}`, {
    role,
    reason: reason ?? null,
  });
}
