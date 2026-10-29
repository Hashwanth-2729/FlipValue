import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { PriceHistoryChart } from "../components/PriceHistoryChart";
import { EmptyState, ErrorState, Loading, Notice } from "../components/ui";
import { ago, count, day, money } from "../format";
import { useAsync, usePageTitle } from "../hooks";
import type { MarketPrices, Offer, OfferCondition, OfferGroup } from "../types";

const GROUPS: { key: OfferGroup; label: string; help: string }[] = [
  { key: "new", label: "New", help: "Retail price of a new unit." },
  { key: "refurbished", label: "Refurbished", help: "What a refurbisher charges. Not what you would receive for selling." },
  { key: "used", label: "Used listings", help: "Asking prices of used phones; sale prices are usually lower." },
  { key: "buyback", label: "Buyback quotes", help: "What a dealer offered to pay a seller." },
];

const MATCH_LABEL: Record<string, string> = {
  exact: "Exact model code",
  strong: "Same model & storage",
  variant_mismatch: "Different storage",
  variant_unknown: "Storage not stated",
  similar: "Different model",
};

const SELLER_LABEL: Record<string, string> = {
  marketplace_seller: "Marketplace seller", retailer: "Retailer", manufacturer: "Manufacturer",
  refurbisher: "Refurbisher", dealer: "Dealer",
};

/** The store a row is about: the store an estimate is modelled for, otherwise the source it was read from. */
function storeOf(o: Offer): string {
  return o.source.estimated ? o.seller ?? o.source.name : o.source.name;
}

function FreshnessBadge({ offer }: { offer: Offer }) {
  if (offer.is_mock) return <span className="badge mock">Fixture</span>;
  if (offer.source.estimated) {
    return <span className="badge warn" title="Modelled by FlipValue from approximate price ranges; not a live listing">Estimate</span>;
  }
  return offer.freshness === "fresh"
    ? <span className="badge good" title="Retrieved within the freshness window">Fresh</span>
    : <span className="badge warn" title="Older than the freshness window; the price may have changed">Stale</span>;
}

function OfferRow({ o }: { o: Offer }) {
  const specs = [o.storage_gb && `${o.storage_gb} GB`, o.ram_gb && `${o.ram_gb} GB RAM`, o.color].filter(Boolean);
  return (
    <tr className={o.availability === "out_of_stock" ? "dim" : undefined}>
      <td>
        <strong>{storeOf(o)}</strong>
        {o.source.estimated
          ? <div className="small muted">FlipValue estimate · not a live listing</div>
          : o.seller && <div className="small muted">{o.seller}{o.seller_type && ` · ${SELLER_LABEL[o.seller_type] ?? o.seller_type}`}</div>}
      </td>
      <td>
        <div className="offer-title">{o.title}</div>
        <div className="chips">{specs.map((s) => <span key={String(s)} className="chip">{s}</span>)}</div>
        <details className="match">
          <summary>{MATCH_LABEL[o.match.category] ?? o.match.category} · match {o.match.score}/100</summary>
          <ul>{o.match.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </details>
      </td>
      <td className="num">
        <span className="price">{money(o.price, o.currency)}</span>
        {o.mrp && <div className="small muted">MRP <s>{money(o.mrp, o.currency)}</s>{o.discount_pct !== null && ` · ${o.discount_pct}% off`}</div>}
        {o.delivery_note && <div className="small muted">{o.delivery_note}</div>}
      </td>
      <td>
        {o.availability === "in_stock" ? "In stock" : o.availability === "out_of_stock" ? "Out of stock" : <span className="muted">{o.source.estimated ? "—" : "Not stated"}</span>}
      </td>
      <td>
        <FreshnessBadge offer={o} />
        {!o.source.estimated && <div className="small muted" title={o.retrieved_at}>{ago(o.retrieved_at)}</div>}
      </td>
      <td>
        {o.url ? (
          <a href={o.url} target="_blank" rel="noopener noreferrer nofollow">View listing<span className="visually-hidden"> on {o.source.name} (opens in a new tab)</span></a>
        ) : <span className="small muted">{o.is_mock ? "No link (fixture)" : o.source.estimated ? "Estimate, no listing" : "No link supplied"}</span>}
      </td>
    </tr>
  );
}

function OfferTable({ offers, caption }: { offers: Offer[]; caption: string }) {
  return (
    <div className="table-wrap">
      <table className="offers">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Store</th><th scope="col">Listing</th><th scope="col" className="num">Price</th>
            <th scope="col">Stock</th><th scope="col">Type</th><th scope="col">Link</th>
          </tr>
        </thead>
        <tbody>{offers.map((o) => <OfferRow key={o.id} o={o} />)}</tbody>
      </table>
    </div>
  );
}

function Summary({ data, group }: { data: MarketPrices; group: OfferGroup }) {
  const s = data.summary[group];
  return (
    <dl className="stat-row">
      <div><dt>Lowest {GROUPS.find((g) => g.key === group)?.label.toLowerCase()}</dt><dd>{money(s.lowest, data.currency)}</dd></div>
      <div><dt>Spread across offers</dt><dd>{s.spread === null ? <span className="muted">needs 2+ offers</span> : money(s.spread, data.currency)}</dd></div>
      <div><dt>Offers</dt><dd>{s.count}</dd></div>
      <div><dt>MRP (retailer-supplied)</dt><dd>{data.mrp ? money(data.mrp.value, data.currency) : <span className="muted">not supplied</span>}</dd></div>
    </dl>
  );
}

export function PricesPage() {
  const titleRef = usePageTitle("Compare prices");
  const [params, setParams] = useSearchParams();
  const catalogue = useAsync(() => api.catalogue(), []);
  const modelId = params.get("model") ?? "";
  const model = catalogue.data?.find((m) => m.id === modelId);
  const [storage, setStorage] = useState<number | null>(Number(params.get("storage")) || null);
  const [group, setGroup] = useState<OfferGroup>("new");
  const [source, setSource] = useState("all");
  const [maxPrice, setMaxPrice] = useState("");
  const [inStockOnly, setInStockOnly] = useState(false);
  const [sellerType, setSellerType] = useState("all");

  useEffect(() => {
    if (model) setStorage((s) => (s && model.storage_gb.includes(s) ? s : model.storage_gb[0]));
  }, [model]);

  const offers = useAsync(
    () => (model && storage ? api.offers(model.id, storage) : Promise.resolve(null)), [model?.id, storage],
  );
  const historyCondition: OfferCondition = group === "refurbished" ? "refurbished" : group === "used" ? "used" : "new";
  const history = useAsync(
    () => (model && storage ? api.priceHistory(model.id, storage, historyCondition) : Promise.resolve(null)),
    [model?.id, storage, historyCondition],
  );

  const data = offers.data;
  const visible = useMemo(() => {
    if (!data) return [];
    const cap = Number(maxPrice);
    return data.groups[group].filter((o) =>
      (source === "all" || storeOf(o) === source) &&
      (!cap || o.price <= cap) &&
      (!inStockOnly || o.availability === "in_stock") &&
      (sellerType === "all" || o.seller_type === sellerType));
  }, [data, group, source, maxPrice, inStockOnly, sellerType]);
  const sources = data ? [...new Set(data.groups[group].map(storeOf))].sort() : [];
  const sellerTypes = data ? [...new Set(data.groups[group].map((o) => o.seller_type).filter(Boolean))] as string[] : [];

  return (
    <div className="container">
      <p className="eyebrow">Marketplace comparison · India</p>
      <h1 ref={titleRef} tabIndex={-1}>Compare prices across sources</h1>
      <p className="lead">
        Prices for exactly the phone and storage you pick, store by store. New, refurbished, used and buyback prices
        are kept apart: they measure different things.
      </p>
      {catalogue.error && <ErrorState error={catalogue.error} onRetry={catalogue.reload} what="the device list" />}

      <div className="card selector">
        <div className="field">
          <label htmlFor="p-model">Phone</label>
          <select id="p-model" value={modelId} onChange={(e) => setParams(e.target.value ? { model: e.target.value } : {})}>
            <option value="">Choose a phone…</option>
            {(catalogue.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.manufacturer} {m.name}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="p-storage">Storage</label>
          <select id="p-storage" value={storage ?? ""} disabled={!model} onChange={(e) => setStorage(Number(e.target.value))}>
            {(model?.storage_gb ?? []).map((s) => <option key={s} value={s}>{s} GB</option>)}
          </select>
        </div>
      </div>

      <div className="stack" style={{ marginTop: 16 }} aria-live="polite">
        {!model && <EmptyState title="Choose a phone to compare prices" />}
        {model && offers.loading && <Loading label="Loading offers" />}
        {model && offers.error && <ErrorState error={offers.error} onRetry={offers.reload} what="prices" />}
        {data && (
          <>
            {data.mock_data_included && (
              <Notice tone="mock" title="Fixture offers — not real listings">
                <p>No marketplace is connected in this environment, so these offers are invented test fixtures with no links. They show how comparison works; they are not prices you can buy at.</p>
              </Notice>
            )}

            <div role="tablist" aria-label="Price type" className="tabs">
              {GROUPS.map((g) => (
                <button key={g.key} role="tab" type="button" aria-selected={group === g.key}
                  className="tab" onClick={() => { setGroup(g.key); setSource("all"); }}>
                  {g.label} <span className="tab-count">{data.summary[g.key].count}</span>
                </button>
              ))}
            </div>
            <section className="card" role="tabpanel" aria-label={GROUPS.find((g) => g.key === group)?.label}>
              <p className="small muted" style={{ marginTop: 0 }}>{GROUPS.find((g) => g.key === group)?.help}</p>
              <Summary data={data} group={group} />
              <div className="filters">
                <div className="field">
                  <label htmlFor="f-source">Store</label>
                  <select id="f-source" value={source} onChange={(e) => setSource(e.target.value)}>
                    <option value="all">All stores</option>
                    {sources.map((name) => <option key={name} value={name}>{name}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="f-max">Max price ({data.currency})</label>
                  <input id="f-max" type="number" inputMode="numeric" min={0} value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="f-seller">Seller type</label>
                  <select id="f-seller" value={sellerType} onChange={(e) => setSellerType(e.target.value)}>
                    <option value="all">Any</option>
                    {sellerTypes.map((t) => <option key={t} value={t}>{SELLER_LABEL[t] ?? t}</option>)}
                  </select>
                </div>
                <label className="check">
                  <input type="checkbox" checked={inStockOnly} onChange={(e) => setInStockOnly(e.target.checked)} /> In stock only
                </label>
              </div>
              {visible.length > 0 ? (
                <OfferTable offers={visible} caption={`${GROUPS.find((g) => g.key === group)?.label} offers, lowest price first`} />
              ) : (
                <p className="empty-line">
                  {data.summary[group].count === 0
                    ? `No ${GROUPS.find((g) => g.key === group)?.label.toLowerCase()} offers retrieved for ${model?.name} ${data.storage_gb} GB in the last ${data.max_age_days} days. Nothing is filled in for missing sources.`
                    : "No offers match these filters."}
                </p>
              )}
              <p className="small muted">
                Sorted by price, out-of-stock last. “Fresh” means retrieved within {data.fresh_hours} hours; older offers
                are marked stale and dropped after {data.max_age_days} days. “Estimate” rows are modelled, not
                retrieved. Prices exclude delivery unless stated.
              </p>
              {(group === "new" || group === "refurbished") && model && storage && (
                <Link className="btn" to={`/watchlist?model=${model.id}&storage=${storage}&condition=${group}`}>
                  Watch this price
                </Link>
              )}
            </section>

            {data.alternatives.length > 0 && (
              <section className="card" aria-labelledby="alt-h">
                <h2 id="alt-h">Similar, but not the same phone</h2>
                <p className="small muted">
                  Other storage sizes or neighbouring models found in the same searches. They are never used for the
                  lowest price above. Open “match” on a row to see why.
                </p>
                <OfferTable offers={data.alternatives} caption="Similar alternatives" />
              </section>
            )}

            <section className="card" aria-labelledby="hist-h">
              <h2 id="hist-h">Observed price history · {historyCondition}</h2>
              {history.loading && <Loading label="Loading history" lines={2} />}
              {history.error && <ErrorState error={history.error} onRetry={history.reload} what="price history" />}
              {history.data && !history.data.available && (
                <p className="empty-line">{history.data.reason} FlipValue does not draw history from a single price.</p>
              )}
              {history.data?.available && (
                <>
                  <dl className="stat-row">
                    <div><dt>Lowest seen</dt><dd>{money(history.data.lowest?.price, history.data.currency)}<span className="small muted"> {day(history.data.lowest?.date)}</span></dd></div>
                    <div><dt>Highest seen</dt><dd>{money(history.data.highest?.price, history.data.currency)}<span className="small muted"> {day(history.data.highest?.date)}</span></dd></div>
                    <div><dt>Latest change</dt><dd className={history.data.change && history.data.change.amount < 0 ? "down" : "up"}>{history.data.change ? `${history.data.change.amount > 0 ? "+" : ""}${money(history.data.change.amount, history.data.currency)} (${history.data.change.pct}%)` : "—"}</dd></div>
                    <div><dt>Observations</dt><dd>{count(history.data.observation_count, "price")} on {history.data.observed_days} days</dd></div>
                  </dl>
                  <PriceHistoryChart series={history.data.series} currency={history.data.currency} />
                  {history.data.gaps.length > 0 && (
                    <p className="small muted">Gaps with no retrieval: {history.data.gaps.map((g) => `${day(g.from)} → ${day(g.to)} (${g.days} days)`).join("; ")}.</p>
                  )}
                </>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
