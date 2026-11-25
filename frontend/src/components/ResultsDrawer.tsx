import { useEffect, useRef } from "react";
import type { CaseFile } from "../types";
import { CasesTable } from "./CasesTable";

// The posts behind a clicked number: a wide panel with a one-line summary and the same
// posts table as the overview. A row opens the post detail on top of it.

const SEV_RANK: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2, NONE: 3 };

export interface ResultsQuery {
  title: string;
  cases: CaseFile[];
}

export function ResultsDrawer({ q, onSelect, onClose }: {
  q: ResultsQuery; onSelect: (c: CaseFile) => void; onClose: () => void;
}) {
  const closeBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeBtn.current?.focus();
    // Esc closes this panel, unless a post detail is open on top of it.
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.querySelector(".drawer:not(.results-drawer)")) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = [...q.cases].sort((a, b) =>
    (SEV_RANK[a.severity] ?? 4) - (SEV_RANK[b.severity] ?? 4) || (b.timestamp || "").localeCompare(a.timestamp || ""));
  const neg = rows.filter((c) => c.sentiment_polarity.toLowerCase().startsWith("neg")).length;
  const pos = rows.filter((c) => c.sentiment_polarity.toLowerCase().startsWith("pos")).length;
  const newest = rows.reduce((d, c) => (c.timestamp > d ? c.timestamp : d), "");
  const newestTxt = newest ? new Date(newest).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : null;

  return (
    <>
      <div className="overlay results-overlay" onClick={onClose} />
      <aside className="drawer results-drawer" role="dialog" aria-modal="true" aria-labelledby="results-title">
        <div className="drawer-head">
          <div className="row">
            <h3 id="results-title" className="results-title">{q.title}</h3>
            <button ref={closeBtn} className="close-x" onClick={onClose} aria-label="Close">×</button>
          </div>
          <p className="results-summary">
            {rows.length === 0 ? "No posts match." : (
              <>
                <b>{rows.length}</b> {rows.length === 1 ? "post" : "posts"}
                {neg > 0 && <>, <span className="neg">{neg} negative</span></>}
                {pos > 0 && <>, <span className="pos">{pos} positive</span></>}
                {newestTxt && <>. Newest from {newestTxt}</>}
                . Click a post to see why it was flagged.
              </>
            )}
          </p>
        </div>
        <CasesTable cases={rows} onSelect={onSelect} />
      </aside>
    </>
  );
}
