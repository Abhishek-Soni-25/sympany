import type { ScanQuota } from "../types";
import { Icon } from "./Icon";

const timeOf = (iso: string | null) => {
  const t = iso ? new Date(iso) : null;
  return t && !isNaN(t.getTime()) ? t.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "";
};

export function TopBar({
  title, subtitle, count, running, live, onScan, onMenu, onLogout, lastScan, quota,
}: {
  title: string; subtitle: string; count: number; running: boolean; live: boolean; onScan: () => void; onMenu?: () => void; onLogout?: () => void;
  lastScan?: string | null; quota?: ScanQuota | null;
}) {
  const last = lastScan ? new Date(lastScan) : null;
  // Run Scan is allowed scan.manual_per_day times per day (successful scans only).
  const usedUp = !!quota && !quota.available;
  const doneTip = usedUp
    ? `Today's scan was done${quota?.last_ok_at ? ` at ${timeOf(quota.last_ok_at)}` : ""}${quota?.last_by ? ` by ${quota.last_by}` : ""}. The next scan can be run tomorrow.`
    : "Collects everything published since the last scan, analyses it and e-mails the summary. One scan a day.";
  return (
    <div className="topbar">
      <div className="tb-left">
        {onMenu && <button className="hamburger" onClick={onMenu} aria-label="Menu"><Icon name="menu" size={18} /></button>}
        <img src="/sympany-mark.svg" alt="Sympany" className="tb-mark" />
        <div>
          <div className="tb-title">{title}</div>
          <div className="tb-sub">{subtitle}</div>
        </div>
      </div>
      <div className="tb-right">
        <span className={`data-badge ${live ? "live" : "demo"}`}>
          {live ? `${count.toLocaleString()} posts stored` : "No data yet"}
        </span>
        {last && !isNaN(last.getTime()) && (
          <span className="last-scan" title="Each scan collects everything published since the previous one; the dashboard keeps the last scanned data">
            Last scan {last.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
        <button className="btn" onClick={onScan} disabled={running || usedUp} title={doneTip}>
          {running ? <><span className="spinner" /> Scanning…</> : usedUp ? <><Icon name="check" size={15} /> Today's scan done</> : <><Icon name="scan" size={15} /> Run Scan</>}
        </button>
        {onLogout && (
          <button className="btn-logout" onClick={onLogout} title="Log out">
            <Icon name="logout" size={15} /> Log out
          </button>
        )}
      </div>
    </div>
  );
}
