// Charts for the downloaded reports, in the Sympany report palette (reportTheme.ts). The
// website's charts are in chartSvg.ts. Date axes and channel names follow the website.
import { dayLabel, tickEvery } from "./chartSvg";
import { displayName } from "./labels";

export const WC_PALETTE = [
  "#4E4385", "#891350", "#6B1040", "#7A6CB0", "#891350", "#A0724F", "#5C5160", "#9185BE",
];
export const hashCode = (s: string) => { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return Math.abs(h); };
export const wcColor = (word: string) => WC_PALETTE[hashCode(word) % WC_PALETTE.length];
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

export interface WCPlaced { name: string; x: number; y: number; size: number; weight: number; color: string; }

// Spiral (circular) word-cloud placement — deterministic, with bounding-box collision.
export function wordCloudLayout(words: { name: string; value: number }[], W = 620, H = 360): WCPlaced[] {
  if (!words.length) return [];
  const max = Math.max(1, ...words.map((w) => w.value));
  const sorted = [...words].sort((a, b) => b.value - a.value);
  const placed: { x: number; y: number; w: number; h: number }[] = [];
  const out: WCPlaced[] = [];
  const cx = W / 2, cy = H / 2;
  const hit = (x: number, y: number, w: number, h: number) =>
    placed.some((p) => !(x + w / 2 < p.x - p.w / 2 || x - w / 2 > p.x + p.w / 2 || y + h / 2 < p.y - p.h / 2 || y - h / 2 > p.y + p.h / 2));
  for (const word of sorted) {
    const size = 13 + Math.round((word.value / max) * 32);
    const w = word.name.length * size * 0.56 + 8;
    const h = size * 1.15;
    let x = cx, y = cy, a = (out.length * 1.3) % (Math.PI * 2), r = 0, ok = false;
    for (let i = 0; i < 1400; i++) {
      x = cx + r * Math.cos(a) * 1.35; y = cy + r * Math.sin(a);
      if (x - w / 2 > 4 && x + w / 2 < W - 4 && y - h / 2 > 4 && y + h / 2 < H - 4 && !hit(x, y, w, h)) { ok = true; break; }
      a += 0.35; r += 0.9;
    }
    if (!ok) continue;
    placed.push({ x, y, w, h });
    out.push({ name: word.name, x, y, size, weight: word.value / max > 0.5 ? 800 : 600, color: wcColor(word.name) });
  }
  return out;
}

// Circular word cloud as an SVG string (for the print/PDF report).
export function wordCloudHtml(words: { name: string; value: number }[]): string {
  if (!words.length) return `<div style="color:#999">Not enough text yet.</div>`;
  const W = 620, H = 340;
  const nodes = wordCloudLayout(words, W, H).map((p) =>
    `<text x="${p.x.toFixed(1)}" y="${p.y.toFixed(1)}" text-anchor="middle" dominant-baseline="middle" font-size="${p.size}" font-weight="${p.weight}" fill="${p.color}" font-family="National2,'Schibsted Grotesk',Arial,sans-serif">${esc(p.name)}</text>`).join("");
  return `<svg width="100%" viewBox="0 0 ${W} ${H}" style="max-width:640px;display:block;margin:0 auto">${nodes}</svg>`;
}

const PALETTE = ["#4E4385", "#891350", "#A0724F", "#A35200", "#7A6CB0", "#5C5160", "#A79DCF"];

// ---- Labeled pie (donut) with leader lines — shared geometry for site + PDF ----
export interface PieArc { path: string; color: string; }
export interface PieLabel { name: string; count: number; pct: number; x: number; y: number; anchor: "start" | "end"; color: string; poly: string; }
export interface PieLayout { W: number; H: number; cx: number; cy: number; rInner: number; total: number; arcs: PieArc[]; labels: PieLabel[]; }

export function pieLayout(data: { name: string; value: number }[], colorFor?: (n: string) => string): PieLayout {
  const W = 680, H = 460, cx = W / 2, cy = H / 2, rOuter = 128, rInner = 74;
  const total = Math.max(1, data.reduce((a, s) => a + s.value, 0));
  const col = (n: string, i: number) => colorFor ? colorFor(n) : PALETTE[i % PALETTE.length];
  const pt = (r: number, a: number) => [cx + r * Math.cos(a), cy + r * Math.sin(a)] as const;
  const arcs: PieArc[] = []; const raw: (PieLabel & { side: number })[] = [];
  let a = -Math.PI / 2;
  data.forEach((s, i) => {
    const ang = (s.value / total) * Math.PI * 2; const a0 = a, a1 = a + ang, mid = (a0 + a1) / 2; a = a1;
    const large = ang > Math.PI ? 1 : 0;
    const [x0, y0] = pt(rOuter, a0), [x1, y1] = pt(rOuter, a1), [x2, y2] = pt(rInner, a1), [x3, y3] = pt(rInner, a0);
    arcs.push({ path: `M${x0.toFixed(1)},${y0.toFixed(1)} A${rOuter},${rOuter} 0 ${large} 1 ${x1.toFixed(1)},${y1.toFixed(1)} L${x2.toFixed(1)},${y2.toFixed(1)} A${rInner},${rInner} 0 ${large} 0 ${x3.toFixed(1)},${y3.toFixed(1)} Z`, color: col(s.name, i) });
    const side = Math.cos(mid) >= 0 ? 1 : -1;
    const [ex, ey] = pt(rOuter + 14, mid);
    raw.push({ name: displayName(s.name), count: s.value, pct: +((s.value / total) * 100).toFixed(2), x: 0, y: ey, anchor: side > 0 ? "start" : "end", color: col(s.name, i), poly: "", side });
    (raw[raw.length - 1] as any)._ring = pt(rOuter, mid); (raw[raw.length - 1] as any)._elbow = [ex, ey];
  });
  // resolve vertical overlaps per side
  for (const sd of [1, -1]) {
    const side = raw.filter((l) => l.side === sd).sort((p, q) => p.y - q.y);
    for (let i = 1; i < side.length; i++) if (side[i].y - side[i - 1].y < 30) side[i].y = side[i - 1].y + 30;
    const labelX = sd > 0 ? cx + rOuter + 54 : cx - rOuter - 54;
    for (const l of side) {
      l.x = labelX;
      const ring = (l as any)._ring, elbow = (l as any)._elbow;
      l.poly = `${ring[0].toFixed(1)},${ring[1].toFixed(1)} ${elbow[0].toFixed(1)},${l.y.toFixed(1)} ${(labelX - sd * 6).toFixed(1)},${l.y.toFixed(1)}`;
    }
  }
  return { W, H, cx, cy, rInner, total, arcs, labels: raw };
}

export function svgPie(data: { name: string; value: number }[], colorFor?: (n: string) => string): string {
  if (!data.length) return `<div style="color:#999">No data.</div>`;
  const L = pieLayout(data, colorFor);
  const arcs = L.arcs.map((a) => `<path d="${a.path}" fill="${a.color}"/>`).join("");
  const labels = L.labels.map((l) =>
    `<polyline points="${l.poly}" fill="none" stroke="#9A9095" stroke-width="1"/>` +
    `<text x="${l.x.toFixed(1)}" y="${(l.y - 3).toFixed(1)}" text-anchor="${l.anchor}" font-size="12" font-weight="600" fill="#1F1A1D" font-family="IBM Plex Sans,Arial">${esc(l.name)}</text>` +
    `<text x="${l.x.toFixed(1)}" y="${(l.y + 12).toFixed(1)}" text-anchor="${l.anchor}" font-size="11" fill="${l.color}" font-family="IBM Plex Sans,Arial">${l.count} | ${l.pct}%</text>`).join("");
  return `<svg width="100%" viewBox="0 0 ${L.W} ${L.H}" style="max-width:560px;display:block;margin:0 auto">${arcs}<text x="${L.cx}" y="${L.cy - 2}" text-anchor="middle" font-size="28" font-weight="800">${L.total}</text><text x="${L.cx}" y="${L.cy + 16}" text-anchor="middle" font-size="11" fill="#9A9095">mentions</text>${labels}</svg>`;
}

// Donut chart SVG.
export function svgDonut(data: { name: string; value: number }[], colors?: (n: string) => string): string {
  const total = Math.max(1, data.reduce((a, s) => a + s.value, 0));
  const size = 220, r = size / 2, stroke = 46, radius = r - stroke / 2, circ = 2 * Math.PI * radius;
  let off = 0;
  const col = (n: string, i: number) => colors ? colors(n) : PALETTE[i % PALETTE.length];
  const arcs = data.map((s, i) => {
    const dash = (s.value / total) * circ;
    const el = `<circle cx="${r}" cy="${r}" r="${radius}" fill="none" stroke="${col(s.name, i)}" stroke-width="${stroke}" stroke-dasharray="${dash} ${circ - dash}" stroke-dashoffset="${-off}" transform="rotate(-90 ${r} ${r})"/>`;
    off += dash; return el;
  }).join("");
  const legend = data.map((s, i) =>
    `<div style="display:flex;align-items:center;gap:8px;font-size:12.5px;padding:3px 0"><span style="width:11px;height:11px;border-radius:3px;background:${col(s.name, i)}"></span><span style="flex:1;text-transform:capitalize">${esc(s.name)}</span><b>${s.value} · ${Math.round((s.value / total) * 100)}%</b></div>`).join("");
  return `<div style="display:flex;gap:26px;align-items:center;flex-wrap:wrap"><svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${arcs}<text x="${r}" y="${r - 2}" text-anchor="middle" font-size="26" font-weight="800">${total}</text><text x="${r}" y="${r + 16}" text-anchor="middle" font-size="11" fill="#9A9095">total</text></svg><div style="flex:1;min-width:190px">${legend}</div></div>`;
}

// Area-line trend SVG.
export function svgArea(data: { day: string; total: number }[]): string {
  if (!data.length) return `<div style="color:#999">No dated items.</div>`;
  const W = 900, H = 260, pad = 34, max = Math.max(1, ...data.map((d) => d.total)), n = data.length;
  const x = (i: number) => pad + (i / Math.max(1, n - 1)) * (W - pad * 2);
  const y = (v: number) => H - pad - (v / max) * (H - pad * 2);
  const line = data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.total).toFixed(1)}`).join(" ");
  const area = `${line} L${x(n - 1)},${H - pad} L${x(0)},${H - pad} Z`;
  const grid = [0, .25, .5, .75, 1].map((f) => `<line x1="${pad}" x2="${W - pad}" y1="${pad + f * (H - pad * 2)}" y2="${pad + f * (H - pad * 2)}" stroke="#EEE6DD"/>`).join("");
  const dots = data.map((d, i) => `<circle cx="${x(i)}" cy="${y(d.total)}" r="3.5" fill="#fff" stroke="#4E4385" stroke-width="2"/>`).join("");
  const every = tickEvery(n);
  const labels = data.map((d, i) => i % every === 0 ? `<text x="${x(i)}" y="${H - 10}" font-size="10" fill="#9A9095" text-anchor="middle">${esc(dayLabel(d.day))}</text>` : "").join("");
  return `<svg width="100%" viewBox="0 0 ${W} ${H}"><defs><linearGradient id="ar" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#4E4385" stop-opacity="0.22"/><stop offset="1" stop-color="#4E4385" stop-opacity="0.02"/></linearGradient></defs>${grid}<path d="${area}" fill="url(#ar)"/><path d="${line}" fill="none" stroke="#4E4385" stroke-width="2.5"/>${dots}${labels}</svg>`;
}

// Multi-series line SVG (brands/sentiment over time).
export function svgMultiLine(series: { name: string; color: string; points: number[] }[], labels: string[]): string {
  if (!series.length) return `<div style="color:#999">No data.</div>`;
  const W = 900, H = 300, pad = 40, n = labels.length;
  const max = Math.max(1, ...series.flatMap((s) => s.points));
  const x = (i: number) => pad + (i / Math.max(1, n - 1)) * (W - pad * 2);
  const y = (v: number) => H - pad - (v / max) * (H - pad * 2);
  const grid = [0, .25, .5, .75, 1].map((f) => `<line x1="${pad}" x2="${W - pad}" y1="${pad + f * (H - pad * 2)}" y2="${pad + f * (H - pad * 2)}" stroke="#EEE6DD"/>`).join("");
  const lines = series.map((s) => {
    const path = s.points.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const dots = s.points.map((v, i) => `<circle cx="${x(i)}" cy="${y(v)}" r="3" fill="#fff" stroke="${s.color}" stroke-width="2"/>`).join("");
    return `<path d="${path}" fill="none" stroke="${s.color}" stroke-width="2.2"/>${dots}`;
  }).join("");
  const every = tickEvery(n);
  const xlabels = labels.map((l, i) => i % every === 0 ? `<text x="${x(i)}" y="${H - 12}" font-size="10" fill="#9A9095" text-anchor="middle">${esc(dayLabel(l))}</text>` : "").join("");
  const legend = series.map((s) => `<span style="display:inline-flex;align-items:center;gap:6px;margin-right:16px;font-size:12px"><span style="width:12px;height:3px;background:${s.color};display:inline-block"></span>${esc(s.name)}</span>`).join("");
  return `<div>${legend}<svg width="100%" viewBox="0 0 ${W} ${H}">${grid}${lines}${xlabels}</svg></div>`;
}

// Static platform-network SVG for the PDF (hubs on a ring, brand leaves around each hub).
export function svgPlatformNetwork(hubs: { platform: string; total: number; leaves: { brand: string; count: number; neg: number; neu: number; pos: number }[] }[]): string {
  if (!hubs.length) return `<div style="color:#999">No data.</div>`;
  const W = 920, H = 660, cx = W / 2, cy = H / 2, Rh = 190;
  const maxT = Math.max(1, ...hubs.map((h) => h.total));
  const maxL = Math.max(1, ...hubs.flatMap((h) => h.leaves.map((l) => l.count)));
  const ring = (x: number, y: number, r: number, neg: number, neu: number, pos: number) => {
    const total = Math.max(1, neg + neu + pos), circ = 2 * Math.PI * (r - 3); let off = 0;
    return [{ v: neg, c: "#C8372D" }, { v: neu, c: "#D6CCC4" }, { v: pos, c: "#2E7D4F" }].map((s) => {
      const dash = (s.v / total) * circ;
      const el = `<circle cx="${x}" cy="${y}" r="${r - 3}" fill="none" stroke="${s.c}" stroke-width="4" stroke-dasharray="${dash} ${circ - dash}" stroke-dashoffset="${-off}" transform="rotate(-90 ${x} ${y})"/>`;
      off += dash; return el;
    }).join("");
  };
  let links = "", nodes = "";
  hubs.forEach((h, hi) => {
    const ha = (hi / hubs.length) * Math.PI * 2 - Math.PI / 2;
    const hx = cx + Rh * Math.cos(ha), hy = cy + Rh * Math.sin(ha);
    const hr = 22 + (h.total / maxT) * 34;
    h.leaves.forEach((l, li) => {
      const la = (li / Math.max(1, h.leaves.length)) * Math.PI * 2;
      const lr = 12 + (l.count / maxL) * 12;
      const lx = hx + (hr + 42) * Math.cos(la), ly = hy + (hr + 42) * Math.sin(la);
      links += `<line x1="${hx.toFixed(1)}" y1="${hy.toFixed(1)}" x2="${lx.toFixed(1)}" y2="${ly.toFixed(1)}" stroke="#E3D9CF" stroke-width="1.4"/>`;
      nodes += `<circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="${lr}" fill="#fff" stroke="#EEE6DD"/>${ring(lx, ly, lr, l.neg, l.neu, l.pos)}<text x="${lx.toFixed(1)}" y="${(ly + 4).toFixed(1)}" text-anchor="middle" font-size="11" font-weight="800" fill="#1F1A1D">${l.count}</text><text x="${lx.toFixed(1)}" y="${(ly + lr + 11).toFixed(1)}" text-anchor="middle" font-size="9" fill="#5E5559">${esc(l.brand)}</text>`;
    });
    nodes += `<circle cx="${hx.toFixed(1)}" cy="${hy.toFixed(1)}" r="${hr}" fill="#4E4385" stroke="#6B1040"/><text x="${hx.toFixed(1)}" y="${(hy + 5).toFixed(1)}" text-anchor="middle" font-size="15" font-weight="800" fill="#fff">${h.total}</text><text x="${hx.toFixed(1)}" y="${(hy + hr + 12).toFixed(1)}" text-anchor="middle" font-size="10" font-weight="700" fill="#5E5559">${esc(displayName(h.platform))}</text>`;
  });
  return `<svg width="100%" viewBox="0 0 ${W} ${H}" style="display:block">${links}${nodes}</svg>`;
}

// Horizontal bars SVG-free HTML (kept for compactness).
export function barsHtml(rows: { name: string; value: number }[], unit = ""): string {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return rows.map((r) => `<div style="display:flex;align-items:center;gap:12px;margin:9px 0;font-size:13px"><span style="width:150px;color:#5E5559;text-transform:capitalize">${esc(r.name)}</span><span style="flex:1;height:10px;background:#F2ECE6;border-radius:2px;overflow:hidden"><span style="display:block;height:100%;width:${Math.max(3, (r.value / max) * 100)}%;background:#4E4385;border-radius:2px"></span></span><b style="width:80px;text-align:right">${r.value.toLocaleString()}${unit}</b></div>`).join("");
}
