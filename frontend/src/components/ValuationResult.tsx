import { Link } from "react-router-dom";

import { FAULT_LABEL, GRADE_HELP, GRADE_LABEL, REGIONS, REPAIR_LABEL } from "../content";
import { day, money } from "../format";
import type { Valuation } from "../types";
import { EstimateCard } from "./EstimateCard";
import { Notice } from "./ui";

export function compareLink(v: Valuation): string {
  const p = new URLSearchParams({ currency: v.currency });
  if (v.as_is) p.set("as_is", String(v.as_is.value));
  if (v.after_repair) p.set("after_repair", String(v.after_repair.value));
  if (v.repair_type) p.set("repair", v.repair_type);
  p.set("label", `${v.device.manufacturer} ${v.device.name} ${v.device.storage_gb} GB`);
  return `/compare?${p}`;
}

const TYPE_ROWS: { key: "buyback" | "refurbished_retail" | "original_retail"; label: string; help: string }[] = [
  { key: "buyback", label: "Dealer buyback", help: "What a dealer offers to pay you. Usually below a private sale." },
  { key: "refurbished_retail", label: "Refurbished retail", help: "What a refurbisher charges for one. Not what you would receive." },
  { key: "original_retail", label: "Original retail (MRP)", help: "As supplied by retailers for this exact variant." },
];
const CONFIDENCE_LABEL = { high: "High confidence", medium: "Medium confidence", low: "Low confidence", insufficient: "No estimate" };

/** The other kinds of value, side by side, each with its own evidence or the reason it is missing. */
function ValueTypes({ v }: { v: Valuation }) {
  const types = v.value_types!;
  return (
    <section className="card" aria-labelledby="types-h">
      <h2 id="types-h">Other kinds of value</h2>
      <p className="small muted">These are different prices, never averaged together.</p>
      <dl className="value-types">
        {TYPE_ROWS.map(({ key, label, help }) => {
          const e = types[key];
          return (
            <div key={key}>
              <dt>{label}<span className="small muted">{help}</span></dt>
              <dd>
                {e.available ? (
                  <>
                    <span className="price">{money(e.value, v.currency)}</span>
                    <span className="small muted"> {money(e.low, v.currency)} – {money(e.high, v.currency)}</span>
                    <div className="small muted">
                      {e.basis?.startsWith("estimate") ? (
                        <><span className="badge warn">Estimate</span> Rough guide, modelled from approximate price ranges</>
                      ) : (
                        <>{CONFIDENCE_LABEL[e.confidence]} · {e.observation_count} {e.basis_label} · newest {day(e.newest_observation)}</>
                      )}
                      {e.sources.some((s) => s.source_type === "estimate") && !e.basis?.startsWith("estimate") && (
                        <span className="badge warn">Includes estimates</span>
                      )}
                      {e.sources.some((s) => s.is_mock) && <span className="badge mock">Fixture</span>}
                    </div>
                  </>
                ) : <span className="muted small">{e.reason}</span>}
              </dd>
            </div>
          );
        })}
      </dl>
      <p className="small"><Link to={`/prices?model=${v.device.model_id}&storage=${v.device.storage_gb}`}>Compare current prices for this phone →</Link></p>
    </section>
  );
}

export function ValuationResult({ v }: { v: Valuation }) {
  const region = REGIONS.find((r) => r.value === v.region)?.label ?? v.region;
  return (
    <div className="stack">
      {v.mock && (
        <Notice tone="mock" title="Mock data — not a real valuation">
          <p>
            These numbers come from synthetic development data. They show how FlipValue works; they are not market
            prices. Do not use them to buy or sell a phone.
          </p>
        </Notice>
      )}
      {v.condition.safety.map((s) => (
        <Notice key={s} tone="danger" title="Safety">
          <p>{s}</p>
        </Notice>
      ))}

      {v.as_is?.quality === "modelled" && (
        <Notice tone="warn" title="This is a FlipValue estimate">
          <p>
            There aren't enough real sales of the {v.device.name} yet, so this price is modelled from current new,
            refurbished and used price ranges. Use it as a rough guide to what a buyer might pay for a phone in{" "}
            “{GRADE_LABEL[v.condition.grade].toLowerCase()}” condition, not as an offer.
          </p>
        </Notice>
      )}
      {v.as_is ? (
        <EstimateCard
          title={`What your ${v.device.name} ${v.device.storage_gb} GB is worth · ${GRADE_LABEL[v.condition.grade]} condition`}
          estimate={v.as_is}
          currency={v.currency}
          note={v.as_is.quality === "modelled" ? "Selling privately (OLX, friends) usually gets the most. Dealers and buyback apps pay less but faster — see Dealer buyback below." : undefined}
        />
      ) : (
        <article className="card" aria-label="Estimate unavailable">
          <p className="eyebrow">Estimated value as it is</p>
          <h2>Not enough evidence for an estimate</h2>
          <p>{v.as_is_unavailable_reason}</p>
          <p className="muted">
            FlipValue has neither enough recent prices nor an estimate for this exact model, storage, market and
            condition, so it shows no number rather than an invented one.
          </p>
          <ul>
            <li>Check whether another storage size or market has evidence on the <Link to="/devices">devices page</Link>.</li>
            <li>Check again later: estimates appear once enough prices have been collected.</li>
          </ul>
        </article>
      )}

      {v.repair_type && (
        v.after_repair ? (
          <EstimateCard
            title={`After ${REPAIR_LABEL[v.repair_type].toLowerCase()}`}
            estimate={v.after_repair}
            currency={v.currency}
            note={`Assumes the repair is done well and the phone then grades “${GRADE_LABEL[v.assumed_grade_after_repair ?? "good"]}”. The repair cost is not included — see Repair or sell.`}
          />
        ) : (
          <article className="card" aria-label="After-repair estimate unavailable">
            <p className="eyebrow">After {REPAIR_LABEL[v.repair_type].toLowerCase()}</p>
            <p>{v.after_repair_unavailable_reason}</p>
          </article>
        )
      )}

      {v.trade_in && <EstimateCard title="Trade-in offers seen" estimate={v.trade_in} currency={v.currency}
        note="Trade-in offers are what retailers credit you, usually less than a private sale." />}

      {v.value_types && <ValueTypes v={v} />}

      <section className="card" aria-labelledby="condition-h">
        <h2 id="condition-h">Condition used</h2>
        <p>
          <span className="badge good">{GRADE_LABEL[v.condition.grade]}</span>{" "}
          <span className="muted">{GRADE_HELP[v.condition.grade]}</span>
        </p>
        {v.condition.reasons.map((r) => <p key={r}>{r}</p>)}
        {v.condition.faults.length > 0 && (
          <p>Reported problems: {v.condition.faults.map((f) => FAULT_LABEL[f] ?? f).join(", ")}.</p>
        )}
        <p className="small muted">
          Based on your answers. FlipValue has not inspected or tested the phone; a buyer will check it.
        </p>
        {v.condition.uncertainties.length > 0 && (
          <Notice tone="warn" title="Things that could change the grade">
            <ul>{v.condition.uncertainties.map((u) => <li key={u}>{u}</li>)}</ul>
          </Notice>
        )}
        {v.condition.not_used.map((n) => <p key={n} className="small muted">{n}</p>)}
      </section>

      <section className="card" aria-labelledby="how-h">
        <h2 id="how-h">How this was worked out</h2>
        <ul>{v.explanation.map((e) => <li key={e}>{e}</li>)}</ul>
        {v.warnings.filter((w) => !w.startsWith("MOCK")).length > 0 && (
          <>
            <h3>Notes</h3>
            <ul>{v.warnings.filter((w) => !w.startsWith("MOCK")).map((w) => <li key={w}>{w}</li>)}</ul>
          </>
        )}
        <p className="small muted">
          {v.device.manufacturer} {v.device.name} · {v.device.storage_gb} GB · {region} · method {v.method_version} ·
          generated {day(v.generated_at)} · ID <code>{v.valuation_id}</code>
        </p>
      </section>
    </div>
  );
}
