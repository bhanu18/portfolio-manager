// ---------------------------------------------------------------------------
// Token storage. The API returns a JWT in the JSON body (it does NOT set a
// cookie), so we persist it in localStorage and also keep an in-memory copy
// for synchronous access by the axios request interceptor.
// ---------------------------------------------------------------------------

const STORAGE_KEY = "portfolio.access_token";

let inMemoryToken: string | null = readInitialToken();

function readInitialToken(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return inMemoryToken;
}

export function setToken(token: string): void {
  inMemoryToken = token;
  try {
    localStorage.setItem(STORAGE_KEY, token);
  } catch {
    /* ignore storage failures (e.g. private mode) */
  }
}

export function clearToken(): void {
  inMemoryToken = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
