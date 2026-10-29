import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api";
import { LineChart } from "../components/LineChart";
import { EmptyState, ErrorState, Loading } from "../components/ui";
import { GRADE_LABEL, REGIONS } from "../content";
import { money, month } from "../format";
import { useAsync, usePageTitle } from "../hooks";
import type { Currency, Grade, Region, TrendPoint } from "../types";

/** First point to last point of the main series: how much value the phone has lost over the period shown. */
function Change({ series, currency }: { series: Record<string, TrendPoint[]>; currency: Currency }) {
  const main = series.completed_sale ?? series.listing ?? series.estimate;
  if (!main || main.length < 2) return null;
  const first = main[0], last = main[main.length - 1];
  const pct = Math.round(((last.median - first.median) / first.median) * 100);
  const years = (Date.parse(`${last.month}-01`) - Date.parse(`${first.month}-01`)) / (365.25 * 86_400_000);
  return (
    <dl className="stat-row">
      <div><dt>{month(first.month)}</dt><dd>{money(first.median, currency)}</dd></div>
      <div><dt>{month(last.month)}</dt><dd>{money(last.median, currency)}</dd></div>
      <div><dt>Change</dt><dd className={pct < 0 ? "down" : "up"}>{pct > 0 ? "+" : ""}{pct}%</dd></div>
      <div><dt>Over</dt><dd>{years >= 1 ? `${years.toFixed(1)} years` : `${main.length} months`}</dd></div>
    </dl>
  );
}

export function TrendsPage() {
  const titleRef = usePageTitle("Price trends");
  const [params] = useSearchParams();
  const catalogue = useAsync(() => api.catalogue(), []);
  const [modelId, setModelId] = useState(params.get("model") ?? "");
  const [storage, setStorage] = useState<number | null>(null);
  const [region, setRegion] = useState<Region>("IN");
  const [grade, setGrade] = useState<Grade>("good");
  const model = catalogue.data?.find((m) => m.id === modelId);

  useEffect(() => {
    if (model) setStorage((s) => (s && model.storage_gb.includes(s) ? s : model.storage_gb[0]));
  }, [model]);

  const trend = useAsync(
    () => (model && storage ? api.trend({ model_id: model.id, storage_gb: storage, region, grade }) : Promise.resolve(null)),
    [model?.id, storage, region, grade],
  );

  return (
    <div className="container">
      <h1 ref={titleRef} tabIndex={-1}>Price trends</h1>
      <p className="lead">
        How a phone's resale price has moved since it launched. Real observed prices are drawn as solid lines; where
        there aren't enough of them yet, FlipValue's modelled estimate is drawn as a dashed line.
      </p>
      {catalogue.error && <ErrorState error={catalogue.error} onRetry={catalogue.reload} what="the device list" />}
      <div className="card">
        <div className="grid">
          <div className="field">
            <label htmlFor="t-model">Phone</label>
            <select id="t-model" value={modelId} onChange={(e) => setModelId(e.target.value)}>
              <option value="">Choose a phone…</option>
              {(catalogue.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.manufacturer} {m.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="t-storage">Storage</label>
            <select id="t-storage" value={storage ?? ""} disabled={!model} onChange={(e) => setStorage(Number(e.target.value))}>
              {(model?.storage_gb ?? []).map((s) => <option key={s} value={s}>{s} GB</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="t-region">Market</label>
            <select id="t-region" value={region} onChange={(e) => setRegion(e.target.value as Region)}>
              {REGIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="t-grade">Condition</label>
            <select id="t-grade" value={grade} onChange={(e) => setGrade(e.target.value as Grade)}>
              {(Object.keys(GRADE_LABEL) as Grade[]).map((g) => <option key={g} value={g}>{GRADE_LABEL[g]}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div style={{ marginTop: 16 }} aria-live="polite">
        {!model && <EmptyState title="Choose a phone to see its price history" />}
        {model && trend.loading && <Loading label="Loading history" />}
        {model && trend.error && <ErrorState error={trend.error} onRetry={trend.reload} what="the price history" />}
        {model && trend.data && !trend.data.available && (
          <EmptyState title="Not enough price history yet">
            <p>{trend.data.reason}</p>
            <p>
              A chart needs at least three months with {trend.data.min_observations_per_month}+ real prices each for{" "}
              {model.name} {trend.data.storage_gb} GB in “{GRADE_LABEL[grade]}” condition in this market.
            </p>
          </EmptyState>
        )}
        {model && trend.data?.available && (
          <section className="card" aria-labelledby="chart-h">
            <h2 id="chart-h">
              {model.manufacturer} {model.name} {trend.data.storage_gb} GB · {GRADE_LABEL[grade]} ·{" "}
              {REGIONS.find((r) => r.value === region)?.label}
            </h2>
            <Change series={trend.data.series} currency={trend.data.currency} />
            <LineChart series={trend.data.series} currency={trend.data.currency} />
            <p className="small muted">
              Solid lines: the median of at least {trend.data.min_observations_per_month} real prices that month; months
              with fewer are left out. Dashed line: FlipValue's estimate, which starts at about 80% of the launch price
              and declines to today's estimated price. It shows the general shape, not exact past prices.
            </p>
          </section>
        )}
      </div>
    </div>
  );
}
