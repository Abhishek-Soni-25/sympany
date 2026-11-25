import type { Severity } from "../types";
import { categoryLabel } from "../labels";

export const SEV_COLORS: Record<Severity, string> = {
  HIGH: "var(--high)",
  MEDIUM: "var(--medium)",
  LOW: "var(--low)",
  NONE: "#9A9095",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const label = { HIGH: "High", MEDIUM: "Medium", LOW: "Low", NONE: "No risk" }[severity] ?? severity;
  return (
    <span className={`badge sev-${severity}`}>
      <span className="pip" style={{ background: SEV_COLORS[severity] }} />
      {label}
    </span>
  );
}

// Shown instead of a severity when the AI analysis of a post failed (retried next scan).
export function FailedBadge() {
  return (
    <span className="badge sev-FAILED" title="The AI analysis failed. It is retried automatically on the next scan.">
      <span className="pip" style={{ background: "var(--medium)" }} />
      Failed
    </span>
  );
}

export function CategoryChip({ category }: { category: string }) {
  if (!category || category === "NONE" || category === "GENERAL")
    return <span className="cat-chip general">General</span>;
  return <span className="cat-chip">{categoryLabel(category)}</span>;
}

const SENT_COLOR: Record<string, string> = {
  negative: "var(--high)", positive: "var(--ok)", neutral: "var(--none)", mixed: "var(--medium)",
  failed: "var(--medium)",
};

export function SentimentTag({ polarity }: { polarity: string }) {
  const key = (polarity || "neutral").toLowerCase();
  return <span className="sent" style={{ color: SENT_COLOR[key] ?? "var(--ink-faint)" }}>{key}</span>;
}

export function ConfidenceBar({ value }: { value: number }) {
  return (
    <span className="conf">
      {Math.round(value * 100)}%
      <span className="conf-bar">
        <span className="conf-fill" style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
    </span>
  );
}

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  // "23 Oct, 15:17": short, one line, 24-hour clock.
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}
