// Report data layer. Every figure is computed from stored data: the analysed mentions,
// the collected competitor posts, follower snapshots of the brand's own accounts, and
// measured first-level response times. Nothing is estimated or randomly generated — a
// panel with no data says so instead.
import type { CompetitorPost, CompetitorSov, FollowerSummary, Mention, ResponseTimes } from "./types";
import { channelwise, shareOfVoice, sentimentTrend, topHashtags, vocalUsers, wordCloud, platformColor } from "./analytics";
import { brandColor, NEUTRAL, OWN, POSITIVE, RED } from "./palette";
import { platformLabel } from "./labels";
import { BRAND_NAME, BRAND_SHORT } from "./brand";

const eng = (m: Mention) => Object.values(m.engagement || {}).reduce((a, b) => a + (Number(b) || 0), 0);
export const kfmt = (n: number) => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(Math.round(n));

// changePct: undefined = not applicable (hidden), null = no earlier data to compare against.
export interface ChangeStat { label: string; value: number; sharePct?: number; changePct?: number | null; }

const OWN_BRAND = BRAND_NAME;
const pct = (cur: number, prev: number, digits = 2): number | null => prev > 0 ? +(((cur - prev) / prev) * 100).toFixed(digits) : null;

/* ---------- Period-over-period change ----------
   With a date filter: the selected period vs the same number of days just before it
   (`prior`, the same filters over that earlier period). Without one: the latest PERIOD_DAYS
   of collected data vs the PERIOD_DAYS before it, anchored on the newest mention (not today),
   so a dataset collected weeks ago still compares like for like. */
export const PERIOD_DAYS = 30;
/** What the "change" figures compare, for the note next to them. */
export const changeNote = (priorDays: number | null) => priorDays
  ? `change vs the previous ${priorDays} day${priorDays === 1 ? "" : "s"}`
  : `change: last ${PERIOD_DAYS} days vs the ${PERIOD_DAYS} before`;
function periodChange(mentions: Mention[], pred: (m: Mention) => boolean = () => true, prior?: Mention[] | null): number | null {
  if (prior) return pct(mentions.filter(pred).length, prior.filter(pred).length);
  const times = mentions.map((m) => Date.parse(m.timestamp)).filter((t) => !isNaN(t));
  if (!times.length) return null;
  const end = Math.max(...times), span = PERIOD_DAYS * 86400e3;
  let cur = 0, prev = 0;
  for (const m of mentions) {
    const t = Date.parse(m.timestamp); if (isNaN(t) || !pred(m)) continue;
    if (t > end - span) cur++; else if (t > end - 2 * span) prev++;
  }
  return pct(cur, prev);
}

/* ---------------- Marketing ---------------- */
export function marketingData(mentions: Mention[], sov: CompetitorSov | null, fol: FollowerSummary | null, prior?: Mention[] | null) {
  const total = mentions.length || 1;
  const latest = fol?.latest?.counts ?? {}, prev = fol?.previous?.counts ?? null;
  const owned = Object.keys(latest);
  const fTotal = owned.reduce((a, k) => a + latest[k], 0) || 1;
  const followers: ChangeStat[] = owned.map((k) => ({
    label: k, value: latest[k], sharePct: +((latest[k] / fTotal) * 100).toFixed(2),
    changePct: prev && prev[k] !== undefined ? pct(latest[k], prev[k], 3) : null,   // follower moves are tiny
  }));
  // New followers = growth between the latest snapshot and the comparison snapshot.
  const newFollowers: ChangeStat[] = prev ? owned.filter((k) => prev[k] !== undefined).map((k) => ({ label: k, value: latest[k] - prev[k] })) : [];

  const neg = mentions.filter((m) => m.sentiment === "negative").length;
  const neu = mentions.filter((m) => m.sentiment === "neutral").length;
  const pos = mentions.filter((m) => m.sentiment === "positive").length;

  const posWords = wordCloud(mentions.filter((m) => m.sentiment === "positive"), 30);
  const negWords = wordCloud(mentions.filter((m) => m.sentiment === "negative"), 30);

  return {
    followers, newFollowers,
    followersAt: fol?.latest?.at ?? null, followersSince: fol?.previous?.at ?? null,
    sentimentSplit: [
      { label: "Total Mentions", value: mentions.length, changePct: periodChange(mentions, undefined, prior) },
      { label: "Negative", value: neg, sharePct: +((neg / total) * 100).toFixed(2), changePct: periodChange(mentions, (m) => m.sentiment === "negative", prior) },
      { label: "Neutral", value: neu, sharePct: +((neu / total) * 100).toFixed(2), changePct: periodChange(mentions, (m) => m.sentiment === "neutral", prior) },
      { label: "Positive", value: pos, sharePct: +((pos / total) * 100).toFixed(2), changePct: periodChange(mentions, (m) => m.sentiment === "positive", prior) },
    ] as ChangeStat[],
    trend: sentimentTrend(mentions),
    distribution: [{ name: "Negative", value: neg }, { name: "Neutral", value: neu }, { name: "Positive", value: pos }],
    posWords: posWords.length ? posWords : wordCloud(mentions, 30),
    negWords,
    influencers: vocalUsers(mentions).slice(0, 6),
    hashtags: topHashtags(mentions, 12),
    sov: brandSov(sov, mentions),
    sample: mentions.length === 0,
  };
}

/* ---------------- Listening ---------------- */
const AUTHOR_LABEL: Record<string, string> = {
  individual: "Individuals", creator: "Creators & Influencers", media: "Media & Journalists",
  brand: "Brands & Businesses", other: "Others",
};
const MEDIA_LABEL: Record<string, string> = { video: "Video", image: "Image", text: "Text", link: "Link" };

export function listeningData(mentions: Mention[], prior?: Mention[] | null) {
  const cw = channelwise(mentions);
  const total = mentions.length || 1;
  const days = new Set(mentions.map((m) => (m.timestamp || "").slice(0, 10))).size || 1;
  const neg = mentions.filter((m) => m.sentiment === "negative").length;
  const neu = mentions.filter((m) => m.sentiment === "neutral").length;
  const pos = mentions.filter((m) => m.sentiment === "positive").length;
  const uniqueUsers = new Set(mentions.map((m) => m.author)).size;
  const totalEng = mentions.reduce((a, m) => a + eng(m), 0);
  const outgoing = mentions.filter((m) => m.is_official).length;

  // One category per unique (non-brand-owned) account, from its most recent post.
  const byAuthor = new Map<string, Mention>();
  for (const m of mentions) {
    if (m.is_official) continue;
    const k = `${m.platform}:${m.author}`, cur = byAuthor.get(k);
    if (!cur || (m.timestamp || "") > (cur.timestamp || "")) byAuthor.set(k, m);
  }
  const cat = new Map<string, number>();
  for (const m of byAuthor.values()) { const l = AUTHOR_LABEL[m.author_type ?? ""] ?? "Unclassified"; cat.set(l, (cat.get(l) ?? 0) + 1); }
  const media = new Map<string, number>();
  for (const m of mentions) { const l = MEDIA_LABEL[m.media_type ?? ""] ?? "Unclassified"; media.set(l, (media.get(l) ?? 0) + eng(m)); }
  const sorted = (mp: Map<string, number>) => [...mp.entries()].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);

  return {
    mentionsCount: mentions.length, avgPerDay: Math.round(mentions.length / days),
    incoming: mentions.length - outgoing, outgoing,
    sentiment: [
      { label: "Negative", value: neg, sharePct: +((neg / total) * 100).toFixed(2), changePct: periodChange(mentions, (m) => m.sentiment === "negative", prior) },
      { label: "Neutral", value: neu, sharePct: +((neu / total) * 100).toFixed(2), changePct: periodChange(mentions, (m) => m.sentiment === "neutral", prior) },
      { label: "Positive", value: pos, sharePct: +((pos / total) * 100).toFixed(2), changePct: periodChange(mentions, (m) => m.sentiment === "positive", prior) },
    ] as ChangeStat[],
    uniqueUsers, totalEng,
    trend: sentimentTrend(mentions),
    channelDist: shareOfVoice(mentions),
    channelTable: cw,
    words: wordCloud(mentions, 40),
    influencerCategories: sorted(cat),
    categorisedAccounts: byAuthor.size,
    mediaTypes: sorted(media),
    sentSeries: sentimentSeries(mentions),
    sample: mentions.length === 0,
  };
}

/* ---------------- Competition ----------------
   Brand-vs-brand comparisons use only the channels competitors are collected on, so every
   brand is measured on the same platforms. */
export function sharedChannels(posts: CompetitorPost[]) { return [...new Set(posts.map((p) => p.platform))].sort(); }

function postsByBrand(sov: CompetitorSov | null, mentions: Mention[], posts: CompetitorPost[]) {
  const shared = new Set(sharedChannels(posts));
  const out = new Map<string, Mention[]>([[OWN_BRAND, mentions.filter((m) => shared.has(m.platform))]]);
  for (const name of Object.keys(sov?.competitors ?? {})) out.set(name, []);
  for (const p of posts) { if (!out.has(p.brand)) out.set(p.brand, []); out.get(p.brand)!.push(p); }
  return out;
}

export function competitionData(sov: CompetitorSov | null, mentions: Mention[], posts: CompetitorPost[], rts: ResponseTimes | null) {
  const brands = brandSov(sov, mentions);
  // No competitor posts yet -> nothing to compare (an empty panel, not a Sympany-vs-zero chart).
  const groups = posts.length ? postsByBrand(sov, mentions, posts) : new Map<string, Mention[]>();
  const num = (ms: Mention[], ...keys: string[]) => ms.reduce((a, m) => a + keys.reduce((s, k) => s + (Number(m.engagement?.[k]) || 0), 0), 0);
  const engagement = [...groups.entries()].map(([name, ms]) => ({
    name, total: ms.reduce((a, m) => a + eng(m), 0), likes: num(ms, "likes", "upvotes"), comments: num(ms, "comments"),
  })).sort((a, b) => b.total - a.total);
  const sovUnique = [...groups.entries()].map(([name, ms]) => ({ name, value: new Set(ms.map((m) => `${m.platform}:${m.author}`)).size, own: name === OWN_BRAND }));

  const rtRows = Object.entries(rts?.brands ?? {}).map(([name, r]) => ({
    name, seconds: r.avg_seconds, replyRate: r.reply_rate, replied: r.replied, comments: r.comments,
    breakdown: Object.entries(r.by_platform ?? {}).map(([p, v]) => `${platformLabel(p)} ${v.replied}/${v.comments}`).join(", "),
  }));
  const lang = new Map<string, number>();
  const all = [...mentions, ...posts];
  for (const m of all) { const l = m.language || "Unclassified"; lang.set(l, (lang.get(l) ?? 0) + 1); }
  const language = [...lang.entries()].map(([name, n]) => ({ name, value: +((n / Math.max(1, all.length)) * 100).toFixed(1) })).sort((a, b) => b.value - a.value);

  return {
    sovOverall: brands,
    sovUnique,
    sharedChannels: sharedChannels(posts),
    responseTimes: rtRows.filter((r) => r.seconds !== null).sort((a, b) => a.seconds! - b.seconds!) as { name: string; seconds: number; replyRate: number | null; replied: number; comments: number; breakdown: string }[],
    noResponse: rtRows.filter((r) => r.seconds === null),
    responseMeasuredAt: rts?.measured_at ?? null,
    responseMeasurements: rts?.measurements ?? null,
    responseFirstAt: rts?.first_measured_at ?? null,
    engagement,
    channelwise: brands.map((b) => ({ name: b.name, by: b.by_platform ?? {}, own: b.own })),
    influencers: vocalUsers(mentions).slice(0, 6),
    words: wordCloud(mentions, 40),
    language, languagePosts: all.length,
    brandTrend: brandTrendSeries(sov, mentions, posts),
    network: platformGraph(sov, mentions),
    sample: !sov || Object.keys(sov.competitors || {}).length === 0,
  };
}

// Sentiment-over-time series for the interactive multi-line chart (real days).
export function sentimentSeries(mentions: Mention[]) {
  const byDay = new Map<string, { neg: number; neu: number; pos: number }>();
  for (const m of mentions) {
    const d = (m.timestamp || m.analysed_at || "").slice(0, 10); if (!d) continue;
    const o = byDay.get(d) ?? { neg: 0, neu: 0, pos: 0 };
    o[m.sentiment === "negative" ? "neg" : m.sentiment === "positive" ? "pos" : "neu"] += 1;
    byDay.set(d, o);
  }
  const labels = [...byDay.keys()].sort();
  return {
    labels,
    series: [
      { name: "Negative", color: RED, points: labels.map((l) => byDay.get(l)!.neg) },
      { name: "Neutral", color: NEUTRAL, points: labels.map((l) => byDay.get(l)!.neu) },
      { name: "Positive", color: POSITIVE, points: labels.map((l) => byDay.get(l)!.pos) },
    ],
  };
}

// Mentions-per-day per brand. With competitor posts collected, every brand is counted on the
// shared channels; otherwise only the own brand's line is shown (all channels).
export function brandTrendSeries(sov: CompetitorSov | null, mentions: Mention[], posts: CompetitorPost[] = []) {
  const groups = posts.length ? postsByBrand(sov, mentions, posts) : new Map([[OWN_BRAND, mentions]]);
  const perBrand = [...groups.entries()].map(([name, ms]) => {
    const byDay = new Map<string, number>();
    for (const m of ms) { const d = (m.timestamp || "").slice(0, 10); if (d) byDay.set(d, (byDay.get(d) ?? 0) + 1); }
    return { name, byDay };
  });
  const labels = [...new Set(perBrand.flatMap((b) => [...b.byDay.keys()]))].sort();
  if (labels.length === 0) return { labels: [], series: [] };
  const competitors = perBrand.filter((b) => b.name !== OWN_BRAND).map((b) => b.name);
  const series = perBrand.map((b) => ({ name: b.name, color: b.name === OWN_BRAND ? OWN : brandColor(b.name, competitors.indexOf(b.name)), points: labels.map((l) => b.byDay.get(l) ?? 0) }));
  return { labels, series };
}


// Shared platform-network model (platform hubs + brand leaves) for the site + PDF.
export interface PlatformHub { platform: string; total: number; leaves: { brand: string; count: number; neg: number; neu: number; pos: number }[]; }
export function platformGraph(sov: CompetitorSov | null, mentions: Mention[]): PlatformHub[] {
  const brands: { name: string; by: Record<string, number>; neg: number; neu: number; pos: number }[] = [];
  if (sov) {
    brands.push({ name: BRAND_SHORT, by: sov.own.by_platform || {}, neg: sov.own.negative, neu: sov.own.neutral, pos: sov.own.positive });
    for (const [n, v] of Object.entries(sov.competitors)) brands.push({ name: n, by: v.by_platform || {}, neg: v.negative, neu: v.neutral, pos: v.positive });
  } else {
    const by: Record<string, number> = {}; let neg = 0, neu = 0, pos = 0;
    for (const m of mentions) { by[m.platform] = (by[m.platform] || 0) + 1; if (m.sentiment === "negative") neg++; else if (m.sentiment === "positive") pos++; else neu++; }
    brands.push({ name: BRAND_SHORT, by, neg, neu, pos });
  }
  const platforms = [...new Set(brands.flatMap((b) => Object.keys(b.by)))];
  return platforms.map((p) => {
    const total = brands.reduce((a, b) => a + (b.by[p] || 0), 0);
    const leaves = brands.filter((b) => (b.by[p] || 0) > 0).map((b) => {
      const c = b.by[p], t = Math.max(1, b.neg + b.neu + b.pos);
      return { brand: b.name, count: c, neg: Math.round(c * b.neg / t), neu: Math.round(c * b.neu / t), pos: Math.round(c * b.pos / t) };
    });
    return { platform: p, total, leaves };
  }).filter((h) => h.total > 0);
}

function brandSov(sov: CompetitorSov | null, mentions: Mention[]) {
  const out: { name: string; value: number; pct: number; own: boolean; by_platform?: Record<string, number> }[] = [];
  if (sov) {
    out.push({ name: BRAND_NAME, value: sov.own.total, pct: 0, own: true, by_platform: sov.own.by_platform });
    for (const [k, v] of Object.entries(sov.competitors)) out.push({ name: k, value: v.total, pct: 0, own: false, by_platform: v.by_platform });
  } else {
    out.push({ name: BRAND_NAME, value: mentions.length, pct: 0, own: true });
  }
  const t = Math.max(1, out.reduce((a, b) => a + b.value, 0));
  out.forEach((b) => (b.pct = +((b.value / t) * 100).toFixed(2)));
  return out.sort((a, b) => b.value - a.value);
}

export { platformColor };
