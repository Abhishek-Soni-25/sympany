import { safeHref } from "../safeUrl";
import { useEffect, useMemo, useState } from "react";
import type { CaseFile } from "../types";
import type { RuleSet, ExtractedAsset } from "@compliance/types";
import { loadActiveRuleSet, runScreening } from "@compliance/screening";
import { CategoryChip, ConfidenceBar, FailedBadge, SentimentTag, SeverityBadge, fmtTime } from "./ui";
import { useFeatures } from "../features";
import { platformLabel } from "../labels";
import { Icon } from "./Icon";

/**
 * Screen a mention's text against the live rule set. A mention is "non-compliant"
 * only when it contains actively-PROHIBITED content (guaranteed returns, specific
 * return figures, testimonials, restricted terms, …). Disclosure/register
 * requirements (e.g. A-04 metadata, A-01 risk warning) don't apply to a third
 * party's social post, so we ignore requirement-type hits here.
 */
function isCompliant(text: string, ruleSet: RuleSet): boolean {
  const asset: ExtractedAsset = {
    assetId: "m", adviserId: "", channel: "", imageText: [], transcript: "",
    captionText: text || "", frames: [], extractionStatus: "complete",
    metadata: { date: "n/a", version: "n/a" },
  };
  const active = runScreening(asset, ruleSet).verdict.activeHits;
  return active.filter((h) => h.type === "prohibition").length === 0;
}

export function CasesTable({
  cases,
  onSelect,
}: {
  cases: CaseFile[];
  onSelect: (c: CaseFile) => void;
}) {
  const [ruleSet, setRuleSet] = useState<RuleSet | null>(null);
  const { media_compliance: complianceOn } = useFeatures();

  // The Media Compliance column only appears while that module is enabled.
  useEffect(() => {
    if (!complianceOn) return;
    loadActiveRuleSet().then(setRuleSet).catch(() => setRuleSet(null));
  }, [complianceOn]);

  // Compliance status per row (recomputed when the rule set or rows change).
  const compliance = useMemo(() => {
    const map: Record<string, boolean | null> = {};
    for (const c of cases) map[c.case_id] = ruleSet ? isCompliant(c.raw_content, ruleSet) : null;
    return map;
  }, [cases, ruleSet]);

  if (cases.length === 0) {
    return (
      <div className="empty">
        No cases match the current filters.
        <br />
        Run a scan to ingest and classify content.
      </div>
    );
  }
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Risk</th>
            <th>Category</th>
            <th>Channel</th>
            <th>Sentiment</th>
            <th>Reason</th>
            <th className="num">Confidence</th>
            {complianceOn && <th>Media compliance</th>}
            <th>Analysed</th>
            <th>Post</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => {
            const compliant = compliance[c.case_id];
            return (
              <tr key={c.case_id} className={`sev-row-${c.analysis_failed ? "FAILED" : c.severity}`} onClick={() => onSelect(c)}>
                <td>{c.analysis_failed ? <FailedBadge /> : <SeverityBadge severity={c.severity} />}</td>
                <td>{c.analysis_failed ? <span className="muted">—</span> : <CategoryChip category={c.risk_category} />}</td>
                <td>{platformLabel(c.platform)}{c.rating != null && <span className="muted"> · {c.rating}★</span>}</td>
                <td><SentimentTag polarity={c.sentiment_polarity} /></td>
                <td className="rationale-cell" title={c.rationale}>{c.rationale}</td>
                <td className="num">{c.analysis_failed ? <span className="muted">—</span> : <ConfidenceBar value={c.confidence} />}</td>
                {complianceOn && <td>
                  {compliant === null ? (
                    <span className="muted">…</span>
                  ) : (
                    // Read-only status. Clicking it does nothing (and must not open the
                    // row drawer); open the row itself to see the reason + notify action.
                    <span
                      className={`mc-status-chip ${compliant ? "compliant" : "noncompliant"}`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {compliant ? "Compliant" : "Non-compliant"}
                    </span>
                  )}
                </td>}
                <td className="muted">{fmtTime(c.created_at)}</td>
                <td>
                  {c.url ? (
                    <a className="link" href={safeHref(c.url)} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                      Open post <Icon name="external" size={13} />
                    </a>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
