/** Base API client — shared fetch wrapper with auth header injection. */

const API_BASE = "/api";

export class ApiRequestError extends Error {
  constructor(
    readonly status: number,
    readonly retryAfter: number | null = null,
  ) {
    super("Request failed. Please try again.");
    this.name = "ApiRequestError";
  }

  static fromResponse(response: Response): ApiRequestError {
    const value = response.headers.get("retry-after") ?? "";
    const seconds = /^\d+$/.test(value) ? Math.min(3600, Math.max(1, Number(value))) : null;
    return new ApiRequestError(response.status, seconds);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Return the current OIDC access token, or null if not authenticated. */
function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  const authority = window.__ENV__?.OIDC_AUTHORITY;
  const clientId = window.__ENV__?.OIDC_CLIENT_ID;
  if (!authority || !clientId) return null;
  const oidcStorage = sessionStorage.getItem(`oidc.user:${authority}:${clientId}`);
  if (!oidcStorage) return null;
  try {
    const value: unknown = JSON.parse(oidcStorage);
    if (!isRecord(value) || typeof value.access_token !== "string") return null;
    return value.access_token;
  } catch {
    return null;
  }
}

/** Build headers including the Bearer token when available. */
function authHeaders(): HeadersInit {
  const token = getAccessToken();
  const headers: HeadersInit = { "Content-Type": "application/json" };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

/** Generic typed POST request. */
export async function apiPost<TReq, TRes>(path: string, body: TReq, signal?: AbortSignal): Promise<TRes> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    signal,
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw ApiRequestError.fromResponse(res);
  }
  return res.json();
}

/** Generic typed PUT request. */
export async function apiPut<TReq, TRes>(path: string, body: TReq): Promise<TRes> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw ApiRequestError.fromResponse(res);
  return res.json();
}

/** Generic typed GET request with optional query params. */
export async function apiGet<TRes>(
  path: string,
  params?: Record<string, string> | URLSearchParams,
  signal?: AbortSignal,
): Promise<TRes> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (params) {
    url.search = new URLSearchParams(params).toString();
  }
  const res = await fetch(url.toString(), {
    method: "GET",
    signal,
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw ApiRequestError.fromResponse(res);
  }
  return res.json();
}
