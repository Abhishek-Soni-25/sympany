// Print-ready HTML report generators — mirror the on-screen sections, with REAL embedded
// charts (donuts, area/line, colourful word cloud). window.print() → PDF.
import { kfmt } from "./reportData";
import { REPORT_CSS, letterhead, reportFooter, SY_BERRY, SY_RED, SY_GREEN } from "./reportTheme";
import { svgPie, svgArea, svgMultiLine, wordCloudHtml, svgPlatformNetwork } from "./reportCharts";
import { isOwnBrand } from "./brand";

// What the report contains (the page filters), shown under the title; `tag` (the dates)
// names the saved PDF. `change` says what the change figures compare.
export interface ReportScope { line: string; change: string; tag: string; measured?: string }

// Brand lines: Sympany berry for Sympany, then one colour per competitor (lavender first, then
// sand-brown / amber / slate so four competitors stay apart on a line chart).
const REPORT_BRANDS = ["#4E4385", "#A0724F", "#A35200", "#5C5160", "#A79DCF"];
const reportSeries = (series: { name: string; color: string; points: number[] }[]) => {
  let i = 0;
  return series.map((s) => ({ ...s, color: isOwnBrand(s.name) ? SY_BERRY : REPORT_BRANDS[i++ % REPORT_BRANDS.length] }));
};

const sentColor = (n: string) => n === "negative" || n === "Negative" ? SY_RED : n === "positive" || n === "Positive" ? SY_GREEN : "#B3AAA4";
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const arrow = (v: number | null) => v === null ? `<span style="color:#7A7075">— no prior data</span>` : v === 0 ? `<span style="color:#7A7075">● no change</span>` : `<span style="color:${v >= 0 ? SY_GREEN : SY_RED}">${v >= 0 ? "▲" : "▼"} ${Math.abs(v)}%</span>`;
const note = (s: string) => `<p style="color:#5E5559;font-size:12px;margin:-4px 0 8px">${esc(s)}</p>`;
const when = (iso: string | null) => iso ? new Date(iso).toLocaleString("en-CH", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const day = (iso: string | null) => iso ? new Date(iso).toLocaleDateString("en-CH", { day: "numeric", month: "short", year: "numeric" }) : "";

const shell = (title: string, body: string, h: ReportScope) => `<!doctype html><html><head><meta charset="utf-8"><title>${esc(`Sympany ${title} ${h.tag}`)}</title>
<style>${REPORT_CSS}</style></head><body>
${letterhead(title, h.line)}
${body}
${reportFooter("Public and authorised channels · PII pseudonymised · Swiss FADP. Figures are computed from collected posts, follower snapshots and measured replies.")}
</body></html>`;

const cards = (items: { l: string; v: string; c?: number | null }[]) =>
  `<div class="cards">${items.map((i) => `<div class="card"><div class="l">${esc(i.l)}</div><div class="v">${esc(i.v)}</div>${i.c !== undefined ? arrow(i.c) : ""}</div>`).join("")}</div>`;
const barTable = (rows: { name: string; value: number }[], unit = "") => {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return `<table><tbody>${rows.map((r) => `<tr><td style="width:180px">${esc(r.name)}</td><td><div class="bar"><span style="width:${(r.value / max) * 100}%"></span></div></td><td style="width:90px;text-align:right;font-weight:700">${r.value.toLocaleString()}${unit}</td></tr>`).join("")}</tbody></table>`;
};
const open = (html: string) => { const w = window.open("", "_blank"); if (w) { w.document.write(html); w.document.close(); } };

export function downloadMarketing(d: ReturnType<typeof import("./reportData").marketingData>, h: ReportScope) {
  const body = `
  <h2>Section 1 · Overall Brand Summary</h2>
  <h3>Channel-Wise Follower Count</h3>${d.followers.length ? note(`Sympany's own accounts · public counts as of ${day(d.followersAt)}`) + cards(d.followers.map((f) => ({ l: f.label, v: `${kfmt(f.value)} · ${f.sharePct}%`, c: f.changePct }))) : note("No follower snapshot recorded yet.")}
  <h3>Channel-Wise New Page Followers</h3>${d.newFollowers.length ? note(`Growth from ${when(d.followersSince)} to ${when(d.followersAt)}`) + cards(d.newFollowers.map((f) => ({ l: f.label, v: (f.value < 0 ? "−" : "+") + kfmt(Math.abs(f.value)) }))) : note("Needs two follower snapshots at least an hour apart.")}
  <h3>Total Mentions &amp; Sentiment Split</h3>${note(`${h.change[0].toUpperCase()}${h.change.slice(1)}.`)}${cards(d.sentimentSplit.map((s) => ({ l: s.label, v: `${kfmt(s.value)}${s.sharePct !== undefined ? " · " + s.sharePct + "%" : ""}`, c: s.changePct })))}
  <h3>Mentions Trend</h3>${svgArea(d.trend)}
  <h3>Mentions Distribution</h3>${svgPie(d.distribution, sentColor)}
  <h2>Section 2 · Voice &amp; Influencers</h2>
  <h3>Positive Word Cloud</h3>${wordCloudHtml(d.posWords)}
  <h3>Negative Word Cloud</h3>${wordCloudHtml(d.negWords)}
  <h3>Top Influencers</h3><table><thead><tr><th>Account</th><th>Platform</th><th>Posts</th><th>Engagement</th></tr></thead><tbody>${d.influencers.map((u) => `<tr><td>${esc(u.author)}</td><td>${esc(u.platform)}</td><td>${u.posts}</td><td>${u.engagement.toLocaleString()}</td></tr>`).join("")}</tbody></table>
  <h3>Top Hashtags</h3>${barTable(d.hashtags.map((h) => ({ name: h.name, value: h.value })))}
  <h2>Section 3 · Share of Voice</h2>${barTable(d.sov.map((b) => ({ name: b.name, value: b.value })))}`;
  open(shell("Marketing Report", body, h));
}

export function downloadListening(d: ReturnType<typeof import("./reportData").listeningData>, h: ReportScope) {
  const body = `
  <h2>Section 1 · Mentions Overview</h2>
  ${cards([{ l: "Mentions Count", v: kfmt(d.mentionsCount) }, { l: "Average Mentions/Day", v: String(d.avgPerDay) }, { l: "Incoming", v: kfmt(d.incoming) }, { l: "Outgoing", v: kfmt(d.outgoing) }, { l: "Unique Users", v: kfmt(d.uniqueUsers) }])}
  <h3>Sentiment Distribution</h3>${note(`${h.change[0].toUpperCase()}${h.change.slice(1)}.`)}${cards(d.sentiment.map((s) => ({ l: s.label, v: `${kfmt(s.value)} · ${s.sharePct}%`, c: s.changePct })))}
  <h3>Mentions Trend with Engagement</h3>${svgMultiLine(d.sentSeries.series, d.sentSeries.labels)}
  <div style="display:flex;gap:20px;flex-wrap:wrap"><div style="flex:1;min-width:320px"><h3>Channel-Wise Distribution</h3>${svgPie(d.channelDist)}</div>
  <div style="flex:1;min-width:320px"><h3>Channel-Wise Sentiment</h3><table><thead><tr><th>Channel</th><th>Neu</th><th>Pos</th><th>Neg</th><th>Total</th></tr></thead><tbody>${d.channelTable.map((c) => `<tr><td>${esc(c.platform)}</td><td>${c.neutral}</td><td>${c.positive}</td><td>${c.negative}</td><td><b>${c.total}</b></td></tr>`).join("")}</tbody></table></div></div>
  <h2>Section 2 · Audience &amp; Engagement</h2>
  <h3>Influencer Categories</h3>${note(`${d.categorisedAccounts} accounts, AI-classified from account name and content.`)}${barTable(d.influencerCategories)}
  <h3>Media Type by Engagement</h3>${note("Total engagement by post format.")}${barTable(d.mediaTypes)}
  <h3>Word Cloud</h3>${wordCloudHtml(d.words)}`;
  open(shell("Listening Overview", body, h));
}

export function downloadCompetition(d: ReturnType<typeof import("./reportData").competitionData>, h: ReportScope) {
  const on = d.sharedChannels.length ? `Measured on ${d.sharedChannels.join(" + ")} — the same channels for every brand.` : "No competitor posts collected yet.";
  const rt = d.responseTimes.length || d.noResponse.length
    ? note(`Brand replies to comments on its own Facebook & Instagram posts${h.measured ? ` · ${h.measured}` : ` · measured ${day(d.responseMeasuredAt)}`}.`)
      + barTable(d.responseTimes.map((r) => ({ name: r.name, value: Math.round(r.seconds / 60) })), " min")
      + (d.noResponse.length ? note(`No replies found in the sampled comments: ${d.noResponse.map((r) => r.name).join(", ")}.`) : "")
    : note("Not measured yet.");
  const body = `
  <h2>Section 1 · Overview Summary</h2>
  <div style="display:flex;gap:20px;flex-wrap:wrap"><div style="flex:1;min-width:320px"><h3>Share of Voice — Overall</h3>${svgPie(d.sovOverall.map((b) => ({ name: b.name, value: b.value })))}</div>
  <div style="flex:1;min-width:320px"><h3>Share of Voice — Unique Users</h3>${note(`Distinct accounts. ${on}`)}${svgPie(d.sovUnique.map((b) => ({ name: b.name, value: b.value })))}</div></div>
  <h3>Mentions Trend by Brand</h3>${note(on)}${svgMultiLine(reportSeries(d.brandTrend.series), d.brandTrend.labels)}
  <h3>Avg First-Level Response Time</h3>${rt}
  <h3>Channel × Brand Network</h3><p style="color:#5E5559;font-size:12px">Platforms as hubs; brands orbit each hub, sized by mentions, ringed by sentiment.</p>${svgPlatformNetwork(d.network)}
  <h3>Channel × Brand — mentions by platform</h3>${(() => {
    const plats = [...new Set(d.channelwise.flatMap((b) => Object.keys(b.by)))];
    return `<table><thead><tr><th>Brand</th>${plats.map((p) => `<th>${esc(p)}</th>`).join("")}</tr></thead><tbody>${d.channelwise.map((b) => `<tr><td><b>${esc(b.name)}</b></td>${plats.map((p) => `<td>${b.by[p] ?? 0}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  })()}
  <h2>Section 2 · Engagement Analysis</h2>${note(on)}
  <h3>Total Engagement by Brand</h3>${barTable(d.engagement.map((e) => ({ name: e.name, value: e.total })))}
  <div style="display:flex;gap:20px;flex-wrap:wrap"><div style="flex:1;min-width:320px"><h3>Likes by Brand</h3>${barTable(d.engagement.map((e) => ({ name: e.name, value: e.likes })))}</div>
  <div style="flex:1;min-width:320px"><h3>Comments by Brand</h3>${barTable(d.engagement.map((e) => ({ name: e.name, value: e.comments })))}</div></div>
  <h2>Section 3 · Word Clouds &amp; Language</h2>
  <h3>Word Cloud</h3>${wordCloudHtml(d.words)}
  <h3>Language Distribution</h3>${note(`% of ${d.languagePosts} posts across all brands, AI-detected.`)}${barTable(d.language, "%")}`;
  open(shell("Competition Benchmarking", body, h));
}
