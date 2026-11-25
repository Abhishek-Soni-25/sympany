import type { ReactNode } from "react";
import { CATEGORY_COLORS } from "../palette";
import type { Insights as InsightsData } from "../demo";
import { categoryLabel, platformLabel } from "../labels";

const CAT_COLOR = CATEGORY_COLORS;

/** What a click in the insights asks to see. */
export type InsightPick =
  | { kind: "alerts" }
  | { kind: "sentiment"; value: "negative" | "neutral" | "positive" }
  | { kind: "category"; value: string }
  | { kind: "channel"; value: string; alertsOnly?: boolean };

// A card or row that is a button when the dashboard can show the posts behind it.
function Pick({ className, onClick, title, children }: {
  className: string; onClick?: () => void; title?: string; children: ReactNode;
}) {
  return onClick ? (
    <button type="button" className={`${className} pickable`} onClick={onClick} title={title}>{children}</button>
  ) : (
    <div className={className}>{children}</div>
  );
}

export function Insights({ d, onPick }: { d: InsightsData; onPick?: (p: InsightPick) => void }) {
  const sent = d.sentiment;
  const total = Math.max(1, d.total);
  const catMax = Math.max(1, ...d.categories.map((c) => c.count));
  const pick = (p: InsightPick) => (onPick ? () => onPick(p) : undefined);
  const SENT = [
    { key: "negative" as const, label: "Negative", n: sent.negative, color: "var(--high)" },
    { key: "neutral" as const, label: "Neutral", n: sent.neutral, color: "#C9BFB8" },
    { key: "positive" as const, label: "Positive", n: sent.positive, color: "var(--ok)" },
  ];

  return (
    <>
      {/* Highlight metrics */}
      <div className="insight-strip">
        <Pick className="insight-card" onClick={pick({ kind: "alerts" })} title="Show the posts flagged as a risk">
          <div className="ic-label">Action required</div>
          <div className="ic-value">
            {d.alerts}<span className="ic-unit"> / {d.total}</span>
          </div>
          <div className="ic-sub">items flagged as a risk</div>
        </Pick>
        <Pick className="insight-card" onClick={pick({ kind: "sentiment", value: "negative" })} title="Show the negative posts">
          <div className="ic-label">Negative sentiment</div>
          <div className="ic-value">{d.negPct}%</div>
          <div className="ic-sub">{sent.negative} of {d.total} mentions</div>
        </Pick>
        <Pick className="insight-card" onClick={d.topCategory ? pick({ kind: "category", value: d.topCategory.name }) : undefined}
          title={d.topCategory ? `Show the ${categoryLabel(d.topCategory.name).toLowerCase()} alerts` : undefined}>
          <div className="ic-label">Top risk category</div>
          <div className="ic-value ic-text" style={d.topCategory ? undefined : { color: "var(--ink-faint)" }}>
            {d.topCategory ? categoryLabel(d.topCategory.name) : "—"}
          </div>
          <div className="ic-sub">{d.topCategory ? `${d.topCategory.count} alerts` : "no alerts"}</div>
        </Pick>
        <Pick className="insight-card" onClick={d.topChannel ? pick({ kind: "channel", value: d.topChannel.name, alertsOnly: true }) : undefined}
          title={d.topChannel ? `Show the alerts on ${platformLabel(d.topChannel.name)}` : undefined}>
          <div className="ic-label">Most-flagged channel</div>
          <div className="ic-value ic-text">{d.topChannel ? platformLabel(d.topChannel.name) : "—"}</div>
          <div className="ic-sub">{d.topChannel ? `${d.topChannel.alerts} alerts` : "all clear"}</div>
        </Pick>
      </div>

      <div className="grid3">
        {/* Sentiment breakdown */}
        <div className="panel">
          <div className="panel-head"><h3>Sentiment breakdown</h3></div>
          <div className="panel-body">
            <div className="stacked">
              {SENT.map((s) => <span key={s.key} className="seg" style={{ width: `${(s.n / total) * 100}%`, background: s.color }} />)}
            </div>
            <div className="sent-legend">
              {SENT.map((s) => (
                <Pick key={s.key} className="sent-row" onClick={pick({ kind: "sentiment", value: s.key })} title={`Show the ${s.label.toLowerCase()} posts`}>
                  <span className="dot" style={{ background: s.color }} /> {s.label} <b>{s.n}</b>
                </Pick>
              ))}
            </div>
          </div>
        </div>

        {/* Risk category */}
        <div className="panel">
          <div className="panel-head"><h3>Alerts by risk category</h3></div>
          <div className="panel-body">
            {d.categories.length === 0 && <div className="muted" style={{ fontSize: 13 }}>No alerts.</div>}
            <div className="hbars">
              {d.categories.map((c) => {
                const col = CAT_COLOR[c.name] ?? "var(--brand)";
                return (
                  <Pick className="hbar" key={c.name} onClick={pick({ kind: "category", value: c.name })}>
                    <span className="hbar-name">{categoryLabel(c.name)}</span>
                    <span className="hbar-track">
                      <span className="hbar-fill" style={{ width: `${Math.max(6, (c.count / catMax) * 100)}%`, background: col }} />
                    </span>
                    <span className="hbar-num">{c.count}</span>
                  </Pick>
                );
              })}
            </div>
          </div>
        </div>

        {/* Channel risk */}
        <div className="panel">
          <div className="panel-head"><h3>Channel risk</h3></div>
          <div className="panel-body">
            <div className="hbars">
              {d.channelRisk.map((c) => {
                const col = c.alerts ? "var(--high)" : "var(--ink-faint)";
                return (
                  <Pick className="hbar" key={c.name} onClick={c.total ? pick({ kind: "channel", value: c.name }) : undefined}>
                    <span className="hbar-name" style={{ width: 110 }}>{platformLabel(c.name)}</span>
                    <span className="hbar-track">
                      <span className="hbar-fill" style={{ width: `${c.total ? Math.max(c.alerts ? 6 : 0, (c.alerts / c.total) * 100) : 0}%`, background: col }} />
                    </span>
                    <span className="hbar-num" style={{ color: c.alerts ? "var(--high)" : "var(--ink-faint)" }}>
                      {c.alerts}<span className="muted" style={{ fontWeight: 400 }}>/{c.total}</span>
                    </span>
                  </Pick>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
