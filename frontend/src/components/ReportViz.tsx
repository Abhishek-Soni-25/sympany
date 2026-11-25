import { useState } from "react";
import type { ChangeStat } from "../reportData";
import { kfmt, changeNote } from "../reportData";
import { useScope } from "../filters";
import { platformColor } from "../analytics";
import { platformLabel } from "../labels";
import { dayLabel, tickEvery, yTicks } from "../chartSvg";
import { AXIS, GRID, NAVY } from "../palette";
import { PlatformLogo } from "./PlatformLogo";


// undefined = not applicable (nothing rendered); null = no earlier data to compare with.
export function ChangePct({ v, title }: { v: number | null | undefined; title?: string }) {
  if (v === undefined) return null;
  if (v === null) return <span className="chg muted" title="No data in the earlier period to compare with">No earlier data</span>;
  if (v === 0) return <span className="chg muted" title={title}>No change</span>;
  const up = v > 0;
  return <span className="chg" title={title} style={{ color: up ? "var(--ok)" : "var(--high)" }}>{up ? "+" : "−"}{Math.abs(v)}%</span>;
}

// Pastel channel stat card (Channel-Wise Follower Count).
export function FollowerCards({ title, data, onCard, note, empty }: {
  title: string; data: ChangeStat[]; onCard?: (label: string) => void; note?: string; empty?: string;
}) {
  return (
    <div className="panel">
      <div className="panel-head"><h3>{title}</h3><span className="count">{note ?? (onCard ? "click a card for detail" : "")}</span></div>
      <div className="panel-body">
        {data.length === 0 && <div className="muted" style={{ fontSize: 13 }}>{empty ?? "No data yet."}</div>}
        <div className="fc-grid">
          {data.map((d) => (
            <div className={`fc-card ${onCard ? "fc-click" : ""}`} key={d.label} onClick={() => onCard?.(d.label)} style={{ borderLeftColor: platformColor(d.label) }}>
              <div className="fc-head"><span className="fc-ico"><PlatformLogo platform={d.label} size={20} /></span><span className="fc-name">{platformLabel(d.label)}</span></div>
              <div className="fc-val">{d.value < 0 ? "−" : ""}{kfmt(Math.abs(d.value))} {d.sharePct !== undefined && <span className="fc-share">{d.sharePct}% share</span>}</div>
              <ChangePct v={d.changePct} title="vs the previous follower snapshot" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Sentiment split cards (Total / Negative / Neutral / Positive).
const SPLIT_RULE: Record<string, string> = { "Total Mentions": "var(--navy)", Negative: "var(--high)", Neutral: "#C9BFB8", Positive: "var(--ok)" };
export function SplitCards({ data }: { data: ChangeStat[] }) {
  const { range } = useScope();
  const tip = changeNote(range?.days ?? null);
  return (
    <div className="fc-grid">
      {data.map((d) => (
        <div className="split-card" key={d.label} style={{ borderLeftColor: SPLIT_RULE[d.label] ?? "var(--line)" }}>
          <div className="split-label">{d.label}</div>
          <div className="split-val">{kfmt(d.value)} {d.sharePct !== undefined && <span className="split-share">{d.sharePct}%</span>}</div>
          <ChangePct v={d.changePct} title={tip[0].toUpperCase() + tip.slice(1)} />
        </div>
      ))}
    </div>
  );
}

// Simple KPI with change (Mentions Count, Avg/Day, etc.)
export function StatRow({ items }: { items: { label: string; value: string | number; changePct?: number }[] }) {
  return (
    <div className="statrow">
      {items.map((it) => (
        <div className="statrow-item" key={it.label}>
          <div className="statrow-label">{it.label}</div>
          <div className="statrow-value">{it.value} {it.changePct !== undefined && <ChangePct v={it.changePct} />}</div>
        </div>
      ))}
    </div>
  );
}

// Area-line trend chart (total mentions per day). Hover shows the day's count.
export function AreaTrend({ data, height = 260 }: { data: { day: string; total: number }[]; height?: number }) {
  const [hi, setHi] = useState<number | null>(null);
  if (data.length === 0) return <div className="muted" style={{ fontSize: 13 }}>No dated items yet.</div>;
  const W = 900, H = height, padL = 40, pad = 30;
  const ticks = yTicks(Math.max(1, ...data.map((d) => d.total))), max = ticks[4];
  const n = data.length, every = tickEvery(n);
  const x = (i: number) => padL + (i / Math.max(1, n - 1)) * (W - padL - pad);
  const y = (v: number) => H - pad - (v / max) * (H - pad * 2);
  const line = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d.total).toFixed(1)}`).join(" ");
  const area = `${line} L${x(n - 1)},${H - pad} L${x(0)},${H - pad} Z`;
  return (
    <div className="chart-wrap" style={{ position: "relative", overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="xMidYMid meet" style={{ minWidth: 520 }}>
        {ticks.map((t) => <g key={t}><line x1={padL} x2={W - pad} y1={y(t)} y2={y(t)} stroke={GRID} /><text x={padL - 8} y={y(t) + 4} fontSize="10" fill={AXIS} textAnchor="end">{t}</text></g>)}
        <path d={area} fill={NAVY} fillOpacity={0.08} />
        <path d={line} fill="none" stroke={NAVY} strokeWidth="2" strokeLinejoin="round" />
        {hi !== null && <line x1={x(hi)} x2={x(hi)} y1={pad} y2={H - pad} stroke={AXIS} strokeDasharray="4 3" opacity="0.6" />}
        {hi !== null && <circle cx={x(hi)} cy={y(data[hi].total)} r={4.5} fill={NAVY} />}
        {data.map((d, i) => i % every === 0 && <text key={i} x={x(i)} y={H - 8} fontSize="10" fill={AXIS} textAnchor="middle">{dayLabel(d.day)}</text>)}
        {data.map((_, i) => <rect key={i} x={x(i) - (W / n) / 2} y={0} width={W / n} height={H} fill="transparent" onMouseEnter={() => setHi(i)} onMouseLeave={() => setHi(null)} />)}
      </svg>
      {hi !== null && (
        <div className="chart-tip" style={{ left: `${(x(hi) / W) * 100}%` }}>
          <b>{dayLabel(data[hi].day)}</b><br />{data[hi].total} mentions
        </div>
      )}
    </div>
  );
}

// Interactive stacked sentiment trend — legend, y-axis, chronological, hover tooltip.
export function StackedTrend({ data, height = 240 }: {
  data: { day: string; positive: number; neutral: number; negative: number; total: number }[]; height?: number;
}) {
  const [hi, setHi] = useState<number | null>(null);
  const rows = [...data].sort((a, b) => a.day.localeCompare(b.day));
  if (rows.length === 0) return <div className="muted" style={{ fontSize: 13 }}>No dated items yet.</div>;
  const W = 900, H = height, padL = 34, padB = 30, padT = 10;
  const max = Math.max(1, ...rows.map((d) => d.total));
  const n = rows.length;
  const bw = Math.min(46, ((W - padL - 10) / n) * 0.62);
  const x = (i: number) => padL + (i + 0.5) * ((W - padL - 10) / n);
  const yScale = (v: number) => (v / max) * (H - padT - padB);
  const ticks = [0, .25, .5, .75, 1];
  return (
    <div className="chart-wrap" style={{ position: "relative", overflowX: "auto" }}>
      <div className="ml-legend">
        <span className="ml-leg"><span className="ml-swatch" style={{ background: "var(--ok)", height: 10, width: 10, borderRadius: 3 }} />Positive</span>
        <span className="ml-leg"><span className="ml-swatch" style={{ background: "#D6CCC4", height: 10, width: 10, borderRadius: 3 }} />Neutral</span>
        <span className="ml-leg"><span className="ml-swatch" style={{ background: "var(--high)", height: 10, width: 10, borderRadius: 3 }} />Negative</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="xMidYMid meet" style={{ minWidth: 560 }}>
        {ticks.map((f) => {
          const yy = padT + (1 - f) * (H - padT - padB);
          return <g key={f}><line x1={padL} x2={W - 10} y1={yy} y2={yy} stroke="#F2ECE6" /><text x={padL - 6} y={yy + 3} fontSize="9" fill="#9A9095" textAnchor="end">{Math.round(max * f)}</text></g>;
        })}
        {rows.map((d, i) => {
          const base = H - padB;
          const hN = yScale(d.negative), hU = yScale(d.neutral), hP = yScale(d.positive);
          return (
            <g key={d.day} onMouseEnter={() => setHi(i)} onMouseLeave={() => setHi(null)} style={{ cursor: "pointer" }} opacity={hi === null || hi === i ? 1 : 0.5}>
              <rect x={x(i) - bw / 2} y={base - hN} width={bw} height={hN} fill="var(--high)" rx="2" />
              <rect x={x(i) - bw / 2} y={base - hN - hU} width={bw} height={hU} fill="#D6CCC4" />
              <rect x={x(i) - bw / 2} y={base - hN - hU - hP} width={bw} height={hP} fill="var(--ok)" rx="2" />
              {i % Math.max(1, Math.ceil(n / 12)) === 0 && <text x={x(i)} y={H - 12} fontSize="9" fill="#7A7075" textAnchor="middle">{dayLabel(d.day)}</text>}
            </g>
          );
        })}
      </svg>
      {hi !== null && (
        <div className="chart-tip" style={{ left: `${(x(hi) / W) * 100}%` }}>
          <b>{rows[hi].day}</b> · {rows[hi].total} total
          <div><span className="ml-swatch" style={{ background: "var(--high)", height: 9, width: 9, borderRadius: 2 }} /> Negative: {rows[hi].negative}</div>
          <div><span className="ml-swatch" style={{ background: "#D6CCC4", height: 9, width: 9, borderRadius: 2 }} /> Neutral: {rows[hi].neutral}</div>
          <div><span className="ml-swatch" style={{ background: "var(--ok)", height: 9, width: 9, borderRadius: 2 }} /> Positive: {rows[hi].positive}</div>
        </div>
      )}
    </div>
  );
}

// Multi-series line chart (sentiment or brands over time) with legend and hover.
export function MultiLineTrend({ series, labels, height = 300 }: {
  series: { name: string; color: string; points: number[] }[]; labels: string[]; height?: number;
}) {
  const [hi, setHi] = useState<number | null>(null);
  if (!series.length || !labels.length) return <div className="muted" style={{ fontSize: 13 }}>No data.</div>;
  const W = 920, H = height, padL = 40, pad = 32, n = labels.length, every = tickEvery(n);
  const ticks = yTicks(Math.max(1, ...series.flatMap((s) => s.points))), max = ticks[4];
  const x = (i: number) => padL + (i / Math.max(1, n - 1)) * (W - padL - pad);
  const y = (v: number) => H - pad - (v / max) * (H - pad * 2);
  return (
    <div className="chart-wrap" style={{ position: "relative", overflowX: "auto" }}>
      <div className="ml-legend">
        {series.map((s) => <span key={s.name} className="ml-leg"><span className="ml-swatch" style={{ background: s.color }} />{s.name}</span>)}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="xMidYMid meet" style={{ minWidth: 560 }}>
        {ticks.map((t) => <g key={t}><line x1={padL} x2={W - pad} y1={y(t)} y2={y(t)} stroke={GRID} /><text x={padL - 8} y={y(t) + 4} fontSize="10" fill={AXIS} textAnchor="end">{t}</text></g>)}
        {hi !== null && <line x1={x(hi)} x2={x(hi)} y1={pad} y2={H - pad} stroke={AXIS} strokeDasharray="4 3" opacity="0.6" />}
        {series.map((s) => (
          <g key={s.name}>
            <path d={s.points.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" />
            {hi !== null && <circle cx={x(hi)} cy={y(s.points[hi])} r={4} fill="#fff" stroke={s.color} strokeWidth="2" />}
          </g>
        ))}
        {labels.map((l, i) => i % every === 0 && <text key={i} x={x(i)} y={H - 8} fontSize="10" fill={AXIS} textAnchor="middle">{dayLabel(l)}</text>)}
        {labels.map((_, i) => <rect key={i} x={x(i) - (W / n) / 2} y={0} width={W / n} height={H} fill="transparent" onMouseEnter={() => setHi(i)} onMouseLeave={() => setHi(null)} />)}
      </svg>
      {hi !== null && (
        <div className="chart-tip" style={{ left: `${(x(hi) / W) * 100}%` }}>
          <b>{dayLabel(labels[hi])}</b>
          {series.map((s) => <div key={s.name}><span className="ml-swatch" style={{ background: s.color }} /> {s.name}: {s.points[hi]}</div>)}
        </div>
      )}
    </div>
  );
}

// Horizontal comparison bars (response time, engagement across brands) — coloured fills.
export function HBarCompare({ data, fmt, colorOwn }: { data: { name: string; value: number; own?: boolean }[]; fmt?: (v: number) => string; colorOwn?: boolean }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="hbars">
      {data.map((d) => {
        const c = colorOwn && d.own ? "var(--brand)" : "#A79DCF";
        return (
          <div className="hbar" key={d.name}>
            <span className="hbar-name" style={{ width: 168 }}>{d.name}</span>
            <span className="hbar-track">
              <span className="hbar-fill" style={{ width: `${Math.max(5, (d.value / max) * 100)}%`, background: c }} />
            </span>
            <span className="hbar-num" style={{ width: 90 }}>{fmt ? fmt(d.value) : d.value.toLocaleString()}</span>
          </div>
        );
      })}
    </div>
  );
}

// Reply time: "15 min", "11 h 29 min", "1 d 11 h".
export const durfmt = (secs: number) => {
  const d = Math.floor(secs / 86400), h = Math.floor((secs % 86400) / 3600), m = Math.floor((secs % 3600) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
};

// Section banner like the report section dividers.
export function SectionBanner({ n, title }: { n: number; title: string }) {
  return <div className="rep-banner" data-section={n}><h2 className="rep-banner-title">{title}</h2></div>;
}
