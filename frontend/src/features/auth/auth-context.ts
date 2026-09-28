import { createContext, useContext } from "react";
import type { Api, UserProfile } from "../../api/endpoints";

export type AuthState = {
  token: string | null;
  user: UserProfile | null;
  /** Calls bound to the current token; a 401 from any of them logs out. */
  api: Api | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

/** For pages behind <RequireAuth>, where the API is always available. */
export function useApi(): Api {
  const { api } = useAuth();
  if (!api) throw new Error("useApi needs a logged-in user");
  return api;
}
