import type { ReactNode } from "react";

import { ApiError } from "../api";
import { EVIDENCE } from "../content";
import type { EvidenceStatus } from "../types";

export function Notice({ tone = "info", title, children }: {
  tone?: "info" | "warn" | "danger" | "mock";
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className={`notice ${tone}`} role={tone === "danger" ? "alert" : undefined}>
      {title && <strong>{title}</strong>}
      {children}
    </div>
  );
}

export function EvidenceBadge({ status, region }: { status: EvidenceStatus; region?: string }) {
  const e = EVIDENCE[status];
  return (
    <span className={`badge ${e.tone}`} title={e.help}>
      {region && <span>{region}:</span>}
      {e.label}
    </span>
  );
}

export function Loading({ label = "Loading", lines = 3 }: { label?: string; lines?: number }) {
  return (
    <div role="status" aria-live="polite" className="stack">
      <span className="visually-hidden">{label}…</span>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 15}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry, what = "this" }: {
  error: ApiError;
  onRetry?: () => void;
  what?: string;
}) {
  const wait = error.retryAfter ? ` Please wait about ${error.retryAfter} seconds.` : "";
  return (
    <Notice tone="danger" title={`We could not load ${what}.`}>
      <p>
        {error.message}
        {wait}
      </p>
      {error.requestId && <p className="small muted">Reference: {error.requestId}</p>}
      {onRetry && error.transient && (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </Notice>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="card" role="status">
      <h3>{title}</h3>
      <div className="muted">{children}</div>
    </div>
  );
}

export interface Choice<T extends string> {
  value: T;
  label: string;
  help?: string;
}

/** Radio-card group with a proper fieldset/legend; required groups show an error after a failed submit. */
export function ChoiceGroup<T extends string>({ name, legend, hint, choices, value, onChange, error }: {
  name: string;
  legend: string;
  hint?: string;
  choices: Choice<T>[];
  value: T | undefined;
  onChange: (value: T) => void;
  error?: string;
}) {
  const hintId = hint ? `${name}-hint` : undefined;
  const errorId = error ? `${name}-error` : undefined;
  return (
    <fieldset aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}>
      <legend>{legend}</legend>
      {hint && (
        <p id={hintId} className="hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="error-text">
          {error}
        </p>
      )}
      <div className="choices">
        {choices.map((c) => (
          <label key={c.value} className="choice">
            <input
              type="radio"
              name={name}
              value={c.value}
              checked={value === c.value}
              onChange={() => onChange(c.value)}
            />
            <span>
              {c.label}
              {c.help && <small>{c.help}</small>}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
