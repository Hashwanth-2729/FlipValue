import { Fragment, useState } from "react";
import { Link } from "react-router-dom";

import { account, ApiError } from "../api";
import { AccountGate } from "../components/AccountGate";
import { ErrorState, Loading, Notice } from "../components/ui";
import { ago, day } from "../format";
import { useAsync, usePageTitle } from "../hooks";
import type { Account, ApiKey, KeyUsage, NewApiKey, Scope } from "../types";

const SCOPE_HELP: Record<Scope, string> = {
  "valuation:read": "POST /api/v1/valuations, GET /api/v1/valuations/{id}, and the FixMyTech-compatible POST /v1/valuations",
  "market_prices:read": "GET /api/v1/market-prices",
  "price_history:read": "GET /api/v1/price-history",
};

const ENDPOINTS: [string, string, string][] = [
  ["GET", "/api/v1/health", "No key. Service and provider status."],
  ["POST", "/api/v1/valuations", "valuation:read · private sale, buyback, refurbished retail, original retail, after repair"],
  ["GET", "/api/v1/valuations/{id}", "valuation:read · only valuations created by your account"],
  ["GET", "/api/v1/market-prices?product_id=&storage_gb=", "market_prices:read · current offers + provider status"],
  ["GET", "/api/v1/price-history?product_id=&storage_gb=&condition=", "price_history:read · observed daily lowest prices"],
  ["GET", "/api/v1/products?q=  ·  /api/v1/products/{id}", "any key · catalogue"],
  ["GET", "/api/v1/usage", "any key · usage and limits of the calling key"],
];

const ERRORS: [number, string, string][] = [
  [401, "unauthorized", "Missing, wrong or revoked X-API-Key."],
  [403, "insufficient_scope", "The key lacks the scope this endpoint needs."],
  [404, "unsupported_model / not_found / no_data_for_condition", "Unknown product, someone else's valuation, or storage unknown."],
  [422, "validation_error / unsupported_region / unsupported_currency / variant_required", "Fix the request; do not retry unchanged."],
  [429, "rate_limited / quota_exceeded", "Wait for Retry-After seconds. Daily quotas reset at 00:00 UTC."],
  [503, "service_timeout", "Safe to retry with backoff."],
];

const EXAMPLE_REQUEST = `curl -X POST "$FLIPVALUE_BASE_URL/api/v1/valuations" \\
  -H "X-API-Key: $FLIPVALUE_API_KEY" -H "Content-Type: application/json" \\
  -d '{"device":{"manufacturer":"Samsung","model":"SM-G991B","storage_gb":128},
       "region":"IN","currency":"INR",
       "condition":{"grade":"faulty","faults":["display_damage"]},
       "repair_scenario":{"repair_type":"screen_replacement"}}'`;

const EXAMPLE_RESPONSE = `HTTP/1.1 201 Created
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 59
X-Quota-Limit: 1000

{"id":"val_…","status":"partial","currency":"INR","confidence":"medium",
 "private_sale":{"available":true,"value":8450,"low":6100,"high":10200,"basis":"completed_sale",
                 "confidence":"medium","observation_count":12,"newest_observation":"2026-10-20",…},
 "buyback":{"available":false,"confidence":"insufficient","reason":"No dealer buyback or trade-in quotes…"},
 "after_repair":{"available":true,"value":21900,…},
 "repair":{"repair_type":"screen_replacement","value_uplift":13450,"confidence":"medium",…},
 "limitations":[…],"assumptions":[…],"missing_data":[],"warnings":[…]}`;

function NewKeyPanel({ created, onDone }: { created: NewApiKey; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <section className="card secret" aria-labelledby="new-key-h">
      <h3 id="new-key-h">Your new key “{created.name}”</h3>
      <Notice tone="warn" title="Copy it now. It will not be shown again.">
        <p>FlipValue keeps only a one-way hash. Store the key in your server's secret storage — never in browser code or a repository.</p>
      </Notice>
      <div className="secret-value">
        <code aria-label="API key">{created.key}</code>
        <button type="button" className="btn" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
      </div>
      <button type="button" className="btn primary" onClick={onDone}>I have stored it</button>
    </section>
  );
}

function UsagePanel({ id }: { id: number }) {
  const usage = useAsync<KeyUsage>(() => account.keyUsage(id), [id]);
  if (usage.loading) return <Loading lines={1} />;
  if (usage.error) return <ErrorState error={usage.error} what="usage" />;
  const u = usage.data!;
  if (u.total === 0) return <p className="small muted">No requests in the last {u.days} days.</p>;
  const peak = Math.max(...u.by_day.map((d) => d.requests));
  return (
    <div className="usage">
      <div className="bars" role="img" aria-label={`Requests per day over the last ${u.days} days`}>
        {u.by_day.map((d) => (
          <span key={d.date} style={{ height: `${Math.max(6, (d.requests / peak) * 100)}%` }} title={`${day(d.date)}: ${d.requests} requests, ${d.errors} errors`} />
        ))}
      </div>
      <table className="compact">
        <thead><tr><th scope="col">Endpoint</th><th scope="col" className="num">Requests</th></tr></thead>
        <tbody>{Object.entries(u.by_endpoint).map(([p, n]) => <tr key={p}><td><code>{p}</code></td><td className="num">{n}</td></tr>)}</tbody>
      </table>
      <p className="small muted">Status codes: {Object.entries(u.by_status).map(([s, n]) => `${s} × ${n}`).join(" · ")}</p>
    </div>
  );
}

function KeyManager({ me }: { me: Account }) {
  const keys = useAsync<ApiKey[]>(() => account.keys(), []);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<Scope[]>(["valuation:read"]);
  const [created, setCreated] = useState<NewApiKey | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const active = (keys.data ?? []).filter((k) => k.status === "active").length;

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      setCreated(await account.createKey(name.trim(), scopes));
      setName("");
      keys.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "unexpected", String(err)));
    }
  };
  const revoke = async (k: ApiKey) => {
    if (!window.confirm(`Revoke “${k.name}” (${k.prefix}…)? Requests with it fail immediately. This cannot be undone.`)) return;
    try {
      await account.revokeKey(k.id);
      keys.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "unexpected", String(err)));
    }
  };

  return (
    <div className="stack">
      {created && <NewKeyPanel created={created} onDone={() => setCreated(null)} />}
      {!created && (
        <form className="card" onSubmit={create} aria-labelledby="create-h">
          <h3 id="create-h">Create a key</h3>
          {error && <Notice tone="danger" title={error.message} />}
          <div className="field">
            <label htmlFor="key-name">Name</label>
            <input id="key-name" type="text" maxLength={80} required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. repair-shop backend (production)" />
          </div>
          <fieldset>
            <legend>Scopes</legend>
            {me.scopes_available.map((s) => (
              <label key={s} className="check block">
                <input type="checkbox" checked={scopes.includes(s)}
                  onChange={(e) => setScopes(e.target.checked ? [...scopes, s] : scopes.filter((x) => x !== s))} />
                <code>{s}</code> <span className="small muted">{SCOPE_HELP[s]}</span>
              </label>
            ))}
          </fieldset>
          <p className="small muted">
            Each key: {me.limits.rate_limit_per_minute} requests/minute and {me.limits.daily_quota} requests/day
            (UTC). Up to {me.limits.max_keys} active keys ({active} in use).
          </p>
          <button type="submit" className="btn primary" disabled={!name.trim() || scopes.length === 0 || active >= me.limits.max_keys}>Create key</button>
        </form>
      )}

      <section className="card" aria-labelledby="keys-h">
        <h3 id="keys-h">Your keys</h3>
        {keys.loading && <Loading lines={2} />}
        {keys.error && <ErrorState error={keys.error} onRetry={keys.reload} what="your keys" />}
        {keys.data?.length === 0 && <p className="muted">No keys yet.</p>}
        {keys.data && keys.data.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th scope="col">Key</th><th scope="col">Scopes</th><th scope="col">Created</th><th scope="col">Last used</th>
                  <th scope="col" className="num">Today</th><th scope="col" className="num">30 days</th><th scope="col">Limits</th><th scope="col"><span className="visually-hidden">Actions</span></th></tr>
              </thead>
              <tbody>
                {keys.data.map((k) => (
                  <Fragment key={k.id}>
                    <tr className={k.status === "revoked" ? "dim" : undefined}>
                      <td><strong>{k.name}</strong><div><code>{k.prefix}…</code> <span className={`badge ${k.status === "active" ? "good" : "none"}`}>{k.status === "active" ? "Active" : `Revoked ${day(k.revoked_at)}`}</span></div></td>
                      <td>{k.scopes.map((s) => <div key={s}><code>{s}</code></div>)}</td>
                      <td>{day(k.created_at)}</td>
                      <td>{k.last_used_at ? ago(`${k.last_used_at}Z`) : "Never"}</td>
                      <td className="num">{k.requests_today} / {k.daily_quota}</td>
                      <td className="num">{k.requests_30d}</td>
                      <td className="small">{k.rate_limit_per_minute}/min</td>
                      <td>
                        <button type="button" className="btn link" aria-expanded={open === k.id} onClick={() => setOpen(open === k.id ? null : k.id)}>Usage</button>
                        {k.status === "active" && <button type="button" className="btn link danger" onClick={() => revoke(k)}>Revoke</button>}
                      </td>
                    </tr>
                    {open === k.id && (
                      <tr><td colSpan={8}><UsagePanel id={k.id} /></td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export function DevelopersPage() {
  const titleRef = usePageTitle("Developers");
  return (
    <div className="container">
      <p className="eyebrow">FlipValue API · version 1</p>
      <h1 ref={titleRef} tabIndex={-1}>Build on FlipValue's resale and price data</h1>
      <p className="lead">
        The same evidence-based valuations and marketplace observations as this website, over a versioned JSON API
        with scoped keys, per-key limits and usage you can see.
      </p>

      <div className="dev-grid">
        <section aria-labelledby="keys-section">
          <h2 id="keys-section">API keys</h2>
          <AccountGate purpose="Sign in to create and manage API keys.">
            {(me, signOut) => (
              <>
                <p className="small muted">Signed in as {me.email}. <button type="button" className="btn link" onClick={signOut}>Sign out</button></p>
                <KeyManager me={me} />
              </>
            )}
          </AccountGate>
        </section>

        <aside className="stack" aria-label="Quick reference">
          <section className="card">
            <h2>Authentication</h2>
            <p>Send your key in the <code>X-API-Key</code> header over HTTPS, from your server only. Keys are never accepted in URLs.</p>
            <p className="small muted">Every response carries <code>X-RateLimit-Limit</code>, <code>X-RateLimit-Remaining</code>, <code>X-RateLimit-Reset</code> and, for keys with a daily quota, <code>X-Quota-*</code>. Revoked keys fail on the next request.</p>
          </section>
          <section className="card">
            <h2>Data honesty</h2>
            <p className="small">A value with too little evidence is returned as <code>available: false</code> with a reason — never estimated. <code>mock: true</code> marks synthetic development data, which production never serves.</p>
          </section>
        </aside>
      </div>

      <section aria-labelledby="ref-h" style={{ marginTop: 40 }}>
        <h2 id="ref-h">Reference</h2>
        <div className="table-wrap card">
          <table>
            <thead><tr><th scope="col">Method</th><th scope="col">Path</th><th scope="col">Scope · returns</th></tr></thead>
            <tbody>{ENDPOINTS.map(([m, p, d]) => <tr key={p}><td><span className="method">{m}</span></td><td><code>{p}</code></td><td>{d}</td></tr>)}</tbody>
          </table>
        </div>
        <div className="grid code-grid" style={{ marginTop: 16 }}>
          <div><h3>Example request</h3><pre className="code"><code>{EXAMPLE_REQUEST}</code></pre></div>
          <div><h3>Example response (abridged)</h3><pre className="code"><code>{EXAMPLE_RESPONSE}</code></pre></div>
        </div>
        <h3 style={{ marginTop: 24 }}>Errors</h3>
        <p className="small muted">Every error is <code>{`{"error":{"code","message","request_id"}}`}</code>. Quote the <code>request_id</code> when asking for help.</p>
        <div className="table-wrap card">
          <table>
            <thead><tr><th scope="col">Status</th><th scope="col">Code</th><th scope="col">What to do</th></tr></thead>
            <tbody>{ERRORS.map(([s, c, d]) => <tr key={c}><td className="num">{s}</td><td><code>{c}</code></td><td>{d}</td></tr>)}</tbody>
          </table>
        </div>
        <p className="small muted" style={{ marginTop: 12 }}>
          Full schemas: the interactive <a href="/docs">OpenAPI reference</a>. Repair-shop integrations (FixMyTech) can
          also use the stable partner endpoint described on the <Link to="/api">partner API page</Link>.
        </p>
      </section>
    </div>
  );
}
