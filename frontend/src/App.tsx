import { useCallback, useEffect, useMemo, useState } from "react";
import { api, HttpError, type AuthMode } from "./api";
import { DEFAULT_FEATURES, FeaturesContext, type Features } from "./features";
import type { AuthorActivity, CaseFile, CompetitorPost, CompetitorSov, CoverageNote, FollowerSummary, Mention, ResponseTimes, ScanQuota, ScanStatus } from "./types";
import { ALL_CHANNELS, computeInsights, computeStats } from "./demo";
import { mentionToCase } from "./adapters";
import { Sidebar, type Page } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Login } from "./components/Login";
import { CaseDrawer } from "./components/CaseDrawer";
import { useDialog } from "./components/Dialog";
import { Overview } from "./pages/Overview";
import { Reports } from "./pages/Reports";
import {
  Influencer, CampaignAnalytics, PRDashboard, ContentPerformance, ContentSense,
  Campaign,
} from "./pages/Pages";
import { MarketingReport, ListeningReport, CompetitionReport } from "./pages/ReportPages";
import { Reviews } from "./pages/Reviews";
import { MediaCompliance } from "./pages/MediaCompliance";
import { MediaComplianceSettings } from "./pages/MediaComplianceSettings";
import { Icon } from "./components/Icon";
import { FilterBar } from "./components/FilterBar";
import {
  applyFilters, buildScope, CHANNELS, followersFor, loadFilters, priorRange, resolveRange, responseTimesFor,
  saveFilters, ScopeContext, shareOfVoice, type Filters,
} from "./filters";

const REAL_CHANNELS = ["youtube", "youtube_channel", "youtube_shorts", "facebook", "instagram", "x", "quora",
  "play_store", "app_store", "google_maps"];

const META: Record<Page, { title: string; sub: string }> = {
  pinned: { title: "Overview dashboard", sub: "AI monitoring across channels — sentiment & risk mapped to RACM / KRI." },
  listening_overview: { title: "Listening overview", sub: "Deep view of incoming mentions across all channels — volume, sentiment, audience, engagement." },
  influencer: { title: "Influencers & UGC", sub: "Top vocal users and the user-generated content driving the conversation." },
  campaign_analytics: { title: "Campaign analytics", sub: "Keyword campaign performance and reach by channel." },
  pr_dashboard: { title: "PR & Reputation", sub: "Reputation risk, negative sentiment and flagged items mapped to RACM / KRI." },
  reviews: { title: "Ratings & reviews", sub: "How customers rate the Sympany app on Play Store and App Store, and its agencies on Google Maps." },
  content_sense: { title: "Topics & themes", sub: "The topics, opinions, hashtags and word clouds in the conversation." },
  content_performance: { title: "Content performance", sub: "Engagement by channel and the top-performing posts." },
  marketing: { title: "Marketing report", sub: "Brand summary — followers, sentiment split, distribution, influencers and share of voice." },
  bench_competition: { title: "Competition benchmarking", sub: "Sympany against CSS, Helsana, SWICA and Visana: share of voice, engagement and reply times." },
  reports: { title: "Risk report & export", sub: "Generate a full priority-ranked surveillance report, or export CSV." },
  campaign: { title: "Keyword campaigns", sub: "Add your own keywords to include in every scan." },
  compliance: { title: "Media compliance", sub: "Screen adviser and marketer creatives against FINMA rules and Sympany advertising policy." },
  mc_settings: { title: "Media compliance settings", sub: "Manage the Do's and Don'ts. Add your own — they apply to every content, image and video screening." },
};

// --- URL-hash routing -------------------------------------------------------
// The current page is persisted in the URL hash (e.g. #campaign) so a browser
// refresh keeps the user on the same module instead of resetting to the overview.
const PAGES: Page[] = [
  "pinned", "listening_overview", "influencer", "campaign_analytics", "pr_dashboard", "reviews",
  "content_sense", "content_performance", "marketing", "bench_competition",
  "reports", "campaign", "compliance", "mc_settings",
];
// Media Compliance pages — only routable when features.media_compliance is on.
const COMPLIANCE_PAGES: Page[] = ["compliance", "mc_settings"];
const pagesFor = (f: Features): Page[] =>
  f.media_compliance ? PAGES : PAGES.filter((p) => !COMPLIANCE_PAGES.includes(p));
const pageFromHash = (pages: Page[] = PAGES): Page => {
  const h = window.location.hash.replace(/^#\/?/, "");
  return (pages as string[]).includes(h) ? (h as Page) : "pinned";
};

// Sign-in. "password": the app's own sign-in screen (session cookie set by /api/login).
// "alb": the load balancer signs the user in with Amazon Cognito before the page loads.
// "none": local development without sign-in.
export default function App() {
  const [authMode, setAuthMode] = useState<AuthMode | "checking">("checking");
  const [authed, setAuthed] = useState(false);
  const [features, setFeatures] = useState<Features>(DEFAULT_FEATURES);

  const checkSession = useCallback(() => {
    api.me()
      .then((u) => {
        sessionStorage.removeItem("auth_reload");
        setFeatures({ ...DEFAULT_FEATURES, ...(u.features || {}) });
        setAuthMode(u.auth_mode); setAuthed(true);
      })
      .catch((err) => {
        if (err instanceof HttpError && err.status === 401 && err.body.auth_mode === "password") {
          setAuthMode("password"); setAuthed(false); return;
        }
        // alb mode: a failed /api/me means the ALB session expired (the request was redirected
        // to the Cognito sign-in page): reload once so the load balancer signs the user in.
        if (!sessionStorage.getItem("auth_reload")) {
          sessionStorage.setItem("auth_reload", "1");
          window.location.reload();
          return;
        }
        setAuthMode("password"); setAuthed(false);
      });
  }, []);
  useEffect(() => { checkSession(); }, [checkSession]);

  // Signing out clears the session cookie on the server (and the Cognito session in alb mode).
  const logout = useCallback(() => { window.location.href = "/api/logout"; }, []);

  const [page, setPageState] = useState<Page>(() => pageFromHash());
  const [mentions, setMentions] = useState<Mention[]>([]);
  const [, setAuthors] = useState<AuthorActivity[]>([]);
  const [sov, setSov] = useState<CompetitorSov | null>(null);
  const [compPosts, setCompPosts] = useState<CompetitorPost[]>([]);
  const [followers, setFollowers] = useState<FollowerSummary | null>(null);
  const [responseTimes, setResponseTimes] = useState<ResponseTimes | null>(null);
  const [coverageNotes, setCoverageNotes] = useState<CoverageNote[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<CaseFile | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [navOpen, setNavOpen] = useState(false);

  // Navigate + persist to the URL hash so refresh/back/forward restore the page.
  const setPage = useCallback((p: Page) => {
    setPageState(p);
    if (window.location.hash.replace(/^#\/?/, "") !== p) window.location.hash = p;
  }, []);

  // Keep state in sync with browser back/forward and manual hash edits; a hidden module's
  // page (e.g. #compliance while Media Compliance is off) falls back to the overview.
  const pages = useMemo(() => pagesFor(features), [features]);
  useEffect(() => {
    const onHash = () => {
      const p = pageFromHash(pages);
      setPageState(p);
      // Normalise a bare "/" or a hidden/unknown page so the URL matches what is shown.
      if (window.location.hash.replace(/^#\/?/, "") !== p) window.location.hash = p;
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [pages]);

  // Only ever render REAL stored data — no prototype/demo fallback on load.
  const live = mentions.length > 0;

  // Page filters (date range, channels, source) apply to every page and every download.
  const [filters, setFiltersState] = useState<Filters>(loadFilters);
  const setFilters = useCallback((f: Filters) => { setFiltersState(f); saveFilters(f); }, []);
  const range = useMemo(() => resolveRange(filters), [filters]);
  const shown = useMemo(() => applyFilters(mentions, filters, range), [mentions, filters, range]);
  const shownComp = useMemo(() => applyFilters(compPosts, filters, range), [compPosts, filters, range]);
  const sovView = useMemo(() => shareOfVoice(shown, shownComp, sov), [shown, shownComp, sov]);
  const followersView = useMemo(() => followersFor(followers, filters, range), [followers, filters, range]);
  const responseView = useMemo(() => responseTimesFor(responseTimes, range), [responseTimes, range]);
  const channels = useMemo(() => {
    const all = live ? REAL_CHANNELS : ALL_CHANNELS;
    if (!filters.channels.length) return all;
    const keep = new Set(CHANNELS.filter((c) => filters.channels.includes(c.key)).flatMap((c) => c.platforms));
    return all.filter((c) => keep.has(c));
  }, [live, filters.channels]);

  // Posts whose AI analysis failed are listed (as "Failed") in the tables but left out of
  // the sentiment / risk charts until a later scan has analysed them.
  const analysed = useMemo(() => shown.filter((m) => m.analysis_status !== "failed"), [shown]);
  const failedCount = shown.length - analysed.length;
  const cases = useMemo(() => shown.map(mentionToCase), [shown]);
  const analysedCases = useMemo(() => analysed.map(mentionToCase), [analysed]);
  const stats = useMemo(() => computeStats(analysedCases), [analysedCases]);
  const insights = useMemo(() => computeInsights(analysedCases, channels), [analysedCases, channels]);

  const refresh = useCallback(async () => {
    try {
      const [m, a, s, cp, f, rt, cov] = await Promise.all([
        api.mentions(), api.authors(), api.competitors().catch(() => null),
        api.competitorMentions().catch(() => []), api.followers().catch(() => null), api.responseTimes().catch(() => null),
        api.coverage().catch(() => []),
      ]);
      setMentions(m ?? []); setAuthors(a ?? []); if (s) setSov(s);
      setCompPosts(cp ?? []); setFollowers(f); setResponseTimes(rt); setCoverageNotes(cov ?? []);
      setBanner(m && m.length ? null : "No stored mentions yet. Click “Run Scan” to ingest and analyse content.");
    } catch {
      setBanner("The data service is unreachable — please retry in a moment.");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { if (authed) refresh(); }, [refresh, authed]);

  // Another user may run the day's scan. Check the shared scan status every 5 minutes (and
  // whenever the tab becomes visible again): when a scan has finished since the last check,
  // reload the stored data. Otherwise the last scanned data simply stays on screen.
  const [lastScan, setLastScan] = useState<string | null>(null);
  const [scanRunning, setScanRunning] = useState(false);
  const [quota, setQuota] = useState<ScanQuota | null>(null);
  const applyStatus = useCallback((s: ScanStatus) => {
    setScanRunning(!!s.running);
    setLastScan(s.last_run ?? null);
    setQuota(s.quota ?? null);
  }, []);
  useEffect(() => {
    if (!authed) return;
    let known: string | null | undefined;
    const check = async () => {
      const s = await api.scanStatus().catch(() => null);
      if (!s) return;
      applyStatus(s);
      if (known !== undefined && s.last_run && s.last_run !== known) await refresh();
      known = s.last_run ?? null;
    };
    check();
    const id = window.setInterval(check, 5 * 60 * 1000);
    const onVisible = () => { if (document.visibilityState === "visible") check(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { window.clearInterval(id); document.removeEventListener("visibilitychange", onVisible); };
  }, [authed, refresh, applyStatus]);

  // A scan runs as its own task (20–40 min on AWS): poll its shared status every 10 s for up
  // to an hour, refreshing the data every 30 s while it runs.
  const waitForScan = useCallback(async (onTick: () => Promise<void>): Promise<ScanStatus | null> => {
    let last: ScanStatus | null = null;
    for (let i = 0; i < 360; i++) {
      await new Promise((r) => setTimeout(r, 10000));
      const s = await api.scanStatus().catch(() => null);
      if (i % 3 === 2) await onTick();
      if (s) { applyStatus(s); last = s; }
      if (s && !s.running) break;
    }
    return last;
  }, [applyStatus]);

  // Run Scan: the site's own confirmation and messages (no browser pop-ups).
  const { confirm, notify, toast } = useDialog();
  const runScan = useCallback(async () => {
    const ok = await confirm({
      title: "Run today's scan?",
      body: (
        <>
          <p>The scan collects everything published since the last scan (Sympany's posts, competitors and followers), analyses it, and e-mails the summary when it finishes.</p>
          <p>It usually takes 15 to 30 minutes. You can run one scan a day.</p>
        </>
      ),
      confirmLabel: "Run scan",
    });
    if (!ok) return;
    setLoading(true);
    try {
      const r = await api.startScan();
      if (!r.started) {
        const reason = r.reason || r.detail || "";
        if (reason.includes("already been run")) {
          const s = await api.scanStatus().catch(() => null);
          const q = s?.quota;
          const at = q?.last_ok_at ? new Date(q.last_ok_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : null;
          await notify({ title: "Today's scan is done", body: <p>{at ? `It was run at ${at}${q?.last_by ? ` by ${q.last_by}` : ""}. ` : ""}You can run the next scan tomorrow.</p> });
        } else if (reason.includes("already running")) {
          await notify({ title: "A scan is already running", body: <p>The dashboard updates by itself when it finishes.</p> });
        } else {
          await notify({ title: "The scan couldn't start", tone: "warning", body: <p>{reason ? `${reason[0].toUpperCase()}${reason.slice(1)}. ` : ""}Try again in a few minutes.</p> });
        }
        return;
      }
      toast("Scan started. The dashboard updates by itself when it finishes.");
      const end = await waitForScan(refresh);
      if (end?.error) toast("The scan didn't finish. You can run it again; a scan that fails doesn't use up the day.", "error");
      else if (end && !end.running) toast("Scan finished. The dashboard is up to date and the summary e-mail is on its way.", "success");
    } catch { /* ignore */ } finally { setLoading(false); await refresh(); }
  }, [refresh, waitForScan, confirm, notify, toast]);

  const meta = META[page];
  const sel = setSelected;
  // The same filters over the period just before the selected one ("change vs previous period").
  const prior = useMemo(() => range
    ? applyFilters(mentions, filters, priorRange(range)).filter((m) => m.analysis_status !== "failed") : null,
  [mentions, filters, range]);
  const scope = useMemo(() => buildScope(filters, range, analysed, lastScan, prior, failedCount, coverageNotes),
    [filters, range, analysed, lastScan, prior, failedCount, coverageNotes]);
  const filterable = page !== "campaign" && page !== "compliance" && page !== "mc_settings";

  // Gate the whole console behind sign-in (after all hooks are declared).
  if (authMode === "checking") return <div className="app-loading"><span className="spinner" /> Signing in…</div>;
  if (!authed) return <Login onSuccess={checkSession} />;

  return (
    <FeaturesContext.Provider value={features}>
    <div className={`shell${navOpen ? " nav-open" : ""}`}>
      <Sidebar active={page} showCompliance={features.media_compliance} onNav={(p) => { setPage(p); setNavOpen(false); }} />
      {navOpen && <div className="nav-scrim" onClick={() => setNavOpen(false)} />}
      <div className="content">
        <TopBar title={meta.title} subtitle={meta.sub} count={mentions.length} running={loading || scanRunning} lastScan={lastScan} quota={quota} live={live} onScan={runScan} onLogout={authMode === "none" ? undefined : logout} onMenu={() => setNavOpen((o) => !o)} />
        {filterable && live && <FilterBar filters={filters} onChange={setFilters} shown={analysed.length} total={mentions.length} period={scope.period} />}
        <ScopeContext.Provider value={scope}>
        <main className="page">
          {!loaded ? (
            <div className="app-loading">
              <span className="spinner" /> Loading stored data…
            </div>
          ) : (
          <>
          {banner && <div className="banner banner-info"><Icon name="info" /> {banner}</div>}
          {failedCount > 0 && (
            <div className="banner banner-info">
              <Icon name="alert" /> {failedCount} post{failedCount > 1 ? "s" : ""} could not be analysed by the AI service and
              {failedCount > 1 ? " are" : " is"} marked “Failed”. {failedCount > 1 ? "They are" : "It is"} retried automatically on the next scan.
            </div>
          )}

          {page === "pinned" && <Overview stats={stats} insights={insights} mentions={analysed} cases={cases} onSelect={sel} />}
          {page === "listening_overview" && <ListeningReport mentions={analysed} />}
          {page === "influencer" && <Influencer mentions={analysed} />}
          {page === "campaign_analytics" && <CampaignAnalytics mentions={analysed} />}
          {page === "pr_dashboard" && <PRDashboard mentions={analysed} cases={cases} stats={stats} onSelect={sel} />}
          {page === "content_sense" && <ContentSense mentions={analysed} sov={sovView} posts={shownComp.filter((p) => p.analysis_status !== "failed")} />}
          {page === "content_performance" && <ContentPerformance mentions={analysed} />}
          {page === "reviews" && <Reviews mentions={analysed} competitors={shownComp.filter((p) => p.analysis_status !== "failed")} />}
          {page === "marketing" && <MarketingReport mentions={analysed} sov={sovView} followers={followersView} />}
          {page === "bench_competition" && <CompetitionReport mentions={analysed} sov={sovView} posts={shownComp.filter((p) => p.analysis_status !== "failed")} responseTimes={responseView} onScan={runScan} scanning={loading || scanRunning} />}
          {page === "reports" && <Reports stats={stats} mentions={analysed} pending={shown.filter((m) => m.analysis_status === "failed")} />}
          {page === "campaign" && <Campaign />}
          {features.media_compliance && page === "compliance" && <MediaCompliance />}
          {features.media_compliance && page === "mc_settings" && <MediaComplianceSettings />}

          <div className="footnote">
            Monitors public and legally authorised channels only. Personal data is pseudonymised under the Swiss FADP and the GDPR.
            Shows the data from the last scan. Run Scan collects new posts, once a day.
          </div>
          </>
          )}
        </main>
        </ScopeContext.Provider>
      </div>
      {selected && <CaseDrawer c={selected} onClose={() => setSelected(null)} />}
    </div>
    </FeaturesContext.Provider>
  );
}
