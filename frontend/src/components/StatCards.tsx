import type { CSSProperties } from "react";
import type { Stats } from "../types";

export type StatKey = "all" | "HIGH" | "MEDIUM" | "norisk";

// The four headline numbers. The left rule shows the risk level a card counts; with
// onPick, each card opens the posts it counts.
export function StatCards({ stats, onPick }: { stats: Stats | null; onPick?: (k: StatKey) => void }) {
  const sev = stats?.by_severity ?? {};
  const cards: { key: StatKey; k: string; v: number; rule: string }[] = [
    { key: "all", k: "Items analysed", v: stats?.total_cases ?? 0, rule: "var(--navy)" },
    { key: "HIGH", k: "High severity", v: sev.HIGH ?? 0, rule: "var(--high)" },
    { key: "MEDIUM", k: "Medium severity", v: sev.MEDIUM ?? 0, rule: "var(--medium)" },
    { key: "norisk", k: "No risk", v: (sev.NONE ?? 0) + (sev.LOW ?? 0), rule: "var(--line)" },
  ];
  return (
    <div className="cards">
      {cards.map((c) => {
        const style = { "--rule": c.rule } as CSSProperties;
        const body = (
          <>
            <div className="k">{c.k}</div>
            <div className="v">{c.v.toLocaleString()}</div>
          </>
        );
        return onPick ? (
          <button type="button" className="card pickable" key={c.k} style={style} onClick={() => onPick(c.key)}
            title={c.v ? `Show the ${c.v} ${c.v === 1 ? "post" : "posts"}` : "No posts"}>
            {body}
          </button>
        ) : (
          <div className="card" key={c.k} style={style}>{body}</div>
        );
      })}
    </div>
  );
}
