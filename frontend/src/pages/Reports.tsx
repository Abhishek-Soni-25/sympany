import type { Mention, Stats } from "../types";
import { REPORT_CSS, letterhead, reportFooter } from "../reportTheme";
import { channelwise, topics } from "../analytics";
import { safeHref } from "../safeUrl";
import { Icon } from "../components/Icon";
import { platformLabel } from "../labels";
import { useScope, type Scope } from "../filters";

const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
// The report window shares the app's origin, so only http(s) links are written into it.
const sourceLink = (url: string | null | undefined) => {
  const href = safeHref(url);
  return href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">source</a>` : "—";
};
const eng = (m: Mention) => Object.values(m.engagement || {}).reduce((a, b) => a + (Number(b) || 0), 0);
const priority = (m: Mention) =>
  m.severity === "HIGH" ? "High" : m.severity === "MEDIUM" || m.sentiment === "negative" ? "Medium" : "Low";

function buildReport(mentions: Mention[], stats: Stats, scope: Scope, pending: Mention[]): string {
  const cw = channelwise(mentions);
  const tp = topics(mentions);
  const neg = mentions.filter((m) => m.sentiment === "negative").length;
  const rows = [...mentions]
    .sort((a, b) => ({ High: 0, Medium: 1, Low: 2 }[priority(a)] - { High: 0, Medium: 1, Low: 2 }[priority(b)]) || eng(b) - eng(a))
    .map((m) => `
      <tr class="p-${priority(m).toLowerCase()}">
        <td><b>${esc(priority(m))}</b></td>
        <td>${esc(m.platform)}</td>
        <td>${esc(m.author)}</td>
        <td class="s-${esc(m.sentiment)}">${esc(m.sentiment)}</td>
        <td>${esc(m.severity)}${m.risk_category && m.risk_category !== "NONE" ? " · " + esc(m.risk_category.replace(/_/g, " ")) : ""}</td>
        <td>${eng(m).toLocaleString()}</td>
        <td>${esc(m.text.slice(0, 220))}${m.text.length > 220 ? "…" : ""}</td>
        <td>${sourceLink(m.url)}</td>
      </tr>`).join("");

  // Posts the AI has not analysed yet: listed so nothing is left out, analysed at the next scan.
  const pendingRows = pending.map((m) => `
      <tr>
        <td><b>Pending</b></td><td>${esc(m.platform)}</td><td>${esc(m.author)}</td>
        <td colspan="2">AI analysis pending</td><td>${eng(m).toLocaleString()}</td>
        <td>${esc(m.text.slice(0, 220))}${m.text.length > 220 ? "…" : ""}</td><td>${sourceLink(m.url)}</td>
      </tr>`).join("");

  const chan = cw.map((c) => `<tr><td>${esc(c.platform)}</td><td>${c.total}</td><td>${c.negative}</td><td>${c.neutral}</td><td>${c.positive}</td></tr>`).join("");
  const top = tp.slice(0, 8).map((t) => `<tr><td>${esc(t.name)}</td><td>${t.count}</td><td>${t.negative}</td><td>${t.positive}</td></tr>`).join("");
  const now = new Date();

  return `<!doctype html><html><head><meta charset="utf-8"><title>Sympany risk surveillance report ${esc(scope.fileTag)}</title>
  <style>${REPORT_CSS}</style></head><body>
  ${letterhead("ORM risk surveillance report", scope.line(mentions.length + pending.length), now)}

  <h2>Executive summary</h2>
  <p>This report covers <b>${stats.total_cases}</b> mentions of Sympany published in the period ${esc(scope.period)}, analysed across
  <b>${cw.length}</b> channel${cw.length === 1 ? "" : "s"}. Of these, <b>${stats.by_severity.HIGH ?? 0}</b> were high-severity and
  <b>${stats.by_severity.MEDIUM ?? 0}</b> medium-severity, and <b>${neg}</b> carried negative sentiment.
  Every flagged item is mapped to the RACM / KRI framework. Items below are ordered by priority (High → Low).</p>

  <div class="kpis">
    <div class="kpi"><div class="v">${stats.total_cases}</div><div class="l">Items analysed</div></div>
    <div class="kpi red"><div class="v">${stats.by_severity.HIGH ?? 0}</div><div class="l">High severity</div></div>
    <div class="kpi amber"><div class="v">${stats.by_severity.MEDIUM ?? 0}</div><div class="l">Medium severity</div></div>
    <div class="kpi"><div class="v">${neg}</div><div class="l">Negative sentiment</div></div>
  </div>

  <h2>Channel breakdown</h2>
  <table><thead><tr><th>Channel</th><th>Mentions</th><th>Negative</th><th>Neutral</th><th>Positive</th></tr></thead><tbody>${chan}</tbody></table>

  <h2>Most-talked topics</h2>
  <table><thead><tr><th>Topic</th><th>Mentions</th><th>Negative</th><th>Positive</th></tr></thead><tbody>${top}</tbody></table>

  <h2>Detailed mention log (${mentions.length + pending.length})</h2>
  <table><thead><tr><th>Priority</th><th>Channel</th><th>Author</th><th>Sentiment</th><th>Severity / Risk</th><th>Engagement</th><th>Content</th><th>Link</th></tr></thead><tbody>${rows}${pendingRows}</tbody></table>

  ${reportFooter("Public and authorised channels. Personal data pseudonymised under the Swiss FADP.")}
  </body></html>`;
}

export function Reports({ stats, mentions, pending = [] }: { stats: Stats; mentions: Mention[]; pending?: Mention[] }) {
  const cw = channelwise(mentions);
  const scope = useScope();

  const generate = () => {
    const html = buildReport(mentions, stats, scope, pending);
    const w = window.open("", "_blank");
    if (w) { w.document.write(html); w.document.close(); }
  };

  const exportCsv = () => {
    const head = ["priority", "platform", "author", "sentiment", "severity", "risk_category", "engagement", "timestamp", "url", "text", "analysis"];
    const cell = (m: Mention, k: string, isPending: boolean) =>
      k === "priority" ? (isPending ? "Pending" : priority(m)) : k === "engagement" ? eng(m)
        : k === "analysis" ? (isPending ? "pending" : "done")
        : isPending && (k === "sentiment" || k === "severity" || k === "risk_category") ? "" : (m as any)[k] ?? "";
    const rows = [...mentions.map((m) => [m, false] as const), ...pending.map((m) => [m, true] as const)].map(([m, p]) =>
      head.map((k) => `"${String(cell(m, k, p)).replace(/"/g, '""')}"`).join(","));
    const blob = new Blob([head.join(",") + "\n" + rows.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `sympany-mentions_${scope.fileTag}.csv`; a.click();
  };

  return (
    <>
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-head">
          <h3>Reports &amp; export</h3>
          <div className="filters">
            <button className="btn" onClick={generate}><Icon name="reports" size={15} /> Generate report</button>
            <button className="btn-ghost" onClick={exportCsv}><Icon name="download" size={15} /> Export CSV</button>
          </div>
        </div>
        <div className="panel-body">
          <p className="report-summary">
            <b>Generate report</b> opens a full, print-ready surveillance report — executive summary,
            channel breakdown, most-talked topics, and a detailed log of every mention with its
            <b> priority, author, engagement, sentiment and severity</b>, ordered High → Low, each linked to source.
          </p>
          <p className="report-summary muted" style={{ marginTop: 8 }}>
            The report and the CSV include the {(mentions.length + pending.length).toLocaleString()} posts matching the filters above: {scope.period} · {scope.channels} · {scope.source}.
            {pending.length > 0 && ` ${pending.length} of them are still waiting for the AI analysis and are listed as pending.`}
            {` Collection: ${scope.coverage}.`}
          </p>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h3>Channel breakdown (preview)</h3></div>
        <div className="panel-body">
          <table>
            <thead><tr><th>Channel</th><th>Mentions</th><th>Negative</th><th>Neutral</th><th>Positive</th></tr></thead>
            <tbody>{cw.map((c) => (
              <tr key={platformLabel(c.platform)}><td>{platformLabel(c.platform)}</td><td><b>{c.total}</b></td>
                <td style={{ color: "var(--high)" }}>{c.negative}</td><td className="muted">{c.neutral}</td><td style={{ color: "var(--ok)" }}>{c.positive}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </div>
    </>
  );
}
