import { createContext, useContext } from "react";

export interface AuthValue {
  /** True when the server has a shared password configured. */
  required: boolean;
  signOut: () => Promise<void>;
}

export const AuthContext = createContext<AuthValue>({ required: false, signOut: async () => undefined });

/** Whether the top bar should offer "Sign out", and how. */
export const useAuth = () => useContext(AuthContext);
