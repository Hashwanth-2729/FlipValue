import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { EmptyState, ErrorState, Loading, Notice } from "../components/ui";
import { compareLink, ValuationResult } from "../components/ValuationResult";
import { day } from "../format";
import { findHistory, readHistory, removeHistory, type HistoryEntry } from "../history";
import { useAsync, usePageTitle } from "../hooks";

/** Confirmation dialog before a permanent delete. */
function useConfirmDelete(onDeleted: (id: string) => void) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [target, setTarget] = useState<HistoryEntry | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const ask = (entry: HistoryEntry) => {
    setTarget(entry);
    setError(null);
    dialog.current?.showModal?.();
  };
  const confirm = async () => {
    if (!target) return;
    setBusy(true);
    try {
      await api.deleteSaved(target.id, target.deleteToken);
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, "unexpected", String(e));
      if (err.status !== 404) {
        setError(err);
        setBusy(false);
        return;
      }
    }
    removeHistory(target.id);
    setBusy(false);
    dialog.current?.close?.();
    onDeleted(target.id);
  };
  const element = (
    <dialog ref={dialog} aria-labelledby="del-h">
      <h2 id="del-h">Delete this saved valuation?</h2>
      <p>{target?.label}. The link will stop working for everyone. This cannot be undone.</p>
      {error && <ErrorState error={error} what="the deletion" />}
      <div className="row">
        <button type="button" className="btn danger" onClick={confirm} disabled={busy}>
          {busy ? "Deleting…" : "Delete"}
        </button>
        <button type="button" className="btn" onClick={() => dialog.current?.close?.()}>Cancel</button>
      </div>
    </dialog>
  );
  return { ask, element };
}

export function SavedListPage() {
  const titleRef = usePageTitle("Saved valuations");
  const [entries, setEntries] = useState(readHistory);
  const { ask, element } = useConfirmDelete((id) => setEntries((e) => e.filter((x) => x.id !== id)));

  return (
    <div className="container narrow">
      <h1 ref={titleRef} tabIndex={-1}>Saved valuations</h1>
      <p className="lead">
        Valuations you saved in this browser. There are no accounts: this list and the keys to delete each link live
        only on this device.
      </p>
      {entries.length === 0 ? (
        <EmptyState title="Nothing saved yet">
          <p>After a valuation, choose “Save this valuation” to get a link you can come back to.</p>
          <Link className="btn primary" to="/value">Value my phone</Link>
        </EmptyState>
      ) : (
        <ul className="stack" style={{ listStyle: "none", padding: 0 }}>
          {entries.map((e) => (
            <li key={e.id} className="card row" style={{ justifyContent: "space-between" }}>
              <span>
                <strong>{e.label}</strong>
                <br />
                <span className="small muted">Saved {day(e.savedAt)}</span>
              </span>
              <span className="row">
                <Link className="btn" to={`/v/${e.id}`}>Open</Link>
                <Link className="btn" to={`/value?edit=${e.id}`}>Update condition</Link>
                <button type="button" className="btn danger" onClick={() => ask(e)}>Delete</button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {element}
    </div>
  );
}

export function SavedViewPage() {
  const { id = "" } = useParams();
  const titleRef = usePageTitle("Saved valuation");
  const state = useAsync(() => api.saved(id), [id]);
  const [deleted, setDeleted] = useState(false);
  const mine = findHistory(id);
  const { ask, element } = useConfirmDelete(() => setDeleted(true));

  return (
    <div className="container narrow">
      <h1 ref={titleRef} tabIndex={-1}>Saved valuation</h1>
      {deleted && <Notice title="Deleted">This saved valuation no longer exists.</Notice>}
      {!deleted && state.loading && <Loading />}
      {!deleted && state.error && (state.error.status === 404 ? (
        <EmptyState title="This link does not exist">
          <p>It may have been deleted by whoever saved it.</p>
        </EmptyState>
      ) : <ErrorState error={state.error} onRetry={state.reload} what="this valuation" />)}
      {!deleted && state.data && (
        <>
          <p className="muted">
            {state.data.result.device.manufacturer} {state.data.result.device.name} · saved {day(state.data.created_at)}.
            Values are as of that date; prices change, so recalculate for a current figure.
          </p>
          <ValuationResult v={state.data.result} />
          <div className="row no-print" style={{ marginTop: 16 }}>
            <Link className="btn primary" to={`/value?edit=${id}`}>Recalculate or update condition</Link>
            {state.data.result.as_is && <Link className="btn" to={compareLink(state.data.result)}>Compare repair or sell</Link>}
            <button type="button" className="btn" onClick={() => window.print()}>Print / save as PDF</button>
            {mine && <button type="button" className="btn danger" onClick={() => ask(mine)}>Delete</button>}
          </div>
        </>
      )}
      {element}
    </div>
  );
}
