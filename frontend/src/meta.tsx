import { createContext, useContext, type ReactNode } from "react";

import { api } from "./api";
import { useAsync, type AsyncState } from "./hooks";
import type { Meta } from "./types";

const MetaContext = createContext<AsyncState<Meta> | null>(null);

export function MetaProvider({ children }: { children: ReactNode }) {
  const state = useAsync(() => api.meta(), []);
  return <MetaContext.Provider value={state}>{children}</MetaContext.Provider>;
}

export function useMeta(): AsyncState<Meta> {
  const value = useContext(MetaContext);
  if (!value) throw new Error("useMeta outside MetaProvider");
  return value;
}
