import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { createApi, login as requestToken, type Api } from "../../api/endpoints";
import { ApiError } from "../../api/http";
import { AuthContext, type AuthState } from "./auth-context";
import { readToken, writeToken } from "./token-storage";

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [token, setToken] = useState<string | null>(readToken);

  // The token state is the source of truth; storage and cache follow it.
  useEffect(() => {
    writeToken(token);
    if (!token) queryClient.clear();
  }, [token, queryClient]);

  const logout = useCallback(() => setToken(null), []);

  // Only a 401 for the session still in use logs out: a late answer to a
  // request made with an earlier token must not end a newer session.
  const logoutIfCurrent = useCallback(
    (expected: string) =>
      setToken((current) => (current === expected ? null : current)),
    [],
  );

  const api = useMemo(
    () =>
      token
        ? logoutOnUnauthorized(createApi(token), () => logoutIfCurrent(token))
        : null,
    [token, logoutIfCurrent],
  );

  const me = useQuery({
    queryKey: ["me", token],
    queryFn: () => api!.me(),
    enabled: api !== null,
    staleTime: Infinity,
  });

  const login = useCallback(async (email: string, password: string) => {
    setToken(await requestToken(email, password));
  }, []);

  const value = useMemo<AuthState>(
    () => ({ token, user: me.data ?? null, api, login, logout }),
    [token, me.data, api, login, logout],
  );

  // A stored token is checked against /users/me before any page renders.
  if (token && me.isPending) {
    return <p className="page-status">Loading…</p>;
  }
  if (token && me.isError && !isUnauthorized(me.error)) {
    return (
      <div className="page-status" role="alert">
        <p>{me.error.message}</p>
        <button className="button" type="button" onClick={() => me.refetch()}>
          Retry
        </button>
      </div>
    );
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/** Wraps every call so an expired or revoked token sends the user back to
 * the login page instead of leaving the screen half broken. */
function logoutOnUnauthorized(api: Api, logout: () => void): Api {
  const wrapped = Object.fromEntries(
    Object.entries(api).map(([name, call]) => [
      name,
      async (...args: unknown[]) => {
        try {
          return await (call as (...a: unknown[]) => Promise<unknown>)(...args);
        } catch (error) {
          if (isUnauthorized(error)) logout();
          throw error;
        }
      },
    ]),
  );
  return wrapped as Api;
}
