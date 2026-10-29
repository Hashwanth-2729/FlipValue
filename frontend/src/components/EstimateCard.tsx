import { QUALITY_LABEL, RANGE_HELP } from "../content";
import { count, day, money, month } from "../format";
import type { Currency, Estimate } from "../types";

function RangeBar({ e, currency }: { e: Estimate; currency: Currency }) {
  const span = e.high - e.low;
  // Pad the track so the range never touches the ends; the bar is illustrative, the numbers are the data.
  const min = e.low - span * 0.25;
  const max = e.high + span * 0.25;
  const pos = (v: number) => (max === min ? 50 : ((v - min) / (max - min)) * 100);
  return (
    <div>
      <div
        className="range-bar"
        role="img"
        aria-label={`Range ${money(e.low, currency)} to ${money(e.high, currency)}, estimate ${money(e.value, currency)}`}
      >
        <div className="span" style={{ left: `${pos(e.low)}%`, width: `${Math.max(pos(e.high) - pos(e.low), 1)}%` }} />
        <div className="mid" style={{ left: `${pos(e.value)}%` }} />
      </div>
      <div className="range-labels">
        <span>Low {money(e.low, currency)}</span>
        <span>High {money(e.high, currency)}</span>
      </div>
    </div>
  );
}

export function EstimateCard({ title, estimate, currency, note }: {
  title: string;
  estimate: Estimate;
  currency: Currency;
  note?: string;
}) {
  const mock = estimate.sources.some((s) => s.is_mock);
  const modelled = estimate.quality === "modelled";
  return (
    <article className="card" aria-label={title}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="eyebrow">{title}</p>
        <div className="row" style={{ gap: 6 }}>
          {mock ? (
            <span className="badge mock">Mock data · not evidence</span>
          ) : (
            <span className={`badge ${estimate.quality === "evidence_backed" ? "good" : "warn"}`}>
              {QUALITY_LABEL[estimate.quality]}
            </span>
          )}
        </div>
      </div>
      <p className="value-big">{money(estimate.value, currency)}</p>
      <p className="muted small">
        {modelled ? "Rough guide" : "Middle (median) price"} · gross, before selling fees
      </p>
      <RangeBar e={estimate} currency={currency} />
      {modelled ? (
        <ul className="facts">
          <li>Likely range {money(estimate.low, currency)} – {money(estimate.high, currency)}</li>
          <li>Modelled for {month(estimate.newest_observation.slice(0, 7))} from approximate market price ranges</li>
          <li>Not based on observed sales of this phone</li>
        </ul>
      ) : (
        <>
          <p className="small muted">{RANGE_HELP[estimate.range_method]}</p>
          <ul className="facts">
            <li>Based on {count(estimate.observation_count, estimate.basis_label.replace(/s$/, ""), estimate.basis_label)}</li>
            <li>
              Dated {day(estimate.oldest_observation)} – {day(estimate.newest_observation)}
            </li>
            <li>Source: {estimate.sources.map((s) => s.name).join(", ")}</li>
          </ul>
        </>
      )}
      {note && <p className="small" style={{ marginTop: 12 }}>{note}</p>}
    </article>
  );
}
