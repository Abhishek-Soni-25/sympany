import { useMemo } from "react";
import type { CompetitorPost, CompetitorSov, FollowerSummary, Mention, ResponseTimes } from "../types";
import { marketingData, listeningData, competitionData, sentimentSeries, platformColor, changeNote } from "../reportData";
import { useScope, type Scope } from "../filters";
import { OWN, COMPETITOR_TINTS, STEEL, sentimentColor } from "../palette";

// Sympany in berry, every competitor in the lavender family.
const brandFill = (n: string) => isOwnBrand(n) ? OWN : COMPETITOR_TINTS[1];
import { downloadMarketing, downloadListening, downloadCompetition } from "../reportBuilders";
import { FollowerCards, SplitCards, StatRow, AreaTrend, MultiLineTrend, HBarCompare, durfmt, SectionBanner } from "../components/ReportViz";
import { BarList, WordCloud } from "../components/Charts";
import { PieChart } from "../components/Pie";
import { VocalUsers, SovSummary } from "../components/Viz";
import { PlatformNetwork } from "../components/NetworkGraph";
import { MetricDrawer, type MetricDetail } from "../components/MetricDrawer";
import { Competitors } from "./Competitors";
import { useState } from "react";
import { Icon } from "../components/Icon";
import { platformLabel } from "../labels";
import { isOwnBrand } from "../brand";

const Panel = ({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) => (
  <div className="panel"><div className="panel-head"><h3>{title}</h3>{right}</div><div className="panel-body">{children}</div></div>
);
const DownloadBar = ({ label, onClick, sample, scope }: { label: string; onClick: () => void; sample: boolean; scope: Scope }) => (
  <div className="report-toolbar">
    {sample && <span className="sample-tag">No data collected yet — run a scan to populate this report</span>}
    {!sample && <span className="muted" style={{ fontSize: 12.5 }}>The report covers {scope.period} · {scope.channels} · {scope.source} · Collection: {scope.coverage}</span>}
    <span style={{ flex: 1 }} />
    <button className="btn" onClick={onClick}><Icon name="download" size={15} /> {label}</button>
  </div>
);
// "measured 23 Oct 2026", or "average of 4 measurements, 1 Nov 2026 – 12 Nov 2026" for a period.
const responseNote = (last: string | null, first: string | null, n: number | null) =>
  !last ? "" : n && n > 1 && first ? `average of ${n} measurements, ${fmtDate(first)} – ${fmtDate(last)}` : `measured ${fmtDate(last)}`;
const fmtDate = (iso: string | null) => iso ? new Date(iso).toLocaleDateString("en-CH", { day: "numeric", month: "short", year: "numeric" }) : "";
const fmtTime = (iso: string | null) => iso ? new Date(iso).toLocaleString("en-CH", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const NoComp = () => <div className="muted" style={{ fontSize: 13 }}>No competitor posts collected yet — run the competitor scan below.</div>;
const Note = ({ children }: { children: React.ReactNode }) => <span className="count">{children}</span>;
const sentColor = sentimentColor;

/* ================= MARKETING ================= */
export function MarketingReport({ mentions, sov, followers }: { mentions: Mention[]; sov: CompetitorSov | null; followers: FollowerSummary | null }) {
  const scope = useScope();
  const change = changeNote(scope.range?.days ?? null);
  const d = useMemo(() => marketingData(mentions, sov, followers, scope.prior), [mentions, sov, followers, scope.prior]);
  const [detail, setDetail] = useState<MetricDetail | null>(null);
  const channelDetail = (label: string) => {
    const ch = mentions.filter((m) => m.platform === label);
    const e = (m: Mention) => Object.values(m.engagement || {}).reduce((a, b) => a + (Number(b) || 0), 0);
    setDetail({
      title: `${label} — channel detail`,
      subtitle: `${ch.length} tracked mentions on ${label}`,
      stats: [
        { label: "Mentions", value: ch.length },
        { label: "Engagement", value: ch.reduce((a, m) => a + e(m), 0).toLocaleString() },
        { label: "Negative", value: ch.filter((m) => m.sentiment === "negative").length },
        { label: "Positive", value: ch.filter((m) => m.sentiment === "positive").length },
      ],
      items: ch.sort((a, b) => e(b) - e(a)).slice(0, 6).map((m) => ({ platform: m.platform, text: m.text, url: m.url, sentiment: m.sentiment })),
    });
  };
  return (
    <>
      {detail && <MetricDrawer d={detail} onClose={() => setDetail(null)} />}
      <DownloadBar label="Download Marketing Report" onClick={() => downloadMarketing(d, { line: scope.line(mentions.length), change, tag: scope.fileTag })} sample={d.sample} scope={scope} />
      <SectionBanner n={1} title="Overall brand summary" />
      <FollowerCards title="Followers by channel" data={d.followers} onCard={channelDetail}
        note={d.followersAt ? `Sympany's own accounts · public counts as of ${fmtDate(d.followersAt)}` : undefined}
        empty="No follower snapshot yet. The next Run Scan records Sympany's public follower counts." />
      <div style={{ height: 16 }} />
      <FollowerCards title="New followers by channel" data={d.newFollowers} onCard={channelDetail}
        note={d.followersSince ? `growth from ${fmtTime(d.followersSince)} to ${fmtTime(d.followersAt)}` : undefined}
        empty="Needs two follower snapshots at least an hour apart — appears after the next scan." />
      <div style={{ height: 16 }} />
      <Panel title="Total mentions and sentiment split" right={<Note>{change}</Note>}>
        <SplitCards data={d.sentimentSplit} />
        <div style={{ height: 14 }} />
        <AreaTrend data={d.trend} />
      </Panel>
      <div style={{ height: 16 }} />
      <Panel title="Mentions by sentiment"><PieChart data={d.distribution} colorFor={sentColor} /></Panel>
      <div style={{ height: 16 }} />
      <div className="grid2">
        <Panel title="Words in positive posts"><WordCloud data={d.posWords} tone="positive" /></Panel>
        <Panel title="Words in negative posts"><WordCloud data={d.negWords} tone="negative" /></Panel>
      </div>
      <SectionBanner n={2} title="Voices and influencers" />
      <Panel title="Top influencers"><VocalUsers users={d.influencers} /></Panel>
      <div style={{ height: 16 }} />
      <div className="grid2">
        <Panel title="Top hashtags"><BarList data={d.hashtags} /></Panel>
        <Panel title="Share of voice"><BarList data={d.sov.map((b) => ({ name: b.name, value: b.value }))} colorFor={brandFill} /></Panel>
      </div>
    </>
  );
}

/* ================= LISTENING ================= */
export function ListeningReport({ mentions }: { mentions: Mention[] }) {
  const scope = useScope();
  const change = changeNote(scope.range?.days ?? null);
  const d = useMemo(() => listeningData(mentions, scope.prior), [mentions, scope.prior]);
  return (
    <>
      <DownloadBar label="Download Listening Report" onClick={() => downloadListening(d, { line: scope.line(mentions.length), change, tag: scope.fileTag })} sample={d.sample} scope={scope} />
      <SectionBanner n={1} title="Mentions overview" />
      <StatRow items={[
        { label: "Mentions", value: d.mentionsCount.toLocaleString() },
        { label: "Average per day", value: d.avgPerDay },
        { label: "From the public", value: d.incoming.toLocaleString() },
        { label: "From Sympany's accounts", value: d.outgoing.toLocaleString() },
        { label: "Unique accounts", value: d.uniqueUsers.toLocaleString() },
      ]} />
      <Panel title="Sentiment split" right={<Note>{change}</Note>}><SplitCards data={d.sentiment} /></Panel>
      <div style={{ height: 16 }} />
      <Panel title="Mentions per day by sentiment" right={<span className="count">hover for daily values</span>}>
        <MultiLineTrend {...sentimentSeries(mentions)} />
      </Panel>
      <div style={{ height: 16 }} />
      <div className="grid2">
        <Panel title="Mentions by channel"><PieChart data={d.channelDist} /></Panel>
        <Panel title="Sentiment by channel">
          <table>
            <thead><tr><th>Channel</th><th>Neutral</th><th>Positive</th><th>Negative</th><th>Mentions</th></tr></thead>
            <tbody>{d.channelTable.map((c) => (
              <tr key={platformLabel(c.platform)}><td>{platformLabel(c.platform)}</td><td className="muted">{c.neutral}</td>
                <td style={{ color: "var(--ok)" }}>{c.positive}</td><td style={{ color: "var(--high)" }}>{c.negative}</td><td><b>{c.total}</b></td></tr>
            ))}</tbody>
          </table>
        </Panel>
      </div>
      <SectionBanner n={2} title="Audience and engagement" />
      <div className="grid2">
        <Panel title="Who is talking" right={<Note>{d.categorisedAccounts} accounts · AI-classified from name &amp; content</Note>}><BarList data={d.influencerCategories} colorFor={() => STEEL} /></Panel>
        <Panel title="Engagement by post format" right={<Note>total engagement by post format</Note>}><BarList data={d.mediaTypes} colorFor={() => STEEL} /></Panel>
      </div>
      <Panel title="Word cloud"><WordCloud data={d.words} /></Panel>
    </>
  );
}

/* ================= COMPETITION ================= */
export function CompetitionReport({ mentions, sov, posts, responseTimes, onScan, scanning }: {
  mentions: Mention[]; sov: CompetitorSov | null; posts: CompetitorPost[]; responseTimes: ResponseTimes | null;
  onScan: () => void; scanning: boolean;
}) {
  const scope = useScope();
  const d = useMemo(() => competitionData(sov, mentions, posts, responseTimes), [sov, mentions, posts, responseTimes]);
  const measured = responseNote(d.responseMeasuredAt, d.responseFirstAt, d.responseMeasurements);
  const on = d.sharedChannels.length ? `on ${d.sharedChannels.map(platformLabel).join(", ")}, collected for every insurer` : "run a scan to compare insurers";
  const ownCount = d.sovOverall.find((b) => b.own)?.value ?? mentions.length;
  const total = Math.max(1, d.sovOverall.reduce((a, b) => a + b.value, 0));
  return (
    <>
      <DownloadBar label="Download Competition Report" onClick={() => downloadCompetition(d, { line: scope.line(mentions.length + posts.length), change: "", tag: scope.fileTag, measured })} sample={d.sample} scope={scope} />
      <SectionBanner n={1} title="Overview" />
      <SovSummary yourCount={ownCount} groupAvg={Math.round(total / Math.max(1, d.sovOverall.length))} sharePct={(ownCount / total) * 100} />
      <div className="grid2">
        <Panel title="Share of voice: all posts"><PieChart data={d.sovOverall.map((b) => ({ name: b.name, value: b.value }))} colorFor={brandFill} /></Panel>
        <Panel title="Share of voice: unique accounts" right={<Note>distinct accounts {on}</Note>}>{d.sovUnique.length ? <PieChart data={d.sovUnique.map((b) => ({ name: b.name, value: b.value }))} colorFor={brandFill} unit="accounts" /> : <NoComp />}</Panel>
      </div>
      <Panel title="Average reply time to comments" right={<Note>each insurer's replies to comments on its own Facebook and Instagram posts{measured ? ` · ${measured}` : ""}</Note>}>
        {d.responseTimes.length === 0 && d.noResponse.length === 0 && <div className="muted" style={{ fontSize: 13 }}>{scope.range ? "No reply time was measured in this period. It is measured by every scan." : "Not measured yet — runs with the competitor scan."}</div>}
        <HBarCompare data={d.responseTimes.map((r) => ({ name: r.name, value: r.seconds, own: isOwnBrand(r.name) }))} fmt={durfmt} colorOwn />
        {(d.responseTimes.length > 0 || d.noResponse.length > 0) && (
          <div className="muted" style={{ fontSize: 12.5, marginTop: 10, lineHeight: 1.6 }}>
            {d.responseTimes.map((r) => <div key={r.name}>{r.name}: replied to {r.replied} of {r.comments} comments{r.breakdown ? ` (${r.breakdown})` : ""}</div>)}
            {d.noResponse.length > 0 && <div>No replies found in the sampled comments: {d.noResponse.map((r) => r.breakdown ? `${r.name} (${r.breakdown})` : r.name).join(" · ")}</div>}
          </div>
        )}
      </Panel>
      <div style={{ height: 16 }} />
      <Panel title="Mentions per day by insurer" right={<Note>{d.sharedChannels.length ? on : "hover for daily values"}</Note>}>
        <MultiLineTrend {...d.brandTrend} />
      </Panel>
      <div style={{ height: 16 }} />
      <Panel title="Insurers on each channel" right={<span className="count">platforms as hubs · insurers orbit · drag &amp; hover</span>}>
        <PlatformNetwork sov={sov} mentions={mentions} />
      </Panel>
      <SectionBanner n={2} title="Engagement" />
      <div className="muted" style={{ fontSize: 12.5, margin: "-6px 0 12px" }}>Likes, comments and views of collected posts {on}.</div>
      <div className="grid2">
        <Panel title="Total engagement by insurer">{d.engagement.length ? <HBarCompare data={d.engagement.map((e) => ({ name: e.name, value: e.total, own: isOwnBrand(e.name) }))} colorOwn /> : <NoComp />}</Panel>
        <Panel title="Likes by insurer">{d.engagement.length ? <HBarCompare data={d.engagement.map((e) => ({ name: e.name, value: e.likes, own: isOwnBrand(e.name) }))} colorOwn /> : <NoComp />}</Panel>
      </div>
      <Panel title="Comments by insurer">{d.engagement.length ? <HBarCompare data={d.engagement.map((e) => ({ name: e.name, value: e.comments, own: isOwnBrand(e.name) }))} colorOwn /> : <NoComp />}</Panel>
      <div style={{ height: 16 }} />
      <Panel title="Mentions by insurer and channel">
        <table>
          <thead><tr><th>Brand</th>{[...new Set(d.channelwise.flatMap((b) => Object.keys(b.by)))].map((p) => <th key={p}>{platformLabel(p)}</th>)}</tr></thead>
          <tbody>{d.channelwise.map((b) => (
            <tr key={b.name} style={b.own ? { background: "var(--accent-soft)" } : {}}>
              <td><b>{b.name}</b></td>
              {[...new Set(d.channelwise.flatMap((x) => Object.keys(x.by)))].map((p) => <td key={p}>{b.by[p] ?? 0}</td>)}
            </tr>
          ))}</tbody>
        </table>
      </Panel>
      <SectionBanner n={3} title="Voices, words and language" />
      <Panel title="Top influencers"><VocalUsers users={d.influencers} /></Panel>
      <div style={{ height: 16 }} />
      <div className="grid2">
        <Panel title="Word cloud"><WordCloud data={d.words} /></Panel>
        <Panel title="Languages" right={<Note>% of {d.languagePosts} posts, all brands · AI-detected</Note>}><BarList data={d.language} unit="%" colorFor={() => STEEL} /></Panel>
      </div>
      <div style={{ height: 16 }} />
      <Competitors mentions={mentions} sov={sov} onScan={onScan} scanning={scanning} />
    </>
  );
}

export { platformColor };
