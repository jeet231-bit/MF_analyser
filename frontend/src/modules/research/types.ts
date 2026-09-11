import type { EntityQuery } from "@/api/research";

/** Cross-page navigation the research screens need; App.tsx wires them to its state. */
export interface ResearchActions {
  openFund: (key: string) => void;
  openFunds: (query?: EntityQuery) => void;
  openCategories: () => void;
  openMovement: () => void;
  openInsights: () => void;
  openAdmin: () => void;
  openVersions: () => void;
  openUpload: () => void;
}
