// Test helpers. The fixtures below are TEST DATA for component tests only; the end-to-end tests in e2e/ run
// against the real backend instead.
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { Layout } from "../components/Layout";
import { MetaProvider } from "../meta";
import type { CatalogueModel, Meta, Valuation } from "../types";

export type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown; headers?: Record<string, string> };

export function mockFetch(routes: Record<string, Handler | { status?: number; body?: unknown }>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const method = (init?.method ?? "GET").toUpperCase();
    // Most specific (longest) matching route wins.
    const key = Object.keys(routes)
      .filter((k) => {
        const [m, p] = k.includes(" ") ? k.split(" ") : ["GET", k];
        return m === method && url.startsWith(p);
      })
      .sort((a, b) => b.length - a.length)[0];
    if (!key) return new Response(JSON.stringify({ error: { code: "not_found", message: `no mock for ${method} ${url}`, request_id: "t" } }), { status: 404 });
    const route = routes[key];
    const r: { status?: number; body?: unknown; headers?: Record<string, string> } =
      typeof route === "function" ? route(url, init) : route;
    return new Response(r.status === 204 ? null : JSON.stringify(r.body ?? {}), {
      status: r.status ?? 200,
      headers: { "Content-Type": "application/json", ...(r.headers ?? {}) },
    });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

export function renderAt(path: string, element: ReactElement, routePath = "*") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <MetaProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path={routePath} element={element} />
          </Route>
        </Routes>
      </MetaProvider>
    </MemoryRouter>,
  );
}

export const META: Meta = {
  environment: "development",
  method_version: "comparables-v1",
  regions: { IN: "INR", US: "USD" },
  data_status: "mock_only",
  real_observations: 0,
  mock_observations: 278,
  mock_data_in_use: true,
  newest_real_observation: null,
  freshness_days: 180,
  sources: [],
};

export const S21: CatalogueModel = {
  id: "samsung-galaxy-s21",
  manufacturer: "Samsung",
  name: "Galaxy S21",
  release_date: "2021-01-29",
  storage_gb: [128, 256],
  oem_codes: ["SM-G991B"],
  evidence: { IN: "mock_only", US: "mock_only" },
};

export const PIXEL6A: CatalogueModel = {
  id: "google-pixel-6a",
  manufacturer: "Google",
  name: "Pixel 6a",
  release_date: "2022-07-28",
  storage_gb: [128],
  oem_codes: [],
  evidence: { IN: "insufficient", US: "insufficient" },
};

const ESTIMATE = {
  value: 8000,
  low: 6500,
  high: 9500.5,
  range_method: "p10_p90" as const,
  basis: "synthetic",
  basis_label: "synthetic (mock) observations",
  quality: "evidence_backed" as const,
  observation_count: 12,
  oldest_observation: "2026-06-05",
  newest_observation: "2026-09-28",
  sources: [{ id: "synthetic-dev", name: "Synthetic development data (MOCK)", source_type: "synthetic", verified: false, is_mock: true }],
};

export const VALUATION: Valuation = {
  valuation_id: "val_test",
  method_version: "comparables-v1",
  mock: true,
  generated_at: "2026-10-21T10:00:00Z",
  region: "IN",
  currency: "INR",
  status: "ok",
  device: { model_id: S21.id, manufacturer: "Samsung", name: "Galaxy S21", storage_gb: 128, storage_inferred: false },
  condition: { grade: "faulty", faults: ["battery_wear"], reasons: ["Graded faulty because the battery drains fast."], uncertainties: [], not_used: [], safety: [], customer_reported: true },
  as_is: ESTIMATE,
  as_is_unavailable_reason: null,
  repair_type: "battery_replacement",
  assumed_grade_after_repair: "good",
  after_repair: { ...ESTIMATE, value: 22000, low: 20000, high: 24000 },
  after_repair_unavailable_reason: null,
  trade_in: null,
  explanation: ["Based on 12 synthetic (mock) observations."],
  warnings: ["MOCK DATA: …"],
};
