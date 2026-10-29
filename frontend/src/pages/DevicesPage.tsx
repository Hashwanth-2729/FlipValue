import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { EmptyState, ErrorState, EvidenceBadge, Loading } from "../components/ui";
import { EVIDENCE } from "../content";
import { day } from "../format";
import { useAsync, usePageTitle } from "../hooks";
import type { EvidenceStatus } from "../types";

export function DevicesPage() {
  const titleRef = usePageTitle("Devices");
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [debounced, setDebounced] = useState(query);
  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced(query);
      setParams(query ? { q: query } : {}, { replace: true });
    }, 200);
    return () => clearTimeout(t);
  }, [query, setParams]);
  const results = useAsync(() => api.catalogue(debounced), [debounced]);

  return (
    <div className="container">
      <h1 ref={titleRef} tabIndex={-1}>Devices</h1>
      <p className="lead">Every phone FlipValue knows, and how much price evidence it has in each market.</p>
      <div className="field" style={{ maxWidth: 520 }}>
        <label htmlFor="q">Search by brand, name or model code</label>
        <input id="q" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. Pixel 7 or SM-G991B" />
      </div>
      <details className="small" style={{ marginBottom: 16 }}>
        <summary>What the evidence labels mean</summary>
        <ul>
          {(Object.keys(EVIDENCE) as EvidenceStatus[]).map((k) => (
            <li key={k}><EvidenceBadge status={k} /> {EVIDENCE[k].help}</li>
          ))}
          <li>Phones that are not listed at all are not supported.</li>
        </ul>
      </details>
      <div aria-live="polite">
        {results.loading && <Loading label="Searching" />}
        {results.error && <ErrorState error={results.error} onRetry={results.reload} what="the device list" />}
        {results.data && results.data.length === 0 && (
          <EmptyState title={`No catalogued phone matches “${debounced}”`}>
            <p>FlipValue only values phones in its catalogue and never substitutes a similar model. Check the spelling or try the model code from Settings → About phone.</p>
          </EmptyState>
        )}
        {results.data && results.data.length > 0 && (
          <div className="grid">
            {results.data.map((m) => (
              <article key={m.id} className="card">
                <h2 style={{ fontSize: "1.15rem" }}>{m.manufacturer} {m.name}</h2>
                <p className="small muted">
                  {m.storage_gb.map((s) => `${s} GB`).join(" · ")}
                  {m.release_date && <> · released {day(m.release_date)}</>}
                </p>
                {m.oem_codes.length > 0 && <p className="small">Model codes: {m.oem_codes.join(", ")}</p>}
                <p className="row small" style={{ gap: 6 }}>
                  <EvidenceBadge status={m.evidence.IN} region="India" />
                  <EvidenceBadge status={m.evidence.US} region="US" />
                </p>
                <div className="row">
                  <Link className="btn primary" to={`/value?model=${m.id}`}>Value this phone</Link>
                  <Link className="btn" to={`/trends?model=${m.id}`}>Trends</Link>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
