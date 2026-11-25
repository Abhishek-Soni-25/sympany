import type { CompetitorSov, Mention } from "../types";
import { Donut } from "../components/Charts";
import { shareOfVoice } from "../analytics";
import { Icon } from "../components/Icon";
import { BRAND_NAME } from "../brand";

// PRD 6.6 — Competitor & Share of Voice, populated from the real competitor scan
// (/api/competitors). Sympany's totals come from the mentions store.
export function Competitors({ mentions, sov, onScan, scanning }: {
  mentions: Mention[]; sov: CompetitorSov | null; onScan: () => void; scanning: boolean;
}) {
  const rows: { name: string; e: CompetitorSov["own"]; own?: boolean }[] = [];
  if (sov) {
    rows.push({ name: BRAND_NAME, e: sov.own, own: true });
    for (const [name, e] of Object.entries(sov.competitors)) rows.push({ name, e });
  }
  rows.sort((a, b) => b.e.total - a.e.total);
  const max = Math.max(1, ...rows.map((r) => r.e.total));
  const collected = rows.some((r) => !r.own && r.e.total > 0);

  return (
    <>
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-head">
          <h3>Share of voice: Sympany and its competitors</h3>
          <button className="btn-ghost" onClick={onScan} disabled={scanning}
            title="Competitor posts are collected by Run Scan, together with Sympany's posts (once a day)">
            {scanning ? "Scanning…" : <><Icon name="scan" size={15} /> Run Scan</>}
          </button>
        </div>
        <div className="panel-body">
          {!collected && (
            <div className="banner banner-info" style={{ marginBottom: 16 }}>
              <Icon name="info" /> No competitor data yet. Click <b>Run Scan</b> to benchmark
              volume and sentiment against CSS, Helsana, SWICA and Visana.
            </div>
          )}
          <div className="sov-grid">
            {rows.map((r) => {
              const t = Math.max(1, r.e.total);
              return (
                <div className={`sov-brand ${r.own ? "active" : ""}`} key={r.name}>
                  <div className="sov-name">{r.name}</div>
                  <div className="sov-count">{r.e.total}</div>
                  <div className="sov-bar">
                    <span style={{ width: `${(r.e.total / max) * 100}%`, background: r.own ? "var(--accent)" : "#A79DCF" }} />
                  </div>
                  <div className="mini-sent">
                    <span style={{ color: "var(--high)" }}>{r.e.negative} neg</span> ·{" "}
                    <span className="muted">{r.e.neutral} neu</span> ·{" "}
                    <span style={{ color: "var(--ok)" }}>{r.e.positive} pos</span>
                  </div>
                  <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                    {Object.entries(r.e.by_platform).map(([p, n]) => `${p} ${n}`).join(" · ") || "no mentions"}
                  </div>
                  <div className="muted" style={{ fontSize: 11 }}>
                    {Math.round((r.e.total / t) * 100) === 100 ? "" : ""}
                    {r.e.total > 0 ? `${r.e.negative + r.e.positive} with clear sentiment` : ""}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h3>Sympany share of voice by channel</h3></div>
        <div className="panel-body"><Donut data={shareOfVoice(mentions)} /></div>
      </div>
    </>
  );
}
