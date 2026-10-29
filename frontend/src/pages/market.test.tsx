// Component tests for price comparison, the developer portal and the watchlist. All data here is TEST DATA.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { META, mockFetch, renderAt, S21 } from "../test/utils";
import type { ApiKey, MarketPrices, Offer, PriceHistory, ProviderStatus } from "../types";
import { DevelopersPage } from "./DevelopersPage";
import { PricesPage } from "./PricesPage";
import { WatchlistPage } from "./WatchlistPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

const base = { "/api/meta": { body: META }, "/api/catalogue": { body: [S21] } };

const PROVIDERS: ProviderStatus[] = [
  { id: "flipkart-affiliate", name: "Flipkart (Affiliate API)", state: "operational", automated: true, markets: "IN", configured: true, requirement: null, last_job_status: "succeeded", last_job_message: null, last_retrieved_at: new Date().toISOString(), terms_note: "", docs_url: null },
  { id: "amazon-creators-in", name: "Amazon.in (Creators API)", state: "not_configured", automated: true, markets: "IN", configured: false, requirement: "Set FLIPVALUE_AMAZON_CREDENTIAL_ID …", last_job_status: null, last_job_message: null, last_retrieved_at: null, terms_note: "", docs_url: null },
];

function offer(id: number, price: number, extra: Partial<Offer> = {}): Offer {
  return {
    id, source: { id: "flipkart-affiliate", name: "Flipkart (Affiliate API)", verified: true, is_mock: false, automated: true },
    title: `SAMSUNG Galaxy S21 5G (128 GB) #${id}`, brand: "Samsung", model_id: S21.id, storage_gb: 128, ram_gb: 8, color: "Gray",
    condition: "new", price_type: "new_retail", price, mrp: 69999, discount_pct: 40, currency: "INR",
    url: `https://www.flipkart.com/p/${id}`, seller: "RetailNet", seller_type: "marketplace_seller", availability: "in_stock",
    delivery_note: null, retrieved_at: new Date().toISOString(), published_at: null, freshness: "fresh", is_mock: false,
    match: { category: "strong", score: 85, reasons: ["brand Samsung", "storage 128 GB"] }, ...extra,
  };
}

const empty = { count: 0, lowest: null, highest: null, spread: null, sources: [] };
const PRICES: MarketPrices = {
  model_id: S21.id, storage_gb: 128, region: "IN", currency: "INR", product: { id: S21.id, manufacturer: "Samsung", name: "Galaxy S21" },
  groups: { new: [offer(1, 41990), offer(2, 39990, { availability: "out_of_stock", seller_type: "retailer" })], refurbished: [], used: [], buyback: [] },
  summary: { new: { count: 2, lowest: 41990, highest: 41990, spread: null, sources: ["Flipkart (Affiliate API)"] }, refurbished: empty, used: empty, buyback: empty },
  alternatives: [offer(3, 29999, { title: "SAMSUNG Galaxy S21 FE", match: { category: "similar", score: 30, reasons: ["a different model: 'fe' follows the name Galaxy S21"] } })],
  mrp: { value: 69999, count: 2 }, mock_data_included: false, generated_at: new Date().toISOString(), fresh_hours: 24, max_age_days: 14,
  providers: PROVIDERS,
};
const NO_HISTORY: PriceHistory = {
  model_id: S21.id, storage_gb: 128, region: "IN", condition: "new", currency: "INR", days: 90, observation_count: 1,
  observed_days: 1, available: false, mock_data_included: false, last_observation: null, series: {}, lowest: null,
  highest: null, change: null, gaps: [], reason: "Tracking has only just started: history needs prices retrieved on at least two different days.",
};

describe("price comparison", () => {
  it("shows comparable offers with links, alternatives apart, and an honest history state", async () => {
    mockFetch({ ...base, "/api/market/offers": { body: PRICES }, "/api/market/history": { body: NO_HISTORY } });
    renderAt(`/prices?model=${S21.id}&storage=128`, <PricesPage />);

    const table = await screen.findByRole("table", { name: /New offers/ });
    expect(screen.queryByText("Needs credentials")).not.toBeInTheDocument();  // provider status is not shown
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    const link = within(rows[0]).getByRole("link", { name: /View listing/ });
    expect(link).toHaveAttribute("href", "https://www.flipkart.com/p/1");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(within(rows[1]).getByText("Out of stock")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Similar, but not the same phone" })).toBeInTheDocument();
    expect(screen.getByText(/history needs prices retrieved on at least two different days/)).toBeInTheDocument();
    expect(screen.queryByText(/Fixture offers/)).not.toBeInTheDocument();
  });

  it("filters by stock and explains empty groups without inventing prices", async () => {
    const user = userEvent.setup();
    mockFetch({ ...base, "/api/market/offers": { body: PRICES }, "/api/market/history": { body: NO_HISTORY } });
    renderAt(`/prices?model=${S21.id}&storage=128`, <PricesPage />);

    await user.click(await screen.findByRole("checkbox", { name: /In stock only/ }));
    expect(within(screen.getByRole("table", { name: /New offers/ })).getAllByRole("row")).toHaveLength(2);
    await user.click(screen.getByRole("tab", { name: /Refurbished/ }));
    expect(screen.getByText(/No refurbished offers retrieved/)).toBeInTheDocument();
  });

  it("shows store estimates by store name, labelled as estimates without links, and filters by store", async () => {
    const user = userEvent.setup();
    const est = (id: number, store: string, price: number) => offer(id, price, {
      source: { id: "flipvalue-store-estimates", name: "FlipValue store price estimates", verified: false, is_mock: false, automated: false, estimated: true },
      seller: store, url: null, availability: null, freshness: "estimate" });
    const groups = { ...PRICES.groups, new: [est(10, "Amazon", 38499), est(11, "Croma", 38999), offer(1, 41990)] };
    mockFetch({ ...base, "/api/market/offers": { body: { ...PRICES, groups, estimates_included: true } }, "/api/market/history": { body: NO_HISTORY } });
    renderAt(`/prices?model=${S21.id}&storage=128`, <PricesPage />);

    const rows = within(await screen.findByRole("table", { name: /New offers/ })).getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Amazon")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Estimate")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Estimate, no listing")).toBeInTheDocument();
    expect(within(rows[2]).getByRole("link", { name: /View listing/ })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Store"), "Croma");
    expect(within(screen.getByRole("table", { name: /New offers/ })).getAllByRole("row")).toHaveLength(2);
  });

  it("labels fixture data", async () => {
    mockFetch({ ...base, "/api/market/offers": { body: { ...PRICES, mock_data_included: true } }, "/api/market/history": { body: NO_HISTORY } });
    renderAt(`/prices?model=${S21.id}&storage=128`, <PricesPage />);
    expect(await screen.findByText(/Fixture offers — not real listings/)).toBeInTheDocument();
  });
});

const KEY: ApiKey = {
  id: 7, name: "shop backend", prefix: "fv_abcdefg", scopes: ["valuation:read"], status: "active",
  created_at: "2026-10-20T10:00:00", revoked_at: null, last_used_at: null, rate_limit_per_minute: 60, daily_quota: 1000,
  requests_today: 0, requests_30d: 0,
};
const ME = { id: 1, email: "dev@example.com", created_at: "2026-10-20T10:00:00", limits: { rate_limit_per_minute: 60, daily_quota: 1000, max_keys: 5 }, scopes_available: ["valuation:read", "market_prices:read", "price_history:read"] };

describe("developer portal", () => {
  it("asks to sign in when there is no session", async () => {
    mockFetch({ ...base, "/api/account/me": { status: 401, body: { error: { code: "not_signed_in", message: "Sign in to continue.", request_id: "r" } } } });
    renderAt("/developers", <DevelopersPage />);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Scope · returns" })).toBeInTheDocument(); // docs stay public
  });

  it("creates a key, shows it once with the CSRF header sent, then hides it", async () => {
    const user = userEvent.setup();
    let keys: ApiKey[] = [];
    const calls = mockFetch({
      ...base,
      "/api/account/me": { body: ME },
      "/api/account/keys": () => ({ body: keys }),
      "POST /api/account/keys": () => {
        keys = [KEY];
        return { status: 201, body: { ...KEY, key: "fv_SECRET_shown_once" } };
      },
    });
    renderAt("/developers", <DevelopersPage />);

    await user.type(await screen.findByLabelText("Name"), "shop backend");
    await user.click(screen.getByRole("button", { name: "Create key" }));
    expect(await screen.findByText("fv_SECRET_shown_once")).toBeInTheDocument();
    expect(screen.getByText(/It will not be shown again/)).toBeInTheDocument();
    const post = calls.find((c) => c.init?.method === "POST")!;
    expect((post.init!.headers as Record<string, string>)["X-FlipValue-Client"]).toBe("web");
    expect(JSON.parse(String(post.init!.body))).toEqual({ name: "shop backend", scopes: ["valuation:read"] });

    await user.click(screen.getByRole("button", { name: "I have stored it" }));
    await waitFor(() => expect(screen.queryByText("fv_SECRET_shown_once")).not.toBeInTheDocument());
    expect(screen.getByText("fv_abcdefg…")).toBeInTheDocument();
  });
});

describe("watchlist", () => {
  it("prefills from the comparison link and explains when alerts fire", async () => {
    mockFetch({ ...base, "/api/account/me": { body: ME }, "/api/account/watchlist": { body: [] }, "/api/account/alerts": { body: [] } });
    renderAt(`/watchlist?model=${S21.id}&storage=256&condition=refurbished`, <WatchlistPage />);
    expect(await screen.findByText(/only when FlipValue actually retrieves an offer/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Phone")).toHaveValue(S21.id));
    expect(screen.getByLabelText("Condition")).toHaveValue("refurbished");
    expect(screen.getByText("No qualifying price has been observed yet.")).toBeInTheDocument();
  });
});
