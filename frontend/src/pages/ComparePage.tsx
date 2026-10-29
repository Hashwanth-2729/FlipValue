import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { ErrorState, Notice } from "../components/ui";
import { REGIONS, REPAIR_LABEL } from "../content";
import { money } from "../format";
import { usePageTitle } from "../hooks";
import type { Currency, DecisionInput, DecisionResult, RepairType } from "../types";

type Field = "as_is" | "after_repair" | "repair_cost" | "fee" | "fixed" | "replacement";

function parse(v: string): number | undefined {
  if (v.trim() === "") return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : NaN;
}

export function ComparePage() {
  const titleRef = usePageTitle("Repair or sell");
  const [params] = useSearchParams();
  const fromValuation = params.has("as_is");
  const [currency, setCurrency] = useState<Currency>((params.get("currency") as Currency) || "INR");
  const [values, setValues] = useState<Record<Field, string>>({
    as_is: params.get("as_is") ?? "",
    after_repair: params.get("after_repair") ?? "",
    repair_cost: "",
    fee: "0",
    fixed: "0",
    replacement: "",
  });
  const [basis, setBasis] = useState<DecisionInput["repair_cost_basis"]>("user_supplied");
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const [result, setResult] = useState<DecisionResult | null>(null);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const repair = params.get("repair") as RepairType | null;

  const set = (f: Field) => (e: React.ChangeEvent<HTMLInputElement>) => setValues((v) => ({ ...v, [f]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const nums = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, parse(v)])) as Record<Field, number | undefined>;
    const errs: Partial<Record<Field, string>> = {};
    for (const [k, v] of Object.entries(nums) as [Field, number | undefined][]) {
      if (v !== undefined && (Number.isNaN(v) || v < 0)) errs[k] = "Enter a number of 0 or more.";
    }
    if (nums.fee !== undefined && nums.fee > 50) errs.fee = "Fees above 50% are not supported.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    setFailure(null);
    try {
      setResult(await api.decide({
        currency,
        as_is_value: nums.as_is,
        after_repair_value: nums.after_repair,
        repair_cost: nums.repair_cost,
        repair_cost_basis: basis,
        selling_fee_pct: nums.fee ?? 0,
        selling_fixed_cost: nums.fixed ?? 0,
        replacement_price: nums.replacement,
      }));
    } catch (err) {
      setFailure(err instanceof ApiError ? err : new ApiError(0, "unexpected", String(err)));
    } finally {
      setBusy(false);
    }
  };

  const input = (f: Field, label: string, hint?: string) => (
    <div className="field">
      <label htmlFor={f}>
        {label} {hint && <span className="hint">{hint}</span>}
      </label>
      <input id={f} type="number" inputMode="decimal" min={0} step="any" value={values[f]} onChange={set(f)}
        aria-invalid={errors[f] ? true : undefined} aria-describedby={errors[f] ? `${f}-err` : undefined} />
      {errors[f] && <span id={`${f}-err`} className="error-text">{errors[f]}</span>}
    </div>
  );

  return (
    <div className="container narrow">
      <h1 ref={titleRef} tabIndex={-1}>Repair or sell?</h1>
      <p className="lead">Compare what you would end up with under each option. Every sum and assumption is shown.</p>
      {fromValuation ? (
        <Notice title={`Values from your FlipValue estimate${params.get("label") ? ` for ${params.get("label")}` : ""}`}>
          <p>
            Pre-filled with the median estimates{repair ? ` (after ${REPAIR_LABEL[repair]?.toLowerCase()})` : ""}. You can change them.
            {!params.has("after_repair") && " No after-repair estimate was available or requested."}
          </p>
        </Notice>
      ) : (
        <Notice title="Enter your own numbers, or start from a valuation">
          <p><Link to="/value">Value your phone</Link> first to fill in the resale values from evidence.</p>
        </Notice>
      )}

      <form className="card" onSubmit={submit} noValidate style={{ marginTop: 16 }}>
        <div className="field">
          <label htmlFor="currency">Currency</label>
          <select id="currency" value={currency} onChange={(e) => setCurrency(e.target.value as Currency)}>
            {REGIONS.map((r) => <option key={r.currency} value={r.currency}>{r.currency} — {r.label}</option>)}
          </select>
        </div>
        {input("as_is", "Resale value as it is", "(gross)")}
        {input("after_repair", "Resale value after repair", "(gross)")}
        {input("repair_cost", "Repair cost")}
        <div className="field">
          <label htmlFor="basis">Where does the repair cost come from?</label>
          <select id="basis" value={basis} onChange={(e) => setBasis(e.target.value as DecisionInput["repair_cost_basis"])}>
            <option value="user_supplied">My own figure</option>
            <option value="estimated">An estimate (e.g. from FixMyTech or a price list)</option>
            <option value="verified_quote">A written quote from a repair shop</option>
          </select>
        </div>
        {input("fee", "Selling fees", "(% of the sale price, e.g. marketplace commission)")}
        {input("fixed", "Other selling costs", "(shipping, travel…)")}
        {input("replacement", "Price of a replacement phone", "(optional)")}
        <button type="submit" className="btn primary" disabled={busy}>{busy ? "Calculating…" : "Compare options"}</button>
      </form>

      {failure && <ErrorState error={failure} what="the comparison" />}

      {result && (
        <section className="card" aria-labelledby="res-h" aria-live="polite" style={{ marginTop: 16 }}>
          <h2 id="res-h">Results</h2>
          <div className="table-wrap">
            <table>
              <caption className="visually-hidden">Net result of each option</caption>
              <thead>
                <tr>
                  <th scope="col">Option</th>
                  <th scope="col" className="num">Sale price</th>
                  <th scope="col" className="num">Fees</th>
                  <th scope="col" className="num">Other costs</th>
                  <th scope="col" className="num">You end up with</th>
                </tr>
              </thead>
              <tbody>
                {result.scenarios.map((s) => (
                  <tr key={s.key}>
                    <th scope="row">
                      {s.title}
                      <div className="small muted" style={{ fontWeight: 400 }}>
                        {s.available ? s.explanation : `Needs ${s.missing.join(" and ")}`}
                      </div>
                    </th>
                    <td className="num">{money(s.gross, result.currency)}</td>
                    <td className="num">{money(s.selling_fees, result.currency)}</td>
                    <td className="num">{money(s.other_costs, result.currency)}</td>
                    <td className="num"><strong>{money(s.net, result.currency)}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.repair_first_advantage !== null && (
            <p style={{ marginTop: 16 }}>
              Repairing before selling leaves you{" "}
              <strong>{money(Math.abs(result.repair_first_advantage), result.currency)}</strong>{" "}
              {result.repair_first_advantage >= 0 ? "better off" : "worse off"} than selling as it is — if the estimates hold.
            </p>
          )}
          <h3>Assumptions</h3>
          <ul>{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
          <p className="small muted">This is arithmetic on the numbers above, not a guarantee or financial advice.</p>
        </section>
      )}
    </div>
  );
}
