import { day, money } from "../format";
import type { Currency } from "../types";

const PALETTE = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

/** Daily lowest observed price per source. Points are only days on which a price was actually retrieved; lines
 *  never bridge a gap longer than one day, so missing days stay visibly missing. */
export function PriceHistoryChart({ series, currency }: {
  series: Record<string, { date: string; lowest: number }[]>;
  currency: Currency;
}) {
  const names = Object.keys(series);
  const dates = [...new Set(Object.values(series).flat().map((p) => p.date))].sort();
  const values = Object.values(series).flat().map((p) => p.lowest);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.2 || hi * 0.05 || 1;
  const [y0, y1] = [lo - pad, hi + pad];
  const W = 640, H = 220, L = 74, R = 16, T = 14, B = 30;
  const t0 = Date.parse(dates[0]);
  const span = Math.max(1, Date.parse(dates[dates.length - 1]) - t0);
  const x = (d: string) => (dates.length === 1 ? (L + W - R) / 2 : L + ((Date.parse(d) - t0) / span) * (W - L - R));
  const y = (v: number) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  const ONE_DAY = 86_400_000;

  const segments = (points: { date: string; lowest: number }[]) => {
    const out: { date: string; lowest: number }[][] = [];
    for (const p of points) {
      const last = out[out.length - 1];
      if (last && Date.parse(p.date) - Date.parse(last[last.length - 1].date) <= ONE_DAY) last.push(p);
      else out.push([p]);
    }
    return out;
  };

  return (
    <figure className="chart" style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Lowest observed price per day by source; data table below">
        {[y0 + (y1 - y0) * 0.15, (y0 + y1) / 2, y1 - (y1 - y0) * 0.15].map((t) => (
          <g key={t}>
            <line className="axis" x1={L} x2={W - R} y1={y(t)} y2={y(t)} />
            <text className="label" x={L - 8} y={y(t) + 4} textAnchor="end">{money(Math.round(t), currency)}</text>
          </g>
        ))}
        {[dates[0], dates[dates.length - 1]].filter((d, i, a) => a.indexOf(d) === i).map((d) => (
          <text key={d} className="label" x={x(d)} y={H - 8} textAnchor="middle">{day(d)}</text>
        ))}
        {names.map((name, i) => (
          <g key={name}>
            {segments(series[name]).map((seg) => (
              <polyline key={seg[0].date} className="line" stroke={PALETTE[i % PALETTE.length]}
                points={seg.map((p) => `${x(p.date)},${y(p.lowest)}`).join(" ")} />
            ))}
            {series[name].map((p) => (
              <circle key={p.date} cx={x(p.date)} cy={y(p.lowest)} r={4} fill={PALETTE[i % PALETTE.length]}>
                <title>{name}, {day(p.date)}: {money(p.lowest, currency)}</title>
              </circle>
            ))}
          </g>
        ))}
      </svg>
      <figcaption className="legend">
        {names.map((n, i) => <span key={n}><i style={{ background: PALETTE[i % PALETTE.length] }} />{n}</span>)}
      </figcaption>
      <details style={{ marginTop: 10 }}>
        <summary>Show the data</summary>
        <div className="table-wrap">
          <table>
            <thead><tr><th scope="col">Date</th><th scope="col">Source</th><th scope="col" className="num">Lowest price</th></tr></thead>
            <tbody>
              {names.flatMap((n) => series[n].map((p) => (
                <tr key={`${n}-${p.date}`}><td>{day(p.date)}</td><td>{n}</td><td className="num">{money(p.lowest, currency)}</td></tr>
              )))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
