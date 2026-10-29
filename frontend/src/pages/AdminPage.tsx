import { useState } from "react";

import { ApiError, request } from "../api";
import { ErrorState, Loading, Notice } from "../components/ui";
import { day } from "../format";
import { usePageTitle } from "../hooks";

// Small operator console over /admin/api. The admin key stays in this tab's session storage only.
const KEY = "flipvalue.admin.key";

function readKey(): string {
  try {
    return window.sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

interface Source {
  id: string; name: string; source_type: string; markets: string; verified: boolean; is_mock: boolean;
  observation_count: number; newest_observation: string | null; freshness_days: number | null;
  last_job_status: string | null; terms_note: string;
}
interface Job { id: number; source_id: string; status: string; started_at: string; accepted: number; rejected: number; duplicates: number; triggered_by: string; message: string | null }
interface Metrics { requests_by_channel: Record<string, number>; status_counts: Record<string, number>; error_codes: Record<string, number>; latency_ms_p50: number | null; latency_ms_p95: number | null; api_clients_active: number }
interface Rejected { line: number; reason: string; raw: string }
interface Quality {
  providers: { id: string; name: string; state: string; requirement: string | null; last_job_message: string | null; last_retrieved_at: string | null }[];
  retrievals_by_source: Record<string, { succeeded: number; failed: number; accepted: number; rejected: number; duplicates: number }>;
  recent_failures: { source_id: string; at: string; message: string | null }[];
  offers: { total_rows: number; current_listings: Record<string, number>; older_than_max_age: number };
  match_categories: Record<string, number>;
  rejected_by_reason: Record<string, number>;
  offers_missing_field: Record<string, number>;
  sources_missing_metadata: { id: string; missing: string[] }[];
}

function DataQuality({ q, onRefresh }: { q: Quality; onRefresh: (model: string) => void }) {
  const [model, setModel] = useState("samsung-galaxy-s21");
  const list = (r: Record<string, number>) => Object.entries(r).map(([k, v]) => `${k} ${v}`).join(" · ") || "none";
  return (
    <section className="card">
      <h2>Marketplace providers and data quality (30 days)</h2>
      <ul>{q.providers.map((p) => (
        <li key={p.id}><strong>{p.name}</strong>: {p.state}{p.last_retrieved_at && `, last retrieved ${day(p.last_retrieved_at)}`}
          {p.requirement && <div className="small muted">{p.requirement}</div>}
          {p.last_job_message && <div className="small error-text">{p.last_job_message}</div>}</li>
      ))}</ul>
      <form className="row" onSubmit={(e) => { e.preventDefault(); onRefresh(model); }}>
        <input type="text" aria-label="Model id to refresh" value={model} onChange={(e) => setModel(e.target.value)} style={{ maxWidth: 260 }} />
        <button type="submit" className="btn">Refresh offers now</button>
      </form>
      <p>Retrievals: {Object.entries(q.retrievals_by_source).map(([s, r]) => `${s} ${r.succeeded} ok / ${r.failed} failed (${r.accepted} stored, ${r.rejected} rejected, ${r.duplicates} duplicates)`).join("; ") || "none"}</p>
      <p>Offers: {q.offers.total_rows} rows; current listings {list(q.offers.current_listings)}; older than max age {q.offers.older_than_max_age}</p>
      <p>Match categories: {list(q.match_categories)}</p>
      <p>Rejects by reason: {list(q.rejected_by_reason)}</p>
      <p>Offers missing a field: {list(q.offers_missing_field)}</p>
      <p>Sources missing metadata: {q.sources_missing_metadata.map((s) => `${s.id} (${s.missing.join(", ")})`).join("; ") || "none"}</p>
      {q.recent_failures.length > 0 && <ul>{q.recent_failures.map((f) => <li key={f.at + f.source_id}>{day(f.at)} {f.source_id}: {f.message}</li>)}</ul>}
    </section>
  );
}

export function AdminPage() {
  const titleRef = usePageTitle("Operator console");
  const [key, setKey] = useState(readKey);
  const [draftKey, setDraftKey] = useState("");
  const [data, setData] = useState<{ sources: Source[]; jobs: Job[]; metrics: Metrics; quality: Quality } | null>(null);
  const [offerSource, setOfferSource] = useState("");
  const [rejected, setRejected] = useState<{ job: number; rows: Rejected[] } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [importSource, setImportSource] = useState("");
  const [importResult, setImportResult] = useState<Job | null>(null);

  const call = <T,>(path: string, init: RequestInit = {}, k = key) =>
    request<T>(`/admin/api${path}`, { ...init, headers: { "X-API-Key": k, ...init.headers } });

  const load = async (k = key) => {
    setLoading(true);
    setError(null);
    try {
      const [sources, jobs, metrics, quality] = await Promise.all([
        call<Source[]>("/sources", {}, k), call<Job[]>("/jobs?limit=20", {}, k), call<Metrics>("/metrics", {}, k),
        call<Quality>("/data-quality", {}, k),
      ]);
      setData({ sources, jobs, metrics, quality });
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unexpected", String(e)));
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const signIn = (e: React.FormEvent) => {
    e.preventDefault();
    try {
      window.sessionStorage.setItem(KEY, draftKey);
    } catch {
      /* the key then lasts only until reload */
    }
    setKey(draftKey);
    setDraftKey("");
    void load(draftKey);
  };

  const signOut = () => {
    try {
      window.sessionStorage.removeItem(KEY);
    } catch {
      /* nothing stored */
    }
    setKey("");
    setData(null);
  };

  const upload = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const file = (e.currentTarget.elements.namedItem("csv") as HTMLInputElement).files?.[0];
    if (!file || !importSource) return;
    try {
      const job = await call<Job>("/imports", { method: "POST", body: JSON.stringify({ source_id: importSource, csv_text: await file.text() }) });
      setImportResult(job);
      void load();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "unexpected", String(err)));
    }
  };

  const refreshOffers = async (model: string) => {
    try {
      await call("/offers/refresh", { method: "POST", body: JSON.stringify({ model_id: model, region: "IN" }) });
      void load();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "unexpected", String(err)));
    }
  };

  const uploadOffers = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const file = (e.currentTarget.elements.namedItem("offers") as HTMLInputElement).files?.[0];
    if (!file || !offerSource) return;
    try {
      setImportResult(await call<Job>("/offer-imports", { method: "POST", body: JSON.stringify({ source_id: offerSource, region: "IN", csv_text: await file.text() }) }));
      void load();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "unexpected", String(err)));
    }
  };

  return (
    <div className="container">
      <h1 ref={titleRef} tabIndex={-1}>Operator console</h1>
      {!key || (error?.status === 401 && !data) ? (
        <form className="card narrow" onSubmit={signIn}>
          {error?.status === 401 && <Notice tone="danger" title="That key was not accepted." />}
          <div className="field">
            <label htmlFor="admin-key">Admin API key</label>
            <input id="admin-key" type="password" autoComplete="off" value={draftKey} onChange={(e) => setDraftKey(e.target.value)} />
            <span className="hint">Kept in this tab only. Partner keys do not work here.</span>
          </div>
          <button type="submit" className="btn primary" disabled={!draftKey}>Open console</button>
        </form>
      ) : (
        <>
          <div className="row no-print">
            <button type="button" className="btn" onClick={() => load()}>{data ? "Refresh" : "Load"}</button>
            <button type="button" className="btn link" onClick={signOut}>Forget key</button>
          </div>
          {loading && <Loading />}
          {error && error.status !== 401 && <ErrorState error={error} onRetry={() => load()} what="operator data" />}
          {data && (
            <div className="stack" style={{ marginTop: 16 }}>
              <section className="card">
                <h2>Last 24 hours</h2>
                <p>Requests: {Object.entries(data.metrics.requests_by_channel).map(([k, v]) => `${k} ${v}`).join(" · ") || "none"}</p>
                <p>Errors: {Object.entries(data.metrics.error_codes).map(([k, v]) => `${k} ${v}`).join(" · ") || "none"}</p>
                <p>Latency p50 {data.metrics.latency_ms_p50 ?? "—"} ms · p95 {data.metrics.latency_ms_p95 ?? "—"} ms · active API keys {data.metrics.api_clients_active}</p>
              </section>
              <section className="card">
                <h2>Sources</h2>
                <div className="table-wrap"><table>
                  <thead><tr><th>Source</th><th>Type</th><th>Markets</th><th className="num">Observations</th><th>Newest</th><th>Last job</th></tr></thead>
                  <tbody>{data.sources.map((s) => (
                    <tr key={s.id}><td>{s.name} {s.is_mock && <span className="badge mock">Mock</span>}<div className="small muted">{s.terms_note}</div></td>
                      <td>{s.source_type}</td><td>{s.markets}</td><td className="num">{s.observation_count}</td>
                      <td>{day(s.newest_observation)}{s.freshness_days !== null && <div className="small muted">{s.freshness_days} days ago</div>}</td>
                      <td>{s.last_job_status ?? "—"}</td></tr>
                  ))}</tbody>
                </table></div>
              </section>
              <section className="card">
                <h2>Import observations (CSV)</h2>
                <p className="small muted">Columns: manufacturer, model, storage_gb, region, currency, grade, price, observed_at, external_ref. Register the source first (CLI or API).</p>
                <form className="row" onSubmit={upload}>
                  <select aria-label="Source" value={importSource} onChange={(e) => setImportSource(e.target.value)} style={{ maxWidth: 260 }}>
                    <option value="">Choose source…</option>
                    {data.sources.filter((s) => !s.is_mock).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                  <input name="csv" type="file" accept=".csv,text/csv" aria-label="CSV file" />
                  <button type="submit" className="btn primary" disabled={!importSource}>Import</button>
                </form>
                {importResult && <p>Job {importResult.id}: {importResult.status}, {importResult.accepted} accepted, {importResult.rejected} rejected, {importResult.duplicates} duplicates.</p>}
              </section>
              <DataQuality q={data.quality} onRefresh={refreshOffers} />
              <section className="card">
                <h2>Import curated offers or buyback quotes (CSV)</h2>
                <p className="small muted">Columns: title, brand, storage_gb, condition, price_type, price, mrp, currency, url, seller, seller_type, availability, retrieved_at, external_ref (docs/DATA_QUALITY.md).</p>
                <form className="row" onSubmit={uploadOffers}>
                  <select aria-label="Offer source" value={offerSource} onChange={(e) => setOfferSource(e.target.value)} style={{ maxWidth: 260 }}>
                    <option value="">Choose source…</option>
                    {data.sources.filter((s) => !s.is_mock).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                  <input name="offers" type="file" accept=".csv,text/csv" aria-label="Offers CSV file" />
                  <button type="submit" className="btn primary" disabled={!offerSource}>Import offers</button>
                </form>
              </section>
              <section className="card">
                <h2>Recent ingestion jobs</h2>
                <div className="table-wrap"><table>
                  <thead><tr><th>#</th><th>Source</th><th>Status</th><th>Started</th><th className="num">Accepted</th><th className="num">Rejected</th><th className="num">Duplicates</th></tr></thead>
                  <tbody>{data.jobs.map((j) => (
                    <tr key={j.id}><td>{j.id}</td><td>{j.source_id}</td><td>{j.status}{j.message && <div className="small muted">{j.message}</div>}</td>
                      <td>{day(j.started_at)}</td><td className="num">{j.accepted}</td>
                      <td className="num">{j.rejected > 0 ? <button type="button" className="btn link" onClick={async () => setRejected({ job: j.id, rows: await call<Rejected[]>(`/jobs/${j.id}/rejected`) })}>{j.rejected}</button> : 0}</td>
                      <td className="num">{j.duplicates}</td></tr>
                  ))}</tbody>
                </table></div>
                {rejected && (
                  <div style={{ marginTop: 12 }}>
                    <h3>Rejected rows in job {rejected.job}</h3>
                    <ul>{rejected.rows.map((r) => <li key={r.line}>Line {r.line}: {r.reason}</li>)}</ul>
                  </div>
                )}
              </section>
            </div>
          )}
        </>
      )}
    </div>
  );
}
