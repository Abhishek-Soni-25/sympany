// Page filters: a date range, channels and source (Sympany's own accounts or the public). One
// filter applies to every page and to every report or CSV downloaded from it, and the
// report header states exactly what was included.
import { createContext, useContext } from "react";
import type { BrandResponseTime, CompetitorPost, CompetitorSov, CoverageNote, FollowerSummary, Mention, ResponseTimes, SovEntry } from "./types";
import { platformLabel } from "./labels";

export type DatePreset = "all" | "today" | "7d" | "30d" | "90d" | "this_month" | "last_month" | "custom";
export type Source = "all" | "official" | "public";

export interface Filters {
  preset: DatePreset;
  from: string;        // "YYYY-MM-DD", custom range only
  to: string;
  channels: string[];  // CHANNELS keys; empty = all channels
  source: Source;
}

export const DEFAULT_FILTERS: Filters = { preset: "all", from: "", to: "", channels: [], source: "all" };

export const PRESETS: { key: DatePreset; label: string }[] = [
  { key: "all", label: "All time" },
  { key: "today", label: "Today" },
  { key: "7d", label: "Last 7 days" },
  { key: "30d", label: "Last 30 days" },
  { key: "90d", label: "Last 3 months" },
  { key: "this_month", label: "This month" },
  { key: "last_month", label: "Last month" },
  { key: "custom", label: "Custom dates" },
];

// The stored platforms behind each channel choice (follower counts use the same keys).
export const CHANNELS: { key: string; label: string; platforms: string[] }[] = [
  { key: "facebook", label: "Facebook", platforms: ["facebook"] },
  { key: "instagram", label: "Instagram", platforms: ["instagram"] },
  { key: "youtube", label: "YouTube", platforms: ["youtube", "youtube_channel", "youtube_shorts"] },
  { key: "x", label: "X", platforms: ["x"] },
  { key: "quora", label: "Quora", platforms: ["quora"] },
  { key: "play_store", label: "Play Store", platforms: ["play_store"] },
  { key: "app_store", label: "App Store", platforms: ["app_store"] },
  { key: "google_maps", label: "Google Maps", platforms: ["google_maps"] },
];

export const SOURCES: { key: Source; label: string }[] = [
  { key: "all", label: "Everyone" },
  { key: "official", label: "Sympany's accounts" },
  { key: "public", label: "Other accounts" },
];

/** A day range in local time; `start` / `end` are the first and last millisecond. */
export interface Range { from: string; to: string; start: number; end: number; days: number }

const pad = (n: number) => String(n).padStart(2, "0");
export const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const dayStart = (s: string) => new Date(`${s}T00:00:00`).getTime();
const dayEnd = (s: string) => new Date(`${s}T23:59:59.999`).getTime();

function makeRange(from: string, to: string): Range | null {
  if (!from || !to) return null;
  const [a, b] = from <= to ? [from, to] : [to, from];
  const start = dayStart(a), end = dayEnd(b);
  if (isNaN(start) || isNaN(end)) return null;
  return { from: a, to: b, start, end, days: Math.round((end + 1 - start) / 86400e3) };
}

/** The dates a filter stands for, or null for "All time". */
export function resolveRange(f: Filters, today = new Date()): Range | null {
  const t = ymd(today);
  const back = (n: number) => { const d = new Date(today); d.setDate(d.getDate() - n); return ymd(d); };
  switch (f.preset) {
    case "today": return makeRange(t, t);
    case "7d": return makeRange(back(6), t);
    case "30d": return makeRange(back(29), t);
    case "90d": return makeRange(back(89), t);
    case "this_month": return makeRange(ymd(new Date(today.getFullYear(), today.getMonth(), 1)), t);
    case "last_month": return makeRange(ymd(new Date(today.getFullYear(), today.getMonth() - 1, 1)),
      ymd(new Date(today.getFullYear(), today.getMonth(), 0)));
    case "custom": return makeRange(f.from, f.to);
    default: return null;
  }
}

/** The same number of days just before `r` (for "change vs the previous period"). */
export function priorRange(r: Range): Range {
  const end = r.start - 1, start = r.start - r.days * 86400e3;
  return { from: ymd(new Date(start)), to: ymd(new Date(end)), start, end, days: r.days };
}

const inRange = (iso: string | null | undefined, r: Range) => {
  const t = iso ? Date.parse(iso) : NaN;
  return !isNaN(t) && t >= r.start && t <= r.end;
};

/** Posts matching the channel and source choices and, when given, published in `range`. */
export function applyFilters<T extends Mention>(items: T[], f: Filters, range: Range | null): T[] {
  const plats = f.channels.length ? new Set(CHANNELS.filter((c) => f.channels.includes(c.key)).flatMap((c) => c.platforms)) : null;
  return items.filter((m) =>
    (!plats || plats.has(m.platform))
    && (f.source === "all" || (f.source === "official") === !!m.is_official)
    && (!range || inRange(m.timestamp, range)));
}

/** Share of voice from the filtered posts: Sympany from its own mentions, each competitor from
 *  its collected posts. Brands listed by the server stay in the table even with no posts. */
export function shareOfVoice(mentions: Mention[], posts: CompetitorPost[], server: CompetitorSov | null): CompetitorSov | null {
  if (!server) return null;
  const blank = (): SovEntry => ({ total: 0, positive: 0, neutral: 0, negative: 0, by_platform: {} });
  const add = (e: SovEntry, m: Mention) => {
    e.total += 1;
    if (m.sentiment === "positive" || m.sentiment === "neutral" || m.sentiment === "negative") e[m.sentiment] += 1;
    e.by_platform[m.platform] = (e.by_platform[m.platform] ?? 0) + 1;
  };
  const own = blank();
  mentions.forEach((m) => add(own, m));
  const competitors: Record<string, SovEntry> = Object.fromEntries(Object.keys(server.competitors).map((k) => [k, blank()]));
  for (const p of posts) add(competitors[p.brand] ??= blank(), p);
  return { own, competitors };
}

/** Follower counts for the chosen channels. With a date range: the last count recorded by
 *  the end of the range, compared with the last count before it started (or the first one
 *  inside it), so "new followers" is the growth over the period. */
export function followersFor(fol: FollowerSummary | null, f: Filters, range: Range | null): FollowerSummary | null {
  if (!fol) return null;
  const pick = (s: FollowerSummary["latest"]) => s && f.channels.length
    ? { ...s, counts: Object.fromEntries(Object.entries(s.counts).filter(([k]) => f.channels.includes(k))) }
    : s;
  if (!range) return { ...fol, latest: pick(fol.latest), previous: pick(fol.previous) };
  const snaps = [...(fol.snapshots ?? [])].sort((a, b) => a.at.localeCompare(b.at));
  const upTo = snaps.filter((s) => Date.parse(s.at) <= range.end);
  const latest = upTo[upTo.length - 1] ?? null;
  const before = snaps.filter((s) => Date.parse(s.at) < range.start);
  const baseline = before[before.length - 1] ?? snaps.find((s) => inRange(s.at, range)) ?? null;
  return {
    latest: pick(latest),
    previous: baseline && latest && baseline.at !== latest.at ? pick(baseline) : null,
    snapshots: snaps.filter((s) => inRange(s.at, range)),
  };
}

/** Reply times measured inside the range, combined per brand: comments and replies are
 *  added up, the average is weighted by the number of replies. */
export function responseTimesFor(rt: ResponseTimes | null, range: Range | null): ResponseTimes | null {
  if (!rt || !range) return rt;
  const hist = (rt.history ?? []).filter((h) => inRange(h.measured_at, range));
  if (!hist.length) {
    return inRange(rt.measured_at, range) ? rt : { measured_at: null, brands: {}, history: [], measurements: 0 };
  }
  const brands: Record<string, BrandResponseTime> = {};
  for (const h of hist) {
    for (const [name, b] of Object.entries(h.brands)) {
      const cur = brands[name] ??= { handle: rt.brands[name]?.handle ?? "", posts: 0, comments: 0, replied: 0, reply_rate: null,
        avg_seconds: null, median_seconds: null, measured_at: h.measured_at };
      const replied = b.replied ?? 0;
      if (b.avg_seconds !== null && replied) {
        const total = (cur.avg_seconds ?? 0) * cur.replied + b.avg_seconds * replied;
        cur.avg_seconds = Math.round(total / (cur.replied + replied));
      }
      cur.comments += b.comments ?? 0;
      cur.replied += replied;
      cur.measured_at = h.measured_at;
    }
  }
  for (const b of Object.values(brands)) b.reply_rate = b.comments ? +((b.replied / b.comments) * 100).toFixed(1) : null;
  return { measured_at: hist[hist.length - 1].measured_at, brands, history: hist,
    measurements: hist.length, first_measured_at: hist[0].measured_at };
}

/* ---------- What the current view contains (page note, report header, file names) ---------- */
export interface Scope {
  filters: Filters;
  range: Range | null;
  active: boolean;             // any filter other than the defaults
  period: string;              // "1 Nov 2026 – 12 Nov 2026"
  channels: string;            // "All channels" / "Facebook, Instagram"
  source: string;
  lastScan: string | null;
  prior: Mention[] | null;     // same filters, the previous period of the same length
  pending: number;             // posts in the view still waiting for the AI analysis
  coverage: string;            // "No gaps recorded" or the channels / dates that may be incomplete
  line: (posts: number) => string;
  fileTag: string;             // "2026-11-01_to_2026-11-12"
}

const longDate = (t: number) => new Date(t).toLocaleDateString("en-CH", { day: "numeric", month: "short", year: "numeric" });
export const scanTime = (iso: string | null) => iso
  ? new Date(iso).toLocaleString("en-CH", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
  : "";

/** Gaps recorded by the scans (src/coverage.py) that overlap the period, for the chosen
 *  channels: "No gaps recorded" or e.g. "possible gaps on Instagram (1 Nov – 5 Nov)". */
export function coverageText(notes: CoverageNote[], f: Filters, start: number, end: number): string {
  const plats = f.channels.length ? new Set(CHANNELS.filter((c) => f.channels.includes(c.key)).flatMap((c) => c.platforms)) : null;
  const platformOf = (ch: string) => ch.startsWith("instagram") ? "instagram" : ch === "facebook_page" ? "facebook" : ch;
  const hits = notes.filter((n) => {
    const from = n.from ? Date.parse(n.from) : Date.parse(n.to), to = Date.parse(n.to);
    return !isNaN(to) && from <= end && to >= start && (!plats || plats.has(platformOf(n.channel)));
  });
  if (!hits.length) return "No gaps recorded";
  const day = (iso: string | null) => iso ? new Date(iso).toLocaleDateString("en-CH", { day: "numeric", month: "short" }) : "";
  const parts = [...new Map(hits.map((n) => [`${n.channel}${n.from}`, `${platformLabel(platformOf(n.channel))} (${day(n.from)} – ${day(n.to)})`])).values()];
  return `possible gaps on ${parts.join(", ")}`;
}

export function buildScope(f: Filters, range: Range | null, all: Mention[], lastScan: string | null, prior: Mention[] | null,
  pending = 0, notes: CoverageNote[] = []): Scope {
  // "All time" still states real dates: the first post collected up to today.
  const times = all.map((m) => Date.parse(m.timestamp)).filter((t) => !isNaN(t));
  const start = range ? range.start : times.length ? Math.min(...times) : Date.now();
  const end = range ? Math.min(range.end, Date.now()) : Date.now();
  const period = `${longDate(start)} – ${longDate(Math.max(start, end))}`;
  const channels = f.channels.length ? CHANNELS.filter((c) => f.channels.includes(c.key)).map((c) => c.label).join(", ") : "All channels";
  const source = f.source === "official" ? "Sympany official accounts only" : f.source === "public" ? "Public mentions only" : "Sympany official accounts and public mentions";
  const coverage = coverageText(notes, f, start, end);
  return {
    filters: f, range, active: f.preset !== "all" || f.channels.length > 0 || f.source !== "all",
    period, channels, source, lastScan, prior, pending, coverage,
    line: (posts) => [`Period: ${period}`, `Channels: ${channels}`, `Source: ${source}`, `Posts in report: ${posts.toLocaleString()}`,
      ...(pending ? [`Awaiting AI analysis: ${pending} (analysed at the next scan)`] : []),
      ...(lastScan ? [`Data up to last scan: ${scanTime(lastScan)}`] : []),
      `Collection: ${coverage}`].join(" · "),
    fileTag: `${ymd(new Date(start))}_to_${ymd(new Date(Math.max(start, end)))}`,
  };
}

export const ScopeContext = createContext<Scope>(buildScope(DEFAULT_FILTERS, null, [], null, null));
export const useScope = () => useContext(ScopeContext);

// The last filter is kept for this browser tab only.
const KEY = "sympany.filters";
export function loadFilters(): Filters {
  try {
    const v = JSON.parse(sessionStorage.getItem(KEY) || "null");
    return v && typeof v === "object" ? { ...DEFAULT_FILTERS, ...v } : DEFAULT_FILTERS;
  } catch { return DEFAULT_FILTERS; }
}
export function saveFilters(f: Filters) {
  try { sessionStorage.setItem(KEY, JSON.stringify(f)); } catch { /* storage unavailable */ }
}
