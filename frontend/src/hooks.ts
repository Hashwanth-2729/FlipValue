import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "./api";

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** Runs `load` when `deps` change; ignores responses that arrive after a newer request started. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean }>({
    data: null,
    error: null,
    loading: true,
  });
  const [tick, setTick] = useState(0);
  const latest = useRef(0);

  useEffect(() => {
    const run = ++latest.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    load().then(
      (data) => run === latest.current && setState({ data, error: null, loading: false }),
      (error) =>
        run === latest.current &&
        setState({
          data: null,
          error: error instanceof ApiError ? error : new ApiError(0, "unexpected", String(error)),
          loading: false,
        }),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}

let initialPageLoad = true;

/** Sets the document title and returns a ref that receives focus after in-app navigation (for screen readers).
 *  On the first page load focus is left alone, so the "Skip to content" link stays the first Tab stop. */
export function usePageTitle(title: string) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${title} · FlipValue`;
    if (initialPageLoad) {
      initialPageLoad = false;
      return;
    }
    ref.current?.focus();
  }, [title]);
  return ref;
}
