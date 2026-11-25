import { useCallback, useMemo, useState } from "react";
import type { CaseFile, Mention, Stats } from "../types";
import type { Insights as InsightsData } from "../demo";
import { StatCards, type StatKey } from "../components/StatCards";
import { Insights, type InsightPick } from "../components/Insights";
import { SentimentByPlatform } from "../components/SentimentByPlatform";
import { BarList } from "../components/Charts";
import { StackedTrend } from "../components/ReportViz";
import { engagementByPlatform, sentimentTrend } from "../analytics";
import { CasesTable } from "../components/CasesTable";
import { ResultsDrawer, type ResultsQuery } from "../components/ResultsDrawer";
import { categoryLabel, platformLabel } from "../labels";
import { Icon } from "../components/Icon";

const isAlert = (c: CaseFile) => c.severity === "HIGH" || c.severity === "MEDIUM";
const sentOf = (c: CaseFile) => c.sentiment_polarity.toLowerCase();

export function Overview({
  stats, insights, mentions, cases, onSelect,
}: {
  stats: Stats; insights: InsightsData; mentions: Mention[];
  cases: CaseFile[]; onSelect: (c: CaseFile) => void;
}) {
  // Every number on this page opens the posts it counts (analysed posts only, like the charts).
  const analysed = useMemo(() => cases.filter((c) => !c.analysis_failed), [cases]);
  const [results, setResults] = useState<ResultsQuery | null>(null);
  const show = useCallback((title: string, keep: (c: CaseFile) => boolean) =>
    setResults({ title, cases: analysed.filter(keep) }), [analysed]);
  const closeResults = useCallback(() => setResults(null), []);

  const pickStat = (k: StatKey) => {
    if (k === "all") show("All analysed posts", () => true);
    else if (k === "norisk") show("Posts with no risk", (c) => c.severity === "NONE" || c.severity === "LOW");
    else show(`${k === "HIGH" ? "High" : "Medium"} severity posts`, (c) => c.severity === k);
  };
  const pickInsight = (p: InsightPick) => {
    if (p.kind === "alerts") show("Posts flagged as a risk", isAlert);
    else if (p.kind === "sentiment") show(`${p.value[0].toUpperCase()}${p.value.slice(1)} posts`, (c) => sentOf(c) === p.value);
    else if (p.kind === "category") show(`${categoryLabel(p.value)} alerts`, (c) => c.risk_category === p.value);
    else if (p.alertsOnly) show(`Alerts on ${platformLabel(p.value)}`, (c) => c.platform === p.value && isAlert(c));
    else show(`${platformLabel(p.value)} posts`, (c) => c.platform === p.value);
  };
  const pickPlatform = (platform: string) => show(`${platformLabel(platform)} posts`, (c) => c.platform === platform);

  return (
    <>
      {(stats.by_severity.HIGH ?? 0) > 0 && (
        <div className="banner banner-error">
          <Icon name="alert" /> {stats.by_severity.HIGH} high-severity alert{(stats.by_severity.HIGH ?? 0) > 1 ? "s" : ""} on
          negative or abusive content about Sympany need review now.{" "}
          <button type="button" className="link-btn" onClick={() => pickStat("HIGH")}>Show them</button>
        </div>
      )}
      <StatCards stats={stats} onPick={pickStat} />
      <Insights d={insights} onPick={pickInsight} />
      <div className="grid2">
        <SentimentByPlatform mentions={mentions} onPick={pickPlatform} />
        <div className="panel">
          <div className="panel-head"><h3>Engagement by channel</h3></div>
          <div className="panel-body">
            <BarList data={engagementByPlatform(mentions)} labelFor={platformLabel} onPick={pickPlatform} />
          </div>
        </div>
      </div>
      <div className="panel" style={{ marginBottom: 22 }}>
        <div className="panel-head"><h3>Sentiment trend over time</h3><span className="count">daily mentions stacked by sentiment · hover for the breakdown</span></div>
        <div className="panel-body"><StackedTrend data={sentimentTrend(mentions)} /></div>
      </div>
      <div className="panel">
        <div className="panel-head">
          <h3>Latest analysed content</h3>
          <span className="count">
            {cases.length} posts. Click a row for details.{" "}
            <button type="button" className="link-btn" onClick={() => setResults({ title: "All posts", cases })}>Show all</button>
          </span>
        </div>
        <CasesTable cases={cases.slice(0, 12)} onSelect={onSelect} />
      </div>
      {results && <ResultsDrawer q={results} onSelect={onSelect} onClose={closeResults} />}
    </>
  );
}
