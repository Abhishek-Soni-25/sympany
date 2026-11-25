import { CHANNELS, DEFAULT_FILTERS, PRESETS, SOURCES, ymd, type DatePreset, type Filters, type Source } from "../filters";
import { Icon } from "./Icon";
import { PlatformLogo } from "./PlatformLogo";

// The filter row under the page title. It reads as a sentence — "Showing [period] on
// [channels] from [source]" — and applies to every page and to every report or CSV
// downloaded while it is set.
export function FilterBar({ filters, onChange, shown, total, period }: {
  filters: Filters; onChange: (f: Filters) => void; shown: number; total: number; period: string;
}) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });
  const today = ymd(new Date());
  const setPreset = (preset: DatePreset) => {
    // Custom dates start from the last 30 days so the two date boxes are never empty.
    if (preset === "custom" && (!filters.from || !filters.to)) {
      const d = new Date(); d.setDate(d.getDate() - 29);
      set({ preset, from: ymd(d), to: today });
    } else set({ preset });
  };
  const toggleChannel = (key: string) => {
    const on = filters.channels.includes(key) ? filters.channels.filter((c) => c !== key) : [...filters.channels, key];
    set({ channels: on.length === CHANNELS.length ? [] : on });
  };
  const changed = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS);
  return (
    <div className="filterbar" role="region" aria-label="Filters">
      <div className="fb-sentence">
        <span className="fb-phrase">
        <span className="fb-word">Showing</span>
        <select className="fb-select" aria-label="Period" value={filters.preset} onChange={(e) => setPreset(e.target.value as DatePreset)}>
          {PRESETS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
        </select>
        {filters.preset === "custom" && (
          <span className="fb-dates">
            <input type="date" aria-label="From" value={filters.from} max={filters.to || today} onChange={(e) => set({ from: e.target.value })} />
            <span className="fb-word">to</span>
            <input type="date" aria-label="To" value={filters.to} min={filters.from} max={today} onChange={(e) => set({ to: e.target.value })} />
          </span>
        )}
        </span>
        <span className="fb-phrase">
        <span className="fb-word">on</span>
        <span className="fb-chips" role="group" aria-label="Channels">
          <button type="button" className="fb-chip" aria-pressed={filters.channels.length === 0} onClick={() => set({ channels: [] })}>All channels</button>
          {CHANNELS.map((c) => (
            <button type="button" key={c.key} className="fb-chip" aria-pressed={filters.channels.includes(c.key)} onClick={() => toggleChannel(c.key)}>
              <PlatformLogo platform={c.key} size={15} />{c.label}
            </button>
          ))}
        </span>
        </span>
        <span className="fb-phrase">
        <span className="fb-word">from</span>
        <span className="fb-seg" role="radiogroup" aria-label="Source">
          {SOURCES.map((s) => (
            <button type="button" role="radio" key={s.key} aria-checked={filters.source === s.key} onClick={() => set({ source: s.key as Source })}>{s.label}</button>
          ))}
        </span>
        </span>
      </div>
      <div className="fb-summary">
        <span><b>{shown.toLocaleString()}</b> of {total.toLocaleString()} posts, {period}</span>
        {changed && <button type="button" className="fb-reset" onClick={() => onChange(DEFAULT_FILTERS)}><Icon name="close" size={12} /> Clear filters</button>}
      </div>
    </div>
  );
}
