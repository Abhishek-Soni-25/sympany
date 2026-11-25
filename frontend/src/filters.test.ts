import { describe, expect, it } from "vitest";
import {
  applyFilters, buildScope, coverageText, DEFAULT_FILTERS, followersFor, priorRange, resolveRange, responseTimesFor, shareOfVoice,
  type Filters,
} from "./filters";
import type { CompetitorPost, FollowerSummary, Mention, ResponseTimes } from "./types";

const post = (platform: string, timestamp: string, extra: Partial<Mention> = {}): Mention => ({
  id: `${platform}-${timestamp}`, platform, provider: null, author: "a", author_url: null, url: null, text: "t",
  keyword: null, engagement: {}, sentiment: "neutral", risk_category: "NONE", severity: "NONE", confidence: 1,
  rationale: "", indicators: [], timestamp, analysed_at: timestamp, ...extra,
});
const f = (patch: Partial<Filters>): Filters => ({ ...DEFAULT_FILTERS, ...patch });
const TODAY = new Date(2026, 10, 12, 15, 0);   // 12 Nov 2026, local time

describe("resolveRange", () => {
  it("is null for all time", () => expect(resolveRange(DEFAULT_FILTERS, TODAY)).toBeNull());
  it("covers whole days for the presets", () => {
    expect(resolveRange(f({ preset: "today" }), TODAY)).toMatchObject({ from: "2026-11-12", to: "2026-11-12", days: 1 });
    expect(resolveRange(f({ preset: "7d" }), TODAY)).toMatchObject({ from: "2026-11-06", to: "2026-11-12", days: 7 });
    expect(resolveRange(f({ preset: "90d" }), TODAY)).toMatchObject({ from: "2026-08-15", to: "2026-11-12", days: 90 });
    expect(resolveRange(f({ preset: "this_month" }), TODAY)).toMatchObject({ from: "2026-11-01", to: "2026-11-12", days: 12 });
    expect(resolveRange(f({ preset: "last_month" }), TODAY)).toMatchObject({ from: "2026-10-01", to: "2026-10-31", days: 31 });
  });
  it("orders custom dates and ignores an incomplete range", () => {
    expect(resolveRange(f({ preset: "custom", from: "2026-11-05", to: "2026-11-01" }), TODAY)).toMatchObject({ from: "2026-11-01", to: "2026-11-05" });
    expect(resolveRange(f({ preset: "custom", from: "2026-11-05", to: "" }), TODAY)).toBeNull();
  });
  it("gives the previous period of the same length", () => {
    const r = resolveRange(f({ preset: "this_month" }), TODAY)!;
    expect(priorRange(r)).toMatchObject({ from: "2026-10-20", to: "2026-10-31", days: 12 });
  });
});

describe("applyFilters", () => {
  const posts = [
    post("facebook", "2026-11-02T10:00:00", { is_official: true }),
    post("instagram", "2026-11-12T23:30:00"),
    post("youtube_shorts", "2026-10-31T23:59:00", { is_official: true }),
    post("quora", "not a date"),
  ];
  const nov = resolveRange(f({ preset: "this_month" }), TODAY);
  it("keeps posts published inside the range, last day included", () =>
    expect(applyFilters(posts, f({}), nov).map((p) => p.platform)).toEqual(["facebook", "instagram"]));
  it("filters by channel, YouTube covering all its feeds", () =>
    expect(applyFilters(posts, f({ channels: ["youtube", "quora"] }), null).map((p) => p.platform)).toEqual(["youtube_shorts", "quora"]));
  it("filters by source", () => {
    expect(applyFilters(posts, f({ source: "official" }), null)).toHaveLength(2);
    expect(applyFilters(posts, f({ source: "public" }), null).map((p) => p.platform)).toEqual(["instagram", "quora"]);
  });
});

describe("shareOfVoice", () => {
  it("counts the filtered posts and keeps every competitor", () => {
    const comp = [{ ...post("facebook", "2026-11-03T00:00:00", { sentiment: "negative" }), brand: "CSS" }] as CompetitorPost[];
    const sov = shareOfVoice([post("facebook", "2026-11-02T00:00:00", { sentiment: "positive" })], comp,
      { own: { total: 9, positive: 0, neutral: 0, negative: 0, by_platform: {} }, competitors: { CSS: {} as never, Helsana: {} as never } })!;
    expect(sov.own).toMatchObject({ total: 1, positive: 1 });
    expect(sov.competitors.CSS).toMatchObject({ total: 1, negative: 1, by_platform: { facebook: 1 } });
    expect(sov.competitors.Helsana.total).toBe(0);
  });
});

describe("followersFor", () => {
  const fol: FollowerSummary = {
    latest: null, previous: null,
    snapshots: [
      { at: "2026-10-30T06:00:00Z", counts: { instagram: 100, facebook: 500 } },
      { at: "2026-11-05T06:00:00Z", counts: { instagram: 110, facebook: 490 } },
      { at: "2026-11-12T06:00:00Z", counts: { instagram: 125, facebook: 495 } },
    ],
  };
  it("measures growth from the last count before the period to the last one in it", () => {
    const r = followersFor(fol, f({ channels: ["instagram"] }), resolveRange(f({ preset: "custom", from: "2026-11-01", to: "2026-11-06" }), TODAY))!;
    expect(r.previous?.counts).toEqual({ instagram: 100 });
    expect(r.latest?.counts).toEqual({ instagram: 110 });
  });
});

describe("responseTimesFor", () => {
  const rt: ResponseTimes = {
    measured_at: "2026-11-12T06:00:00Z",
    brands: { Visana: { handle: "visana.versicherungen", posts: 5, comments: 10, replied: 5, reply_rate: 50, avg_seconds: 999, median_seconds: 1, measured_at: "" } },
    history: [
      { measured_at: "2026-10-20T06:00:00Z", brands: { Visana: { comments: 10, replied: 2, reply_rate: 20, avg_seconds: 100, median_seconds: 100 } } },
      { measured_at: "2026-11-02T06:00:00Z", brands: { Visana: { comments: 10, replied: 1, reply_rate: 10, avg_seconds: 600, median_seconds: 600 } } },
      { measured_at: "2026-11-10T06:00:00Z", brands: { Visana: { comments: 10, replied: 3, reply_rate: 30, avg_seconds: 200, median_seconds: 200 } } },
    ],
  };
  it("combines the measurements of the period, weighted by replies", () => {
    const r = responseTimesFor(rt, resolveRange(f({ preset: "this_month" }), TODAY))!;
    expect(r.measurements).toBe(2);
    expect(r.brands.Visana).toMatchObject({ comments: 20, replied: 4, reply_rate: 20, avg_seconds: 300, handle: "visana.versicherungen" });
  });
  it("is empty for a period without measurements", () => {
    const r = responseTimesFor(rt, resolveRange(f({ preset: "custom", from: "2026-09-01", to: "2026-09-30" }), TODAY))!;
    expect(r.brands).toEqual({});
  });
});

describe("buildScope", () => {
  it("states the period, channels, source, post count and last scan", () => {
    const r = resolveRange(f({ preset: "custom", from: "2026-11-01", to: "2026-11-05" }), TODAY);
    const s = buildScope(f({ preset: "custom", from: "2026-11-01", to: "2026-11-05", channels: ["instagram"], source: "official" }), r, [], "2026-11-12T04:45:00Z", null);
    expect(s.active).toBe(true);
    expect(s.fileTag).toBe("2026-11-01_to_2026-11-05");
    const line = s.line(84);
    expect(line).toContain("Period: 1 Nov 2026 – 5 Nov 2026");
    expect(line).toContain("Channels: Instagram");
    expect(line).toContain("Source: Sympany official accounts only");
    expect(line).toContain("Posts in report: 84");
    expect(line).toContain("Data up to last scan:");
  });
  it("uses the first collected post as the start of all time", () => {
    const s = buildScope(DEFAULT_FILTERS, null, [post("facebook", "2026-05-10T08:00:00")], null, null);
    expect(s.period.startsWith("10 May 2026 – ")).toBe(true);
    expect(s.active).toBe(false);
  });
});

describe("coverageText", () => {
  const notes = [{ channel: "instagram_tagged", from: "2026-11-01", to: "2026-11-05T06:00:00Z", at: "2026-11-05T06:00:00Z", note: "x" }];
  const nov = resolveRange(f({ preset: "this_month" }), TODAY)!;
  const oct = resolveRange(f({ preset: "last_month" }), TODAY)!;
  it("names the channel and dates of a gap inside the period", () =>
    expect(coverageText(notes, f({}), nov.start, nov.end)).toMatch(/^possible gaps on Instagram \(1 Nov – 5 Nov\)$/));
  it("is clean for another period or another channel", () => {
    expect(coverageText(notes, f({}), oct.start, oct.end)).toBe("No gaps recorded");
    expect(coverageText(notes, f({ channels: ["facebook"] }), nov.start, nov.end)).toBe("No gaps recorded");
  });
  it("is stated in the report line with the posts awaiting analysis", () => {
    const line = buildScope(f({ preset: "this_month" }), nov, [], null, null, 3, notes).line(10);
    expect(line).toContain("Awaiting AI analysis: 3");
    expect(line).toContain("Collection: possible gaps on Instagram");
  });
});
