import { useMemo, useState } from "react";
import { safeHref } from "../safeUrl";
import type { CompetitorPost, Mention } from "../types";
import { BRAND_SHORT } from "../brand";
import { PlatformName } from "../components/PlatformLogo";
import { CategoryChip, fmtTime } from "../components/ui";
import { platformLabel } from "../labels";

// Ratings & Reviews: how customers rate Sympany's app (Play Store, App Store) and its
// agencies (Google Maps). Every review carries a 1-5 star rating; low ratings are the ones
// the risk team reads, so the page leads with each source's rating month by month.

export const REVIEW_PLATFORMS = ["play_store", "app_store", "google_maps"];
const SOURCE_NOTE: Record<string, string> = {
  play_store: "Sympany app, Android",
  app_store: "Sympany app, iPhone",
  google_maps: "Agency reviews across Switzerland",
};

const Panel = ({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) => (
  <div className="panel"><div className="panel-head"><h3>{title}</h3>{right}</div><div className="panel-body">{children}</div></div>
);

const monthKey = (iso: string) => iso.slice(0, 7);
const monthLabel = (k: string) => new Date(`${k}-01T00:00:00`).toLocaleDateString(undefined, { month: "short" });
const avg = (xs: number[]) => xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;

/** Diverging scale on the dashboard's sentiment colours: 1★ red, 3★ grey, 5★ green. */
function ratingColor(r: number | null): string {
  if (r == null) return "var(--line-soft)";
  const t = Math.max(0, Math.min(1, (r - 1) / 4));
  if (t < 0.5) return `color-mix(in srgb, var(--high) ${Math.round((0.5 - t) * 200)}%, #D6CCC4)`;
  return `color-mix(in srgb, var(--ok) ${Math.round((t - 0.5) * 200)}%, #D6CCC4)`;
}

function Stars({ value }: { value: number }) {
  return (
    <span className="rv-stars" role="img" aria-label={`${value.toFixed(1)} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((i) => {
        const fill = Math.max(0, Math.min(1, value - (i - 1)));
        return <span key={i} className="rv-star"><span style={{ width: `${fill * 100}%` }} /></span>;
      })}
    </span>
  );
}

/** Each insurer's average rating per review source, Sympany first: the competitor comparison. */
function BankComparison({ own, competitors, months }: { own: Mention[]; competitors: CompetitorPost[]; months: string[] }) {
  const banks = [
    { name: BRAND_SHORT, own: true, rs: own },
    ...[...new Set(competitors.map((p) => p.brand))].sort().map((b) => ({ name: b, own: false, rs: competitors.filter((p) => p.brand === b) })),
  ];
  if (banks.length < 2) return null;
  const cell = (rs: { rating?: number }[]) => {
    const a = avg(rs.map((r) => Number(r.rating)));
    return a == null
      ? <span className="rv-cmp-cell rv-cmp-none">–</span>
      : <span className="rv-cmp-cell" style={{ background: ratingColor(a) }} title={`${a.toFixed(2)} stars from ${rs.length.toLocaleString()} reviews`}>
          {a.toFixed(1)}<small>{rs.length.toLocaleString()}</small></span>;
  };
  return (
    <div className="panel rv-cmp">
      <div className="panel-head">
        <h3>Ratings against competitors</h3>
        <span className="count">average stars · competitor Play Store reviews are sampled (100 every 10 days)</span>
      </div>
      <div className="panel-body">
        <div className="rv-cmp-grid" style={{ gridTemplateColumns: `minmax(170px, 1.2fr) repeat(3, minmax(90px, 1fr)) minmax(260px, 3fr)` }}>
          <span /><span>Play Store</span><span>App Store</span><span>Google Maps</span>
          <span className="rv-months">{months.map((m) => <span key={m}>{monthLabel(m)}</span>)}</span>
          {banks.map((b) => (
            <div className={`rv-cmp-row${b.own ? " own" : ""}`} key={b.name}>
              <span className="rv-cmp-bank">{b.name}</span>
              {REVIEW_PLATFORMS.map((p) => <span key={p}>{cell(b.rs.filter((r) => r.platform === p))}</span>)}
              <span className="rv-months" aria-label={`${b.name} Play Store rating by month`}>
                {months.map((m) => {
                  const ms = b.rs.filter((r) => r.platform === "play_store" && monthKey(r.timestamp) === m).map((r) => Number(r.rating));
                  const a = avg(ms);
                  return <span key={m} className="rv-cell" style={{ background: ratingColor(a) }}
                    title={a == null ? `${monthLabel(m)}: no Play Store reviews` : `${monthLabel(m)}: ${a.toFixed(2)} stars from ${ms.length} Play Store reviews`}>
                    {a == null ? "–" : a.toFixed(1)}</span>;
                })}
              </span>
            </div>
          ))}
        </div>
        <p className="rv-cmp-note">The strip on the right is each insurer's Play Store rating month by month.</p>
      </div>
    </div>
  );
}

export function Reviews({ mentions, competitors = [] }: { mentions: Mention[]; competitors?: CompetitorPost[] }) {
  const reviews = useMemo(() => mentions.filter((m) => REVIEW_PLATFORMS.includes(m.platform) && m.rating != null), [mentions]);
  const months = useMemo(() => [...new Set(reviews.map((r) => monthKey(r.timestamp)))].sort(), [reviews]);
  const present = REVIEW_PLATFORMS.filter((p) => reviews.some((r) => r.platform === p));
  const compReviews = useMemo(() => competitors.filter((p) => REVIEW_PLATFORMS.includes(p.platform) && p.rating != null), [competitors]);
  const [pick, setPick] = useState<string>("all");

  if (!reviews.length) {
    return (
      <div className="panel"><div className="empty">
        No app or agency reviews in this view. Choose All channels, or Play Store, App Store or Google Maps, in the filter row above.
      </div></div>
    );
  }

  const rows = present.map((p) => {
    const rs = reviews.filter((r) => r.platform === p);
    const stars = rs.map((r) => Number(r.rating));
    const low = stars.filter((s) => s <= 2).length;
    return {
      p, count: rs.length, avg: avg(stars) ?? 0, lowPct: Math.round((low / rs.length) * 100),
      byMonth: months.map((m) => {
        const ms = rs.filter((r) => monthKey(r.timestamp) === m).map((r) => Number(r.rating));
        return { m, n: ms.length, avg: avg(ms) };
      }),
    };
  });

  const scope = pick === "all" ? reviews : reviews.filter((r) => r.platform === pick);
  const dist = [5, 4, 3, 2, 1].map((s) => ({ s, n: scope.filter((r) => Number(r.rating) === s).length }));
  const distMax = Math.max(1, ...dist.map((d) => d.n));
  const stack = months.map((m) => {
    const ms = scope.filter((r) => monthKey(r.timestamp) === m);
    return { m, total: ms.length, parts: [1, 2, 3, 4, 5].map((s) => ms.filter((r) => Number(r.rating) === s).length) };
  });
  const stackMax = Math.max(1, ...stack.map((s) => s.total));
  const lowRated = scope.filter((r) => Number(r.rating) <= 2 && !String(r.text).match(/^\d-star review/))
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 25);

  return (
    <>
      <div className="panel rv-ledger">
        <div className="panel-head">
          <h3>Rating by month</h3>
          <span className="count">average stars per month · {months.length ? `${monthLabel(months[0])} – ${monthLabel(months[months.length - 1])}` : ""}</span>
        </div>
        <div className="rv-rows">
          <div className="rv-row rv-head" aria-hidden="true">
            <span /><span>Average</span><span>Reviews</span><span>1–2 stars</span>
            <span className="rv-months">{months.map((m) => <span key={m}>{monthLabel(m)}</span>)}</span>
          </div>
          {rows.map((r) => (
            <div className="rv-row" key={r.p}>
              <span className="rv-src"><PlatformName platform={r.p} size={16} /><small>{SOURCE_NOTE[r.p]}</small></span>
              <span className="rv-avg"><b>{r.avg.toFixed(1)}</b><Stars value={r.avg} /></span>
              <span className="rv-num">{r.count.toLocaleString()}</span>
              <span className="rv-num rv-low">{r.lowPct}%</span>
              <span className="rv-months">
                {r.byMonth.map((c) => (
                  <span key={c.m} className="rv-cell" style={{ background: ratingColor(c.avg) }}
                    title={c.avg == null ? `${monthLabel(c.m)}: no reviews` : `${monthLabel(c.m)}: ${c.avg.toFixed(2)} stars from ${c.n} reviews`}>
                    {c.avg == null ? "–" : c.avg.toFixed(1)}
                  </span>
                ))}
              </span>
            </div>
          ))}
        </div>
      </div>

      <BankComparison own={reviews} competitors={compReviews} months={months} />

      <div className="rv-pick" role="radiogroup" aria-label="Review source">
        {["all", ...present].map((p) => (
          <button key={p} role="radio" aria-checked={pick === p} onClick={() => setPick(p)}>
            {p === "all" ? "All review sources" : platformLabel(p)}
          </button>
        ))}
      </div>

      <div className="grid2">
        <Panel title="Stars given" right={<span className="count">{scope.length.toLocaleString()} reviews</span>}>
          {dist.map((d) => (
            <div className="hbar" key={d.s}>
              <span className="hbar-name">{d.s} star{d.s > 1 ? "s" : ""}</span>
              <span className="hbar-track"><span className="hbar-fill" style={{ width: `${(d.n / distMax) * 100}%`, background: d.s <= 2 ? "var(--high)" : d.s === 3 ? "#B3AAA4" : "var(--ok)" }} /></span>
              <span className="hbar-num">{d.n.toLocaleString()}</span>
            </div>
          ))}
        </Panel>
        <Panel title="Reviews per month" right={<span className="count">red 1–2 · grey 3 · green 4–5 stars</span>}>
          <div className="rv-cols">
            {stack.map((s) => (
              <div className="rv-col" key={s.m} title={`${monthLabel(s.m)}: ${s.total} reviews`}>
                <div className="rv-bar" style={{ height: `${(s.total / stackMax) * 100}%` }}>
                  {s.parts.map((n, i) => n ? <span key={i} style={{ flexGrow: n, background: i <= 1 ? "var(--high)" : i === 2 ? "#B3AAA4" : "var(--ok)" }} /> : null)}
                </div>
                <span className="rv-col-n">{s.total.toLocaleString()}</span>
                <span className="rv-col-m">{monthLabel(s.m)}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Latest low-rated reviews" right={<span className="count">1–2 stars, newest first</span>}>
        {lowRated.length ? (
          <ul className="rv-list">
            {lowRated.map((r) => (
              <li key={`${r.platform}-${r.id}`}>
                <div className="rv-meta">
                  <span className="rv-badge">{r.rating}★</span>
                  <PlatformName platform={r.platform} />
                  <span className="muted">{fmtTime(r.timestamp)}</span>
                  {r.risk_category && !["GENERAL", "NONE"].includes(r.risk_category) && <CategoryChip category={r.risk_category} />}
                  {safeHref(r.url) && <a className="link" href={safeHref(r.url)} target="_blank" rel="noreferrer">Open review</a>}
                </div>
                <p>{r.text}</p>
              </li>
            ))}
          </ul>
        ) : <div className="empty">No 1–2 star reviews with text in this view.</div>}
      </Panel>
    </>
  );
}
