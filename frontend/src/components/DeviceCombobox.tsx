import { useEffect, useId, useState } from "react";

import { api } from "../api";
import type { CatalogueModel } from "../types";

/** Accessible autocomplete over the real catalogue (ARIA combobox pattern). Only catalogue models can be chosen. */
export function DeviceCombobox({ value, onChange, error }: {
  value: CatalogueModel | null;
  onChange: (model: CatalogueModel | null) => void;
  error?: string;
}) {
  const id = useId();
  const [query, setQuery] = useState(value ? `${value.manufacturer} ${value.name}` : "");
  const [options, setOptions] = useState<CatalogueModel[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");

  // A model chosen elsewhere (prefill from a link or saved answers) shows up in the box.
  useEffect(() => {
    if (value) setQuery(`${value.manufacturer} ${value.name}`);
  }, [value?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return;
    setStatus("loading");
    const timer = setTimeout(() => {
      api.catalogue(query).then(
        (models) => {
          setOptions(models);
          setActive(0);
          setStatus("idle");
        },
        () => setStatus("error"),
      );
    }, 150);
    return () => clearTimeout(timer);
  }, [query, open]);

  const choose = (model: CatalogueModel) => {
    onChange(model);
    setQuery(`${model.manufacturer} ${model.name}`);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.min(a + 1, options.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && open && options[active]) {
      e.preventDefault();
      choose(options[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const listId = `${id}-list`;
  const showList = open && status !== "error";
  return (
    <div className="field combobox">
      <label htmlFor={`${id}-input`}>
        Phone model
        <span className="hint"> — search by name or model code (e.g. SM-G991B)</span>
      </label>
      <input
        id={`${id}-input`}
        type="text"
        role="combobox"
        autoComplete="off"
        aria-autocomplete="list"
        aria-expanded={showList}
        aria-controls={listId}
        aria-activedescendant={showList && options[active] ? `${id}-opt-${active}` : undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          if (value) onChange(null);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
      />
      {error && (
        <span id={`${id}-error`} className="error-text">
          {error}
        </span>
      )}
      {status === "error" && <span className="error-text">Could not load the device list. Try again.</span>}
      {showList && (
        <ul id={listId} role="listbox" className="listbox" aria-label="Matching phones">
          {status === "loading" && options.length === 0 && <li className="option muted">Searching…</li>}
          {status === "idle" && options.length === 0 && (
            <li className="option muted" role="option" aria-selected={false} aria-disabled>
              No catalogued phone matches “{query}”. FlipValue only values models in its catalogue.
            </li>
          )}
          {options.map((m, i) => (
            <li
              key={m.id}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className="option"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(m)}
            >
              <span>
                {m.manufacturer} {m.name}
              </span>
              {m.oem_codes.length > 0 && <span className="muted small">{m.oem_codes.join(", ")}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
