import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { DeviceCombobox } from "../components/DeviceCombobox";
import { ChoiceGroup, ErrorState, EvidenceBadge, Loading, Notice } from "../components/ui";
import { compareLink, ValuationResult } from "../components/ValuationResult";
import { REGIONS, REPAIR_FOR_FAULT, REPAIR_LABEL } from "../content";
import { addHistory } from "../history";
import { usePageTitle } from "../hooks";
import type { Assessment, CatalogueModel, Region, RepairType, Valuation, ValuationRequest } from "../types";

const STEPS = ["Phone", "Basics", "Condition", "Review", "Result"];
type A = Partial<Assessment>;

interface Draft {
  model: CatalogueModel | null;
  storage?: number;
  region?: Region;
  a: A;
  repair: RepairType | "";
}

const CHECK = [
  { value: "working", label: "Works" },
  { value: "issue", label: "Has a problem" },
  { value: "not_tested", label: "Not tested" },
] as const;

const REPAIRS = [
  { value: "previous_screen", key: "screen", label: "Screen" },
  { value: "previous_battery", key: "battery", label: "Battery" },
  { value: "previous_back", key: "back_glass", label: "Back glass" },
  { value: "previous_port", key: "charging_port", label: "Charging port" },
  { value: "previous_camera", key: "camera", label: "Camera" },
  { value: "previous_other", key: "other", label: "Other" },
];

function powered(a: A) {
  return a.powers_on !== "no";
}

/** Fills in answers that are not asked for a phone that does not power on. */
export function buildRequest(d: Draft): ValuationRequest {
  const a = d.a;
  const on = powered(a);
  const assessment: Assessment = {
    powers_on: a.powers_on!,
    usable_normally: on ? a.usable_normally! : "no",
    screen: a.screen!,
    ...(a.screen === "cracked" ? { screen_touch_works: a.screen_touch_works } : {}),
    body: a.body!,
    battery: a.battery!,
    charging: a.charging!,
    cameras: on ? a.cameras! : "not_tested",
    audio: on ? a.audio! : "not_tested",
    buttons: on ? a.buttons! : "not_tested",
    connectivity: on ? a.connectivity! : "not_tested",
    liquid_damage: a.liquid_damage!,
    previous_repairs: a.previous_repairs ?? [],
  };
  const region = d.region!;
  return {
    device: { model_id: d.model!.id, ...(d.storage ? { storage_gb: d.storage } : {}) },
    region,
    currency: REGIONS.find((r) => r.value === region)!.currency,
    assessment,
    ...(d.repair ? { repair_type: d.repair } : {}),
  };
}

export function missingFor(step: number, d: Draft): Record<string, string> {
  const e: Record<string, string> = {};
  const a = d.a;
  if (step === 0) {
    if (!d.model) e.model = "Choose a phone from the list.";
    if (d.model && d.model.storage_gb.length > 1 && !d.storage) e.storage = "Choose the storage size.";
    if (!d.region) e.region = "Choose where you are selling.";
  }
  if (step === 1) {
    if (!a.powers_on) e.powers_on = "Choose an answer.";
    if (powered(a) && !a.usable_normally) e.usable_normally = "Choose an answer.";
  }
  if (step === 2) {
    const required: (keyof Assessment)[] = ["screen", "body", "battery", "charging", "liquid_damage"];
    if (powered(a)) required.push("cameras", "audio", "buttons", "connectivity");
    if (a.screen === "cracked") required.push("screen_touch_works");
    for (const k of required) if (!a[k]) e[k] = "Choose an answer.";
  }
  return e;
}

export function ValuePage() {
  const titleRef = usePageTitle("Value my phone");
  const [params] = useSearchParams();
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Draft>({ model: null, a: {}, repair: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Valuation | null>(null);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [prefill, setPrefill] = useState<"idle" | "loading" | "error">("idle");
  const [saved, setSaved] = useState<{ id: string; stored: boolean } | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Prefill: ?model=<id> from the devices page, or ?edit=<saved id> to change answers and recalculate.
  useEffect(() => {
    const modelId = params.get("model");
    const editId = params.get("edit");
    if (!modelId && !editId) return;
    setPrefill("loading");
    (async () => {
      if (editId) {
        const req = await api.savedRequest(editId);
        const model = await api.model(req.device.model_id);
        setDraft({ model, storage: req.device.storage_gb, region: req.region, a: req.assessment,
                   repair: req.repair_type ?? "" });
      } else if (modelId) {
        const model = await api.model(modelId);
        setDraft((d) => ({ ...d, model, storage: model.storage_gb.length === 1 ? model.storage_gb[0] : undefined }));
      }
      setPrefill("idle");
    })().catch(() => setPrefill("error"));
  }, [params]);

  useEffect(() => {
    if (step > 0) headingRef.current?.focus();
  }, [step]);

  const setA = (patch: A) => setDraft((d) => ({ ...d, a: { ...d.a, ...patch } }));

  const next = () => {
    const missing = missingFor(step, draft);
    setErrors(missing);
    if (Object.keys(missing).length) {
      requestAnimationFrame(() => document.querySelector<HTMLElement>("[aria-invalid='true'], .error-text")
        ?.closest("fieldset, .field")?.querySelector<HTMLElement>("input")?.focus());
      return;
    }
    setStep((s) => s + 1);
  };

  const submit = async () => {
    setBusy(true);
    setFailure(null);
    setSaved(null);
    try {
      setResult(await api.valuate(buildRequest(draft)));
      setStep(4);
    } catch (e) {
      setFailure(e instanceof ApiError ? e : new ApiError(0, "unexpected", String(e)));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setFailure(null);
    try {
      const r = await api.save(buildRequest(draft));
      const stored = addHistory({
        id: r.id,
        deleteToken: r.delete_token,
        label: `${r.result.device.manufacturer} ${r.result.device.name} ${r.result.device.storage_gb} GB`,
        savedAt: new Date().toISOString(),
      });
      setResult(r.result);
      setSaved({ id: r.id, stored });
    } catch (e) {
      setFailure(e instanceof ApiError ? e : new ApiError(0, "unexpected", String(e)));
    } finally {
      setBusy(false);
    }
  };

  const d = draft;
  const a = d.a;
  const suggested = [...new Set((result?.condition.faults ?? []).map((f) => REPAIR_FOR_FAULT[f]).filter(Boolean))];

  return (
    <div className="container narrow">
      <h1 ref={titleRef} tabIndex={-1}>Value my phone</h1>
      <ol className="stepper" aria-label="Progress">
        {STEPS.map((s, i) => (
          <li key={s} className={i < step ? "done" : undefined} aria-current={i === step ? "step" : undefined}>
            <span>
              {i + 1}. {s}
            </span>
          </li>
        ))}
      </ol>
      <p className="visually-hidden" aria-live="polite">
        Step {step + 1} of {STEPS.length}: {STEPS[step]}
      </p>

      {prefill === "loading" && <Loading label="Loading your phone" />}
      {prefill === "error" && <Notice tone="warn" title="Could not load the saved answers.">Start below instead.</Notice>}

      {step === 0 && (
        <section className="card" aria-labelledby="s0">
          <h2 id="s0" ref={headingRef} tabIndex={-1}>Which phone?</h2>
          <DeviceCombobox
            value={d.model}
            error={errors.model}
            onChange={(model) =>
              setDraft((x) => ({ ...x, model, storage: model?.storage_gb.length === 1 ? model.storage_gb[0] : undefined }))
            }
          />
          {d.model && (
            <>
              <p className="row small">
                Evidence: <EvidenceBadge status={d.model.evidence.IN} region="India" />
                <EvidenceBadge status={d.model.evidence.US} region="US" />
              </p>
              {d.model.storage_gb.length > 1 ? (
                <ChoiceGroup
                  name="storage"
                  legend="Storage"
                  hint="Prices differ by storage, so we never mix sizes."
                  choices={d.model.storage_gb.map((s) => ({ value: String(s), label: `${s} GB` }))}
                  value={d.storage ? String(d.storage) : undefined}
                  onChange={(v) => setDraft((x) => ({ ...x, storage: Number(v) }))}
                  error={errors.storage}
                />
              ) : (
                <p className="muted">Catalogued with {d.model.storage_gb[0]} GB only.</p>
              )}
            </>
          )}
          <ChoiceGroup
            name="region"
            legend="Where will you sell it?"
            hint="Values are given in that market's currency. We never convert currencies."
            choices={REGIONS.map((r) => ({ value: r.value, label: r.label }))}
            value={d.region}
            onChange={(region) => setDraft((x) => ({ ...x, region }))}
            error={errors.region}
          />
          <p className="small muted">
            Phone not listed? FlipValue only values phones in its <Link to="/devices">catalogue</Link> and never
            substitutes a similar model.
          </p>
        </section>
      )}

      {step === 1 && (
        <section className="card" aria-labelledby="s1">
          <h2 id="s1" ref={headingRef} tabIndex={-1}>The basics</h2>
          <ChoiceGroup name="powers_on" legend="Does the phone turn on?" value={a.powers_on} error={errors.powers_on}
            choices={[{ value: "yes", label: "Yes" }, { value: "no", label: "No" }]} onChange={(v) => setA({ powers_on: v })} />
          {powered(a) && (
            <ChoiceGroup name="usable_normally" legend="Can it be unlocked and used normally?"
              hint="For example: no forgotten passcode, account lock or boot loop." value={a.usable_normally}
              error={errors.usable_normally}
              choices={[{ value: "yes", label: "Yes" }, { value: "no", label: "No" }, { value: "unsure", label: "Not sure" }]}
              onChange={(v) => setA({ usable_normally: v })} />
          )}
          <fieldset>
            <legend>Any parts replaced before? <span className="hint">(optional)</span></legend>
            <p className="hint">Recorded in your summary. It does not change the estimate yet.</p>
            <div className="choices">
              {REPAIRS.map((r) => (
                <label key={r.value} className="choice">
                  <input
                    type="checkbox"
                    checked={(a.previous_repairs ?? []).includes(r.key)}
                    onChange={(e) =>
                      setA({
                        previous_repairs: e.target.checked
                          ? [...(a.previous_repairs ?? []), r.key]
                          : (a.previous_repairs ?? []).filter((x) => x !== r.key),
                      })
                    }
                  />
                  <span>{r.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <Notice title="Why we don't ask the phone's age or what you paid">
            <p>
              Estimates come from recent prices of this exact model and storage, which already reflect how old that
              model is. Your purchase date and price would not change the number, so we don't collect them.
            </p>
          </Notice>
        </section>
      )}

      {step === 2 && (
        <section className="card" aria-labelledby="s2">
          <h2 id="s2" ref={headingRef} tabIndex={-1}>Condition</h2>
          <p className="muted">Answer as honestly as you can — a buyer will check. Nothing here tests the phone.</p>
          <ChoiceGroup name="screen" legend="Screen" value={a.screen} error={errors.screen}
            choices={[
              { value: "perfect", label: "No marks" },
              { value: "light_scratches", label: "Light scratches", help: "Hard to see when on" },
              { value: "heavy_scratches", label: "Deep or many scratches" },
              { value: "cracked", label: "Cracked glass" },
              { value: "display_fault", label: "Display fault", help: "Lines, dead areas, touch issues" },
            ]}
            onChange={(v) => setA({ screen: v, ...(v !== "cracked" ? { screen_touch_works: undefined } : {}) })} />
          {a.screen === "cracked" && (
            <ChoiceGroup name="screen_touch_works" legend="With the crack, do the display and touch still work everywhere?"
              value={a.screen_touch_works} error={errors.screen_touch_works}
              choices={[{ value: "yes", label: "Yes, fully" }, { value: "no", label: "No" }]}
              onChange={(v) => setA({ screen_touch_works: v })} />
          )}
          <ChoiceGroup name="body" legend="Back and frame" value={a.body} error={errors.body}
            choices={[
              { value: "like_new", label: "Like new" },
              { value: "light_wear", label: "Light wear" },
              { value: "visible_wear", label: "Visible scratches or dents" },
              { value: "heavy_wear", label: "Heavy wear" },
              { value: "cracked_back", label: "Cracked back" },
            ]}
            onChange={(v) => setA({ body: v })} />
          <ChoiceGroup name="battery" legend="Battery" value={a.battery} error={errors.battery}
            choices={[
              { value: "normal", label: "Lasts as expected" },
              { value: "drains_fast", label: "Drains fast" },
              { value: "swollen", label: "Swollen / bulging" },
              { value: "unknown", label: "Don't know" },
            ]}
            onChange={(v) => setA({ battery: v })} />
          <ChoiceGroup name="charging" legend="Charging" value={a.charging} error={errors.charging}
            choices={[
              { value: "normal", label: "Charges normally" },
              { value: "unreliable", label: "Unreliable", help: "Loose cable, stops charging" },
              { value: "not_charging", label: "Does not charge" },
            ]}
            onChange={(v) => setA({ charging: v })} />
          {powered(a) ? (
            <>
              <ChoiceGroup name="cameras" legend="Cameras" value={a.cameras} error={errors.cameras}
                choices={[...CHECK]} onChange={(v) => setA({ cameras: v })} />
              <ChoiceGroup name="audio" legend="Speakers and microphones" value={a.audio} error={errors.audio}
                choices={[...CHECK]} onChange={(v) => setA({ audio: v })} />
              <ChoiceGroup name="buttons" legend="Buttons" value={a.buttons} error={errors.buttons}
                choices={[...CHECK]} onChange={(v) => setA({ buttons: v })} />
              <ChoiceGroup name="connectivity" legend="Wi-Fi, mobile data and Bluetooth" value={a.connectivity}
                error={errors.connectivity} choices={[...CHECK]} onChange={(v) => setA({ connectivity: v })} />
            </>
          ) : (
            <Notice title="Skipping feature checks">
              <p>The phone doesn't turn on, so cameras, audio, buttons and connectivity can't be checked. It will be valued as faulty.</p>
            </Notice>
          )}
          <ChoiceGroup name="liquid_damage" legend="Has it been in water or other liquid?" value={a.liquid_damage}
            error={errors.liquid_damage}
            choices={[{ value: "no", label: "No" }, { value: "yes", label: "Yes" }, { value: "unsure", label: "Not sure" }]}
            onChange={(v) => setA({ liquid_damage: v })} />
          <div className="field">
            <label htmlFor="repair">
              Also estimate the value after a repair? <span className="hint">(optional)</span>
            </label>
            <select id="repair" value={d.repair} onChange={(e) => setDraft((x) => ({ ...x, repair: e.target.value as RepairType | "" }))}>
              <option value="">No, just the current value</option>
              {(Object.keys(REPAIR_LABEL) as RepairType[]).map((r) => (
                <option key={r} value={r}>{REPAIR_LABEL[r]}</option>
              ))}
            </select>
            <span className="hint">FlipValue does not estimate repair costs. You can add a quote on the Repair or sell page.</span>
          </div>
        </section>
      )}

      {step === 3 && d.model && (
        <section className="card" aria-labelledby="s3">
          <h2 id="s3" ref={headingRef} tabIndex={-1}>Check your answers</h2>
          <Review d={d} goTo={setStep} />
          {failure && <ErrorState error={failure} onRetry={submit} what="your valuation" />}
        </section>
      )}

      {step === 4 && result && (
        <section aria-labelledby="s4">
          <h2 id="s4" ref={headingRef} tabIndex={-1}>
            {result.device.manufacturer} {result.device.name} · {result.device.storage_gb} GB
          </h2>
          <ValuationResult v={result} />
          {suggested.length > 0 && !result.repair_type && (
            <p className="small muted" style={{ marginTop: 16 }}>
              Want an after-repair estimate? Edit your answers and choose {suggested.map((r) => REPAIR_LABEL[r]).join(" or ")}.
            </p>
          )}
          {failure && <ErrorState error={failure} onRetry={save} what="the saved link" />}
          {saved && (
            <Notice title="Saved">
              <p>
                Link: <Link to={`/v/${saved.id}`}>{`${window.location.origin}/v/${saved.id}`}</Link>
              </p>
              <p className="small">
                Anyone with the link can view this valuation (it holds no personal details).{" "}
                {saved.stored
                  ? "This browser keeps the private key to delete it — see Saved."
                  : "Your browser blocked storage, so this browser cannot delete it later. Keep the link private."}
              </p>
            </Notice>
          )}
          <div className="row no-print" style={{ marginTop: 16 }}>
            {!saved && (
              <button type="button" className="btn primary" onClick={save} disabled={busy}>
                {busy ? "Saving…" : "Save this valuation"}
              </button>
            )}
            {result.as_is && <Link className="btn" to={compareLink(result)}>Compare repair or sell</Link>}
            <button type="button" className="btn" onClick={() => setStep(2)}>Change answers</button>
            <button type="button" className="btn" onClick={() => window.print()}>Print / save as PDF</button>
            <button type="button" className="btn link" onClick={() => {
              setDraft({ model: null, a: {}, repair: "" });
              setResult(null);
              setSaved(null);
              setStep(0);
            }}>Value another phone</button>
          </div>
        </section>
      )}

      {step < 4 && (
        <div className="wizard-actions no-print">
          {step > 0 ? (
            <button type="button" className="btn" onClick={() => setStep((s) => s - 1)}>Back</button>
          ) : <span />}
          {step < 3 && <button type="button" className="btn primary" onClick={next}>Continue</button>}
          {step === 3 && (
            <button type="button" className="btn primary" onClick={submit} disabled={busy}>
              {busy ? "Working it out…" : "Get my valuation"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const LABELS: Record<string, string> = {
  yes: "Yes", no: "No", unsure: "Not sure", perfect: "No marks", light_scratches: "Light scratches",
  heavy_scratches: "Deep or many scratches", cracked: "Cracked glass", display_fault: "Display fault",
  like_new: "Like new", light_wear: "Light wear", visible_wear: "Visible scratches or dents", heavy_wear: "Heavy wear",
  cracked_back: "Cracked back", normal: "Normal", drains_fast: "Drains fast", swollen: "Swollen", unknown: "Don't know",
  unreliable: "Unreliable", not_charging: "Does not charge", working: "Works", issue: "Has a problem",
  not_tested: "Not tested",
};

function Review({ d, goTo }: { d: Draft; goTo: (step: number) => void }) {
  const a = d.a;
  const rows: [string, string, number][] = [
    ["Phone", `${d.model!.manufacturer} ${d.model!.name}`, 0],
    ["Storage", `${d.storage ?? d.model!.storage_gb[0]} GB`, 0],
    ["Market", REGIONS.find((r) => r.value === d.region)!.label, 0],
    ["Turns on", LABELS[a.powers_on!], 1],
    ...(powered(a) ? [["Usable normally", LABELS[a.usable_normally!], 1] as [string, string, number]] : []),
    ["Previous repairs", (a.previous_repairs ?? []).join(", ") || "None", 1],
    ["Screen", LABELS[a.screen!] + (a.screen === "cracked" ? ` (display/touch work: ${LABELS[a.screen_touch_works!]})` : ""), 2],
    ["Back and frame", LABELS[a.body!], 2],
    ["Battery", LABELS[a.battery!], 2],
    ["Charging", LABELS[a.charging!], 2],
    ...(powered(a)
      ? ([["Cameras", LABELS[a.cameras!], 2], ["Speakers / mics", LABELS[a.audio!], 2], ["Buttons", LABELS[a.buttons!], 2],
          ["Connectivity", LABELS[a.connectivity!], 2]] as [string, string, number][])
      : []),
    ["Liquid", LABELS[a.liquid_damage!], 2],
    ["After-repair estimate", d.repair ? REPAIR_LABEL[d.repair] : "Not requested", 2],
  ];
  return (
    <dl className="summary">
      {rows.map(([k, v, step]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>
            {v}{" "}
            <button type="button" className="btn link small" onClick={() => goTo(step)} aria-label={`Change ${k}`}>
              Change
            </button>
          </dd>
        </div>
      ))}
    </dl>
  );
}
