import { money, month } from "../format";
import type { Currency, TrendPoint } from "../types";

const COLORS: Record<string, string> = {
  completed_sale: "var(--accent)",
  listing: "var(--warn)",
  trade_in: "var(--mock)",
  estimate: "var(--text)",
};
const LABELS: Record<string, string> = {
  completed_sale: "Completed sales (monthly median)",
  listing: "Asking prices (monthly median)",
  trade_in: "Trade-in offers (monthly median)",
  estimate: "FlipValue estimate (modelled, dashed)",
};
const DASHED = new Set(["estimate"]);

/** Monthly medians, one line per price basis (modelled estimates dashed), with a data table for screen readers. */
export function LineChart({ series, currency }: { series: Record<string, TrendPoint[]>; currency: Currency }) {
  const months = [...new Set(Object.values(series).flat().map((p) => p.month))].sort();
  const values = Object.values(series).flat().map((p) => p.median);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.15 || hi * 0.1 || 1;
  const [y0, y1] = [lo - pad, hi + pad];
  const W = 640, H = 260, L = 70, R = 16, T = 16, B = 34;
  const x = (m: string) => L + (months.length === 1 ? (W - L - R) / 2 : (months.indexOf(m) / (months.length - 1)) * (W - L - R));
  const y = (v: number) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  const ticks = [y0 + (y1 - y0) * 0.1, (y0 + y1) / 2, y1 - (y1 - y0) * 0.1];

  return (
    <figure className="chart" style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Monthly median prices over time; data table below">
        {ticks.map((t) => (
          <g key={t}>
            <line className="axis" x1={L} x2={W - R} y1={y(t)} y2={y(t)} />
            <text className="label" x={L - 8} y={y(t) + 4} textAnchor="end">
              {money(Math.round(t), currency)}
            </text>
          </g>
        ))}
        {months.map((m, i) =>
          // Long histories: one label per January (plus the first month); short ones: up to eight labels.
          (months.length > 24
            ? (i === 0 && Number(m.slice(5)) <= 9) || (i > 0 && m.endsWith("-01"))
            : months.length <= 8 || i % Math.ceil(months.length / 8) === 0) ? (
            <text key={m} className="label" x={x(m)} y={H - 10} textAnchor="middle">
              {months.length > 24 && i > 0 ? m.slice(0, 4) : month(m)}
            </text>
          ) : null,
        )}
        {Object.entries(series).map(([basis, points]) => (
          <g key={basis}>
            <polyline
              className="line"
              stroke={COLORS[basis] ?? "var(--text)"}
              strokeDasharray={DASHED.has(basis) ? "6 4" : undefined}
              points={points.map((p) => `${x(p.month)},${y(p.median)}`).join(" ")}
            />
            {points.map((p) => (
              <circle key={p.month} cx={x(p.month)} cy={y(p.median)} r={points.length > 24 ? 2.5 : 3.5}
                fill={COLORS[basis] ?? "var(--text)"}>
                <title>
                  {month(p.month)}: {money(p.median, currency)}
                  {DASHED.has(basis) ? " (FlipValue estimate)" : ` (${p.count} observations)`}
                </title>
              </circle>
            ))}
          </g>
        ))}
      </svg>
      <figcaption className="legend">
        {Object.keys(series).map((b) => (
          <span key={b}>
            <i style={{ background: COLORS[b] ?? "var(--text)" }} />
            {LABELS[b] ?? b}
          </span>
        ))}
      </figcaption>
      <details style={{ marginTop: 12 }}>
        <summary>Show the data</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Month</th>
                <th scope="col">Price basis</th>
                <th scope="col" className="num">Median</th>
                <th scope="col" className="num">Observations</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(series).flatMap(([basis, points]) =>
                points.map((p) => (
                  <tr key={`${basis}-${p.month}`}>
                    <td>{month(p.month)}</td>
                    <td>{LABELS[basis] ?? basis}</td>
                    <td className="num">{money(p.median, currency)}</td>
                    <td className="num">{DASHED.has(basis) ? "estimate" : p.count}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
