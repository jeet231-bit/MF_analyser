import { createContext, useContext } from "react";
import { DEFAULT_FORMAT, type FormatSettings } from "./format";

/** Number grouping and decimals from dashboard.config.json, for every table and tile below. */
export const FormatContext = createContext<FormatSettings>(DEFAULT_FORMAT);

export function useFormat(): FormatSettings {
  return useContext(FormatContext);
}
