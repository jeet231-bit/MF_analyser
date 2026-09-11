import { apiGet } from "./client";

export interface DashboardConfig {
  display_name: string | null;
  sheet_scope: string[];
  number_grouping: "indian" | "international";
  number_decimals: number;
}

export function getConfig(): Promise<DashboardConfig> {
  return apiGet<DashboardConfig>("/config");
}
