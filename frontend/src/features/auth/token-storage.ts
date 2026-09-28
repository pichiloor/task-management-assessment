// sessionStorage: the token survives a reload but not closing the tab, and
// is not sent automatically like a cookie (so no CSRF surface). Storage can
// be unavailable (private mode, blocked site data), hence the try/catch.
const KEY = "task-management.token";

export function readToken(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function writeToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(KEY, token);
    else sessionStorage.removeItem(KEY);
  } catch {
    // The session then lasts only until the page is reloaded.
  }
}
