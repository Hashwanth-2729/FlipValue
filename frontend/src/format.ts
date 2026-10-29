import type { Currency } from "./types";

const LOCALE: Record<Currency, string> = { INR: "en-IN", USD: "en-US" };

/** Whole units for large values (₹22,000), cents only when present ($180.50). Null shows as an em dash. */
export function money(value: number | null | undefined, currency: Currency): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const whole = Number.isInteger(value);
  return new Intl.NumberFormat(LOCALE[currency], {
    style: "currency",
    currency,
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 2,
  }).format(value);
}

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const MONTH = new Intl.DateTimeFormat("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });

/** "2026-10-01" or an ISO datetime -> "1 Oct 2026" (dates are shown in UTC so they never shift by a day). */
export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(date.getTime()) ? "—" : DATE.format(date);
}

/** "2026-10" -> "Oct 2026" */
export function month(ym: string): string {
  return MONTH.format(new Date(`${ym}-01T00:00:00Z`));
}

export function daysSince(iso: string, today = new Date()): number {
  const then = Date.parse(`${iso}T00:00:00Z`);
  const now = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return Math.round((now - then) / 86_400_000);
}

/** "3 h ago", "2 days ago" for an ISO datetime; falls back to the date for anything older than a month. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const ms = now - Date.parse(iso);
  if (Number.isNaN(ms)) return "—";
  const minutes = Math.max(0, Math.round(ms / 60_000));
  if (minutes < 60) return minutes <= 1 ? "just now" : `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days <= 31 ? `${days} days ago` : day(iso);
}

export function count(n: number, singular: string, plural = `${singular}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? singular : plural}`;
}
