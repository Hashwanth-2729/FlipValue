import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { account, api, ApiError } from "../api";
import { AccountGate } from "../components/AccountGate";
import { EmptyState, ErrorState, Loading, Notice } from "../components/ui";
import { ago, day, money } from "../format";
import { useAsync, usePageTitle } from "../hooks";
import type { PriceAlert, WatchItem } from "../types";

function AddWatch({ onAdded }: { onAdded: () => void }) {
  const [params] = useSearchParams();
  const catalogue = useAsync(() => api.catalogue(), []);
  const [modelId, setModelId] = useState(params.get("model") ?? "");
  const [storage, setStorage] = useState<number | null>(Number(params.get("storage")) || null);
  const [condition, setCondition] = useState<"new" | "refurbished">(params.get("condition") === "refurbished" ? "refurbished" : "new");
  const [target, setTarget] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const model = catalogue.data?.find((m) => m.id === modelId);

  useEffect(() => {
    if (model) setStorage((s) => (s && model.storage_gb.includes(s) ? s : model.storage_gb[0]));
  }, [model]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!model || !storage) return;
    setError(null);
    try {
      await account.watch({ model_id: model.id, storage_gb: storage, condition, ...(target ? { target_price: target } : {}) });
      setTarget("");
      onAdded();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "unexpected", String(err)));
    }
  };

  return (
    <form className="card" onSubmit={submit} aria-labelledby="add-h">
      <h2 id="add-h">Watch a price</h2>
      {error && <Notice tone="danger" title={error.message} />}
      <div className="filters">
        <div className="field">
          <label htmlFor="w-model">Phone</label>
          <select id="w-model" value={modelId} required onChange={(e) => setModelId(e.target.value)}>
            <option value="">Choose a phone…</option>
            {(catalogue.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.manufacturer} {m.name}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="w-storage">Storage</label>
          <select id="w-storage" value={storage ?? ""} disabled={!model} onChange={(e) => setStorage(Number(e.target.value))}>
            {(model?.storage_gb ?? []).map((s) => <option key={s} value={s}>{s} GB</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="w-condition">Condition</label>
          <select id="w-condition" value={condition} onChange={(e) => setCondition(e.target.value as "new" | "refurbished")}>
            <option value="new">New</option>
            <option value="refurbished">Refurbished</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="w-target">Alert at or below (INR, optional)</label>
          <input id="w-target" type="number" inputMode="decimal" min={1} step="0.01" value={target} onChange={(e) => setTarget(e.target.value)} />
        </div>
      </div>
      <button type="submit" className="btn primary" disabled={!model}>Add to watchlist</button>
    </form>
  );
}

function Watchlist() {
  const items = useAsync<WatchItem[]>(() => account.watchlist(), []);
  const alerts = useAsync<PriceAlert[]>(() => account.alerts(), []);
  const remove = async (w: WatchItem) => {
    if (!window.confirm(`Stop watching ${w.product_name} ${w.storage_gb} GB (${w.condition})?`)) return;
    await account.unwatch(w.id);
    items.reload();
    alerts.reload();
  };
  const read = async (a: PriceAlert) => {
    await account.markRead(a.id);
    alerts.reload();
    items.reload();
  };

  return (
    <div className="stack">
      <Notice title="How alerts work">
        <p>
          An alert is created only when FlipValue actually retrieves an offer for exactly this phone, storage and
          condition at or below your target. Alerts appear here; email delivery is not configured yet. Prices refresh
          only as often as each source allows.
        </p>
      </Notice>
      <AddWatch onAdded={items.reload} />

      <section className="card" aria-labelledby="alerts-h">
        <h2 id="alerts-h">Alerts</h2>
        {alerts.loading && <Loading lines={1} />}
        {alerts.error && <ErrorState error={alerts.error} onRetry={alerts.reload} what="alerts" />}
        {alerts.data?.length === 0 && <p className="muted">No qualifying price has been observed yet.</p>}
        <ul className="alert-list">
          {alerts.data?.map((a) => (
            <li key={a.id} className={a.read ? "dim" : undefined}>
              <strong>{a.product_name} {a.storage_gb} GB · {a.condition}</strong>: {money(a.price, a.currency)} at {a.source_name}
              {a.is_mock && <span className="badge mock">Fixture</span>}
              <div className="small muted">{a.reason}. Retrieved {ago(`${a.offer_retrieved_at}Z`)}.
                {a.url && <> <a href={a.url} target="_blank" rel="noopener noreferrer nofollow">View listing</a></>}
              </div>
              {!a.read && <button type="button" className="btn link" onClick={() => read(a)}>Mark as read</button>}
            </li>
          ))}
        </ul>
      </section>

      <section className="card" aria-labelledby="watch-h">
        <h2 id="watch-h">Watching</h2>
        {items.loading && <Loading lines={2} />}
        {items.error && <ErrorState error={items.error} onRetry={items.reload} what="your watchlist" />}
        {items.data?.length === 0 && <EmptyState title="Nothing watched yet">Add a phone above, or use “Watch this price” on the price comparison.</EmptyState>}
        {items.data && items.data.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead><tr><th scope="col">Phone</th><th scope="col" className="num">Target</th><th scope="col" className="num">Lowest current</th><th scope="col">Since</th><th scope="col"><span className="visually-hidden">Actions</span></th></tr></thead>
              <tbody>
                {items.data.map((w) => (
                  <tr key={w.id}>
                    <td><Link to={`/prices?model=${w.model_id}&storage=${w.storage_gb}`}>{w.product_name} {w.storage_gb} GB</Link> <span className="badge none">{w.condition}</span>
                      {w.unread_alerts > 0 && <span className="badge good">{w.unread_alerts} new</span>}</td>
                    <td className="num">{w.target_price ? money(w.target_price, w.currency) : <span className="muted">none</span>}</td>
                    <td className="num">{w.lowest_current_price !== null ? money(w.lowest_current_price, w.currency) : <span className="muted">no current offer</span>}
                      {w.lowest_current_retrieved_at && <div className="small muted">{ago(`${w.lowest_current_retrieved_at}Z`)}</div>}</td>
                    <td>{day(w.created_at)}</td>
                    <td><button type="button" className="btn link danger" onClick={() => remove(w)}>Remove</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export function WatchlistPage() {
  const titleRef = usePageTitle("Watchlist");
  return (
    <div className="container">
      <h1 ref={titleRef} tabIndex={-1}>Watchlist and price alerts</h1>
      <AccountGate purpose="Sign in to keep a watchlist and receive price alerts.">
        {(me, signOut) => (
          <>
            <p className="small muted">Signed in as {me.email}. <button type="button" className="btn link" onClick={signOut}>Sign out</button></p>
            <Watchlist />
          </>
        )}
      </AccountGate>
    </div>
  );
}
