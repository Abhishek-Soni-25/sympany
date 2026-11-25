import { useState } from "react";
import { Icon, type IconName } from "./Icon";

export type Page =
  | "pinned" | "listening_overview" | "influencer" | "campaign_analytics" | "pr_dashboard" | "reviews"
  | "content_sense" | "content_performance" | "marketing"
  | "bench_competition"
  | "reports" | "campaign" | "compliance" | "mc_settings";

type Section = "analytics" | "reports" | "campaign" | "compliance";

const RAIL: { key: Section; icon: IconName; label: string }[] = [
  { key: "analytics", icon: "analytics", label: "Analytics" },
  { key: "reports", icon: "reports", label: "Reports" },
  { key: "campaign", icon: "campaign", label: "Campaign" },
  { key: "compliance", icon: "compliance", label: "Media compliance" },
];

const ANALYTICS: { group: string; items: { key: Page; label: string }[] }[] = [
  { group: "", items: [{ key: "pinned", label: "Overview dashboard" }] },
  { group: "Social listening", items: [
    { key: "listening_overview", label: "Listening overview" },
    { key: "influencer", label: "Influencers & UGC" },
    { key: "content_sense", label: "Topics & themes" },
    { key: "pr_dashboard", label: "PR & Reputation" },
    { key: "reviews", label: "Ratings & reviews" },
  ] },
  { group: "Marketing", items: [
    { key: "marketing", label: "Marketing report" },
    { key: "content_performance", label: "Content performance" },
    { key: "campaign_analytics", label: "Campaign analytics" },
  ] },
  { group: "Benchmarking", items: [
    { key: "bench_competition", label: "Competition benchmarking" },
  ] },
];

const SECTION_PAGES: Record<Exclude<Section, "analytics">, { key: Page; label: string }[]> = {
  reports: [{ key: "reports", label: "Risk report & export" }],
  campaign: [{ key: "campaign", label: "Keyword campaigns" }],
  compliance: [
    { key: "compliance", label: "Media compliance analyser" },
    { key: "mc_settings", label: "Settings" },
  ],
};

const PAGE_SECTION: Record<Page, Section> = {
  pinned: "analytics", listening_overview: "analytics", influencer: "analytics",
  campaign_analytics: "analytics", pr_dashboard: "analytics", content_sense: "analytics", reviews: "analytics",
  content_performance: "analytics", marketing: "analytics",
  bench_competition: "analytics",
  reports: "reports", campaign: "campaign",
  compliance: "compliance", mc_settings: "compliance",
};

export function Sidebar({ active, onNav, showCompliance = false }: {
  active: Page; onNav: (p: Page) => void; showCompliance?: boolean;
}) {
  const [section, setSection] = useState<Section>(PAGE_SECTION[active]);
  // Media Compliance is hidden unless features.media_compliance is on (code kept as is).
  const rail = showCompliance ? RAIL : RAIL.filter((r) => r.key !== "compliance");

  return (
    <div className="sidebar2">
      <div className="rail">
        <img src="/sympany-mark.svg" alt="Sympany" className="rail-logo" />
        {rail.map((r) => (
          <button key={r.key} className={`rail-btn ${section === r.key ? "on" : ""}`}
            title={r.label} onClick={() => {
              setSection(r.key);
              onNav(r.key === "analytics" ? "pinned" : SECTION_PAGES[r.key][0].key);
            }}>
            <span className="rail-ico"><Icon name={r.icon} size={20} /></span>
            <span className="rail-lbl">{r.label}</span>
          </button>
        ))}
      </div>

      <div className="subnav">
        <div className="subnav-brand">
          <img src="/sympany-logo.svg" alt="Sympany. All the insurance you need." />
          <span className="subnav-product">Social media listening</span>
        </div>
        <div className="subnav-title">{RAIL.find((r) => r.key === section)?.label}</div>
        {section === "analytics" ? (
          <div className="subnav-tree">
            {ANALYTICS.map((g, gi) => (
              <AnalyticsGroup key={gi} group={g.group} items={g.items} active={active} onNav={onNav} />
            ))}
          </div>
        ) : (
          <div className="subnav-tree">
            {SECTION_PAGES[section].map((it) => (
              <button key={it.key} className={`sub-item ${active === it.key ? "active" : ""}`} onClick={() => onNav(it.key)}>{it.label}</button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AnalyticsGroup({ group, items, active, onNav }: {
  group: string; items: { key: Page; label: string }[]; active: Page; onNav: (p: Page) => void;
}) {
  const [open, setOpen] = useState(true);
  if (!group) {
    return (
      <div className="subnav-flat">
        {items.map((it) => (
          <button key={it.key} className={`sub-item ${active === it.key ? "active" : ""}`} onClick={() => onNav(it.key)}>{it.label}</button>
        ))}
      </div>
    );
  }
  return (
    <div className="subnav-group">
      <button className="subnav-group-head" onClick={() => setOpen((o) => !o)}>
        <span>{group}</span><span className="chev"><Icon name={open ? "chevronDown" : "chevronRight"} size={14} /></span>
      </button>
      {open && items.map((it) => (
        <button key={it.key} className={`sub-item indent ${active === it.key ? "active" : ""}`} onClick={() => onNav(it.key)}>{it.label}</button>
      ))}
    </div>
  );
}
