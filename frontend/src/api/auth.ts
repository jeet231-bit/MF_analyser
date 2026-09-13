import { apiGet, apiSend } from "./client";

export interface SessionState {
  /** Whether a shared password is configured on the server. */
  required: boolean;
  authenticated: boolean;
  sessionHours: number;
}

export const getSession = () => apiGet<SessionState>("/auth/session");
export const login = (password: string) => apiSend<void>("POST", "/auth/login", { password });
export const logout = () => apiSend<void>("POST", "/auth/logout");

/** Fired by the API client when any request answers 401: the session has expired. */
export const UNAUTHENTICATED_EVENT = "mfa:unauthenticated";
