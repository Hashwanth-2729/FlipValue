// Saved valuations kept in this browser only: the link id, its private delete token and a label.
// Storage can be unavailable (private mode, blocked site data), so every access is guarded.

export interface HistoryEntry {
  id: string;
  deleteToken: string;
  label: string;
  savedAt: string;
}

const KEY = "flipvalue.saved.v1";

export function readHistory(): HistoryEntry[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((e) => e && typeof e.id === "string") : [];
  } catch {
    return [];
  }
}

function write(entries: HistoryEntry[]): boolean {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(entries));
    return true;
  } catch {
    return false;
  }
}

export function addHistory(entry: HistoryEntry): boolean {
  return write([entry, ...readHistory().filter((e) => e.id !== entry.id)].slice(0, 50));
}

export function removeHistory(id: string): void {
  write(readHistory().filter((e) => e.id !== id));
}

export function findHistory(id: string): HistoryEntry | undefined {
  return readHistory().find((e) => e.id === id);
}
