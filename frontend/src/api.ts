// Typed client for the public FlipValue API (/api). No API key ever reaches the browser.
import type {
  Account,
  ApiKey,
  CatalogueModel,
  DecisionInput,
  DecisionResult,
  KeyUsage,
  MarketPrices,
  Meta,
  NewApiKey,
  OfferCondition,
  PriceAlert,
  PriceHistory,
  ProviderStatus,
  SaveResponse,
  SavedValuation,
  Scope,
  Trend,
  Valuation,
  ValuationRequest,
  WatchItem,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null = null,
    readonly retryAfter: number | null = null,
  ) {
    super(message);
  }

  /** Worth offering a retry button for. */
  get transient(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }
}

const TIMEOUT_MS = 15_000;

/** API origin from the build (VITE_API_BASE_URL); empty means the website's own origin. */
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/$/, "");

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { Accept: "application/json", ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach FlipValue. Check your connection and try again.");
  } finally {
    clearTimeout(timer);
  }
  if (response.status === 204) return undefined as T;
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const error = (payload as { error?: { code?: string; message?: string; request_id?: string } } | null)?.error;
    const retry = Number(response.headers.get("Retry-After"));
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? `Request failed (${response.status}).`,
      error?.request_id ?? null,
      Number.isFinite(retry) && retry > 0 ? retry : null,
    );
  }
  return payload as T;
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

// Account calls carry the session cookie; state changes add the header the server requires against CSRF.
const WEB = { "X-FlipValue-Client": "web" };
const acct = <T>(path: string, init: RequestInit = {}) =>
  request<T>(`/api/account${path}`, { credentials: "same-origin", ...init, headers: { ...WEB, ...init.headers } });
const acctPost = <T>(path: string, body?: unknown) =>
  acct<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  meta: () => request<Meta>("/api/meta"),
  catalogue: (q = "") => request<CatalogueModel[]>(`/api/catalogue?q=${encodeURIComponent(q)}`),
  model: (id: string) => request<CatalogueModel>(`/api/catalogue/${encodeURIComponent(id)}`),
  valuate: (body: ValuationRequest) => post<Valuation>("/api/valuations", body),
  decide: (body: DecisionInput) => post<DecisionResult>("/api/decision", body),
  save: (body: ValuationRequest) => post<SaveResponse>("/api/saved", body),
  saved: (id: string) => request<SavedValuation>(`/api/saved/${encodeURIComponent(id)}`),
  savedRequest: (id: string) => request<ValuationRequest>(`/api/saved/${encodeURIComponent(id)}/request`),
  deleteSaved: (id: string, token: string) =>
    request<void>(`/api/saved/${encodeURIComponent(id)}`, { method: "DELETE", headers: { "X-Delete-Token": token } }),
  trend: (p: { model_id: string; storage_gb: number; region: string; grade: string }) =>
    request<Trend>(`/api/trends?${new URLSearchParams({ ...p, storage_gb: String(p.storage_gb) })}`),
  providers: () => request<ProviderStatus[]>("/api/market/providers"),
  offers: (model_id: string, storage_gb: number, region = "IN") =>
    request<MarketPrices>(`/api/market/offers?${new URLSearchParams({ model_id, storage_gb: String(storage_gb), region })}`),
  priceHistory: (model_id: string, storage_gb: number, condition: OfferCondition, days = 90, region = "IN") =>
    request<PriceHistory>(
      `/api/market/history?${new URLSearchParams({ model_id, storage_gb: String(storage_gb), condition, days: String(days), region })}`,
    ),
};

export const account = {
  me: () => acct<Account>("/me"),
  register: (email: string, password: string) => acctPost<Account>("/register", { email, password }),
  login: (email: string, password: string) => acctPost<Account>("/login", { email, password }),
  logout: () => acctPost<void>("/logout"),
  keys: () => acct<ApiKey[]>("/keys"),
  createKey: (name: string, scopes: Scope[]) => acctPost<NewApiKey>("/keys", { name, scopes }),
  revokeKey: (id: number) => acct<ApiKey>(`/keys/${id}`, { method: "DELETE" }),
  keyUsage: (id: number, days = 30) => acct<KeyUsage>(`/keys/${id}/usage?days=${days}`),
  watchlist: () => acct<WatchItem[]>("/watchlist"),
  watch: (body: { model_id: string; storage_gb: number; condition: "new" | "refurbished"; target_price?: string }) =>
    acctPost<WatchItem>("/watchlist", body),
  unwatch: (id: number) => acct<void>(`/watchlist/${id}`, { method: "DELETE" }),
  alerts: () => acct<PriceAlert[]>("/alerts"),
  markRead: (id: number) => acctPost<void>(`/alerts/${id}/read`),
};
