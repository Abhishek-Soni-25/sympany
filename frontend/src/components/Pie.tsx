import { useState } from "react";
import { pieLayout } from "../chartSvg";

// Labelled donut with leader lines. Interactive: hover highlights a slice. `unit` names what
// is counted ("posts", "accounts").
export function PieChart({ data, colorFor, unit = "posts" }: { data: { name: string; value: number }[]; colorFor?: (n: string) => string; unit?: string }) {
  const [hi, setHi] = useState<number | null>(null);
  const rows = data.filter((d) => d.value > 0);
  if (rows.length === 0) return <div className="muted" style={{ fontSize: 13 }}>No data.</div>;
  const L = pieLayout(rows, colorFor);
  return (
    <svg width="100%" viewBox={`0 0 ${L.W} ${L.H}`} style={{ display: "block", maxWidth: 620, margin: "0 auto" }}>
      {L.arcs.map((a, i) => (
        <path key={i} d={a.path} fill={a.color} stroke="#fff" strokeWidth={2} opacity={hi === null || hi === i ? 1 : 0.35}
          onMouseEnter={() => setHi(i)} onMouseLeave={() => setHi(null)} style={{ cursor: "pointer", transition: "opacity .15s" }} />
      ))}
      <text x={L.cx} y={L.cy - 2} textAnchor="middle" fontSize="28" fontWeight="700" fill="var(--ink)">{L.total.toLocaleString()}</text>
      <text x={L.cx} y={L.cy + 16} textAnchor="middle" fontSize="12" fill="var(--ink-faint)">{unit}</text>
      {L.labels.map((l, i) => (
        <g key={l.name} opacity={hi === null || hi === i ? 1 : 0.4} onMouseEnter={() => setHi(i)} onMouseLeave={() => setHi(null)} style={{ cursor: "pointer" }}>
          <polyline points={l.poly} fill="none" stroke="#C9BFB8" strokeWidth={hi === i ? 1.8 : 1} />
          <text x={l.x} y={l.y - 3} textAnchor={l.anchor} fontSize="15" fontWeight="600" fill="var(--ink)">{l.name}</text>
          <text x={l.x} y={l.y + 15} textAnchor={l.anchor} fontSize="13.5" fill="var(--ink-soft)">{l.count.toLocaleString()} ({l.pct.toFixed(1)}%)</text>
        </g>
      ))}
    </svg>
  );
}
