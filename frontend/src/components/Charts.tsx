import type { Slice } from "../analytics";
import { platformColor } from "../analytics";
import { wordCloudLayout, type CloudTone } from "../chartSvg";
import { STEEL } from "../palette";
import { displayName } from "../labels";

// A lightweight SVG donut chart — no chart library needed.
export function Donut({ data, colorFor, size = 190 }: {
  data: Slice[]; colorFor?: (name: string) => string; size?: number;
}) {
  const total = Math.max(1, data.reduce((a, s) => a + s.value, 0));
  const color = colorFor ?? platformColor;
  const r = size / 2;
  const stroke = size * 0.22;
  const radius = r - stroke / 2;
  const circ = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="donut-wrap">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <g transform={`rotate(-90 ${r} ${r})`}>
          {data.map((s) => {
            const frac = s.value / total;
            const dash = frac * circ;
            const el = (
              <circle key={s.name} cx={r} cy={r} r={radius} fill="none"
                stroke={color(s.name)} strokeWidth={stroke}
                strokeDasharray={`${dash} ${circ - dash}`} strokeDashoffset={-offset} />
            );
            offset += dash;
            return el;
          })}
        </g>
        <text x={r} y={r - 4} textAnchor="middle" className="donut-total">{total}</text>
        <text x={r} y={r + 14} textAnchor="middle" className="donut-label">mentions</text>
      </svg>
      <div className="donut-legend">
        {data.map((s) => (
          <div key={s.name} className="dl-row">
            <span className="dot" style={{ background: color(s.name) }} />
            <span className="dl-name">{displayName(s.name)}</span>
            <span className="dl-val">{s.value}<span className="muted"> · {Math.round((s.value / total) * 100)}%</span></span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Horizontal bar list. labelFor: display name for a row (default: platform keys get their
// display name, anything else is shown as stored);
// onPick: makes each row a button (e.g. to show the posts behind it).
export function BarList({ data, colorFor, unit, labelFor, onPick }: {
  data: Slice[]; colorFor?: (name: string) => string; unit?: string;
  labelFor?: (name: string) => string; onPick?: (name: string) => void;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const color = colorFor ?? (() => STEEL);
  if (data.length === 0) return <div className="muted" style={{ fontSize: 13 }}>No data.</div>;
  return (
    <div className="hbars">
      {data.map((d) => {
        const c = color(d.name);
        const inner = (
          <>
            <span className="hbar-name">{(labelFor ?? displayName)(d.name)}</span>
            <span className="hbar-track">
              <span className="hbar-fill" style={{ width: `${Math.max(d.value ? 4 : 0, (d.value / max) * 100)}%`, background: c }} />
            </span>
            <span className="hbar-num">{d.value.toLocaleString()}{unit ? ` ${unit}` : ""}</span>
          </>
        );
        return onPick ? (
          <button type="button" className="hbar pickable" key={d.name} onClick={() => onPick(d.name)}>{inner}</button>
        ) : (
          <div className="hbar" key={d.name}>{inner}</div>
        );
      })}
    </div>
  );
}

// Stacked daily sentiment trend (columns).
export function TrendColumns({ data }: {
  data: { day: string; positive: number; neutral: number; negative: number; total: number }[];
}) {
  const max = Math.max(1, ...data.map((d) => d.total));
  if (data.length === 0) return <div className="muted" style={{ fontSize: 13 }}>No dated items.</div>;
  return (
    <div className="trend">
      {data.map((d) => (
        <div className="trend-col" key={d.day} title={`${d.day} — ${d.total} mentions`}>
          <div className="trend-bar" style={{ height: `${(d.total / max) * 140}px` }}>
            <span style={{ height: `${(d.negative / d.total) * 100}%`, background: "var(--high)" }} />
            <span style={{ height: `${(d.neutral / d.total) * 100}%`, background: "#D6CCC4" }} />
            <span style={{ height: `${(d.positive / d.total) * 100}%`, background: "var(--ok)" }} />
          </div>
          <div className="trend-day">{d.day.slice(5)}</div>
        </div>
      ))}
    </div>
  );
}

// Word cloud — circular spiral layout. Size and colour depth show how often a word is used;
// `tone` colours the positive / negative clouds by their sentiment.
export function WordCloud({ data, tone }: { data: Slice[]; tone?: CloudTone }) {
  if (data.length === 0) return <div className="muted" style={{ fontSize: 13 }}>Not enough text yet.</div>;
  const W = 620, H = 340;
  const nodes = wordCloudLayout(data, W, H, tone);
  const byName = new Map(data.map((d) => [d.name, d.value]));
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: "block", maxWidth: 660, margin: "0 auto" }}>
      {nodes.map((p) => (
        <text key={p.name} x={p.x} y={p.y} textAnchor="middle" dominantBaseline="middle"
          fontSize={p.size} fontWeight={p.weight} fill={p.color} className="wc-svg-word">
          <title>{`${p.name} · ${byName.get(p.name)}`}</title>
          {p.name}
        </text>
      ))}
    </svg>
  );
}
