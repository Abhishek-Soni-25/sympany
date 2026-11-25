import { useEffect, useRef, useState } from "react";
import { topics as topicsOf, type Topic } from "../analytics";
import type { CompetitorPost, CompetitorSov, Mention } from "../types";
import { COMPETITOR_TINTS, NAVY, NEUTRAL, OWN, POSITIVE, RED } from "../palette";
import { displayName } from "../labels";
import { BRAND_SHORT } from "../brand";

const SENT = [{ k: "neg", c: RED }, { k: "neu", c: NEUTRAL }, { k: "pos", c: POSITIVE }] as const;
// Half the width of a node label, so a node is kept far enough from the edge to show it.
const halfLabel = (label: string) => label.length * 3.1 + 6;

// Self-contained force-directed network graph (no external lib). Nodes repel, links act as
// springs, mild gravity keeps it centred. Interactive: hover tooltip + drag.
export interface GInput { id: string; label: string; count: number; neg: number; neu: number; pos: number; hub?: boolean; fill?: string; own?: boolean; }
interface GNode extends GInput { r: number; x: number; y: number; vx: number; vy: number; fixed?: boolean; }
interface GLink { s: string; t: string; w?: number; }

const W = 880, H = 560;

export function ForceGraph({ nodes: input, links, height = H }: { nodes: GInput[]; links: GLink[]; height?: number }) {
  const nodesRef = useRef<GNode[]>([]);
  const dragRef = useRef<string | null>(null);
  const [, force] = useState(0);
  const [hover, setHover] = useState<GNode | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const maxHub = Math.max(1, ...input.filter((n) => n.hub).map((n) => n.count));
    const maxLeaf = Math.max(1, ...input.filter((n) => !n.hub).map((n) => n.count));
    nodesRef.current = input.map((n, i) => {
      const a = (i / Math.max(1, input.length)) * Math.PI * 2;
      const r = n.hub ? 18 + (n.count / maxHub) * 22 : 11 + (n.count / maxLeaf) * 16;
      return { ...n, r, x: W / 2 + Math.cos(a) * (n.hub ? 90 : 190), y: height / 2 + Math.sin(a) * (n.hub ? 70 : 170), vx: 0, vy: 0 };
    });
    force((v) => v + 1);
  }, [input, height]);

  useEffect(() => {
    let raf = 0;
    const linkOf = (id: string) => links.filter((l) => l.s === id || l.t === id);
    const tick = () => {
      const nodes = nodesRef.current;
      const byId = new Map(nodes.map((n) => [n.id, n]));
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i]; if (a.fixed) continue;
        let fx = 0, fy = 0;
        for (let j = 0; j < nodes.length; j++) {
          if (i === j) continue; const b = nodes[j];
          const dx = a.x - b.x, dy = a.y - b.y; const d2 = dx * dx + dy * dy || 1, d = Math.sqrt(d2);
          // stronger repulsion; extra push between hubs so brand nodes never stack
          const rep = (a.hub && b.hub ? 42000 : 13000) / d2;
          fx += (dx / d) * rep; fy += (dy / d) * rep;
        }
        const ln = linkOf(a.id);
        for (const l of ln) {
          const other = byId.get(l.s === a.id ? l.t : l.s); if (!other) continue;
          const dx = a.x - other.x, dy = a.y - other.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
          const rest = a.r + other.r + 60;
          // scale by 1/linkCount so a topic linked to every brand isn't yanked to the centre
          const k = (d - rest) * 0.01 / Math.sqrt(ln.length || 1);
          fx -= (dx / d) * k; fy -= (dy / d) * k;
        }
        fx += (W / 2 - a.x) * 0.004; fy += (height / 2 - a.y) * 0.004;
        a.vx = (a.vx + fx) * 0.75; a.vy = (a.vy + fy) * 0.75;
        a.x = a.x + a.vx; a.y = a.y + a.vy;
      }
      // hard collision resolution (several passes so springs can't reintroduce overlap)
      for (let pass = 0; pass < 10; pass++) {
        for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j];
          const dx = b.x - a.x, dy = b.y - a.y; const d = Math.sqrt(dx * dx + dy * dy) || 1;
          const minD = a.r + b.r + 34;
          if (d < minD) {
            const push = (minD - d) / 2, ux = dx / d, uy = dy / d;
            if (!a.fixed) { a.x -= ux * push; a.y -= uy * push; }
            if (!b.fixed) { b.x += ux * push; b.y += uy * push; }
          }
        }
      }
      for (const n of nodes) {
        const side = Math.max(n.r + 4, halfLabel(n.label));
        n.x = Math.max(side, Math.min(W - side, n.x));
        n.y = Math.max(n.r + 4, Math.min(height - n.r - 20, n.y));
      }
      force((v) => (v + 1) % 100000);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [links, height]);

  const toSvg = (e: React.PointerEvent) => { const r = svgRef.current!.getBoundingClientRect(); return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * height }; };
  const onDown = (id: string) => (e: React.PointerEvent) => { dragRef.current = id; (e.target as Element).setPointerCapture?.(e.pointerId); const n = nodesRef.current.find((x) => x.id === id); if (n) n.fixed = true; };
  const onMove = (e: React.PointerEvent) => { const id = dragRef.current; if (!id) return; const p = toSvg(e); const n = nodesRef.current.find((x) => x.id === id); if (n) { n.x = p.x; n.y = p.y; n.vx = n.vy = 0; } };
  const onUp = () => { const id = dragRef.current; if (id) { const n = nodesRef.current.find((x) => x.id === id); if (n) n.fixed = false; } dragRef.current = null; };

  const nodes = nodesRef.current; const byId = new Map(nodes.map((n) => [n.id, n]));
  const ring = (n: GNode) => {
    const total = Math.max(1, n.neg + n.neu + n.pos); const circ = 2 * Math.PI * (n.r - 3); let off = 0;
    return SENT.map(({ k, c }) => ({ v: n[k], c })).map((s, i) => {
      const dash = (s.v / total) * circ;
      const el = <circle key={i} cx={n.x} cy={n.y} r={n.r - 3} fill="none" stroke={s.c} strokeWidth={4} strokeDasharray={`${dash} ${circ - dash}`} strokeDashoffset={-off} transform={`rotate(-90 ${n.x} ${n.y})`} />;
      off += dash; return el;
    });
  };

  if (!input.length) return <div className="muted" style={{ fontSize: 13 }}>No data yet.</div>;
  return (
    <div className="chart-wrap" style={{ position: "relative" }}>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${height}`} width="100%" style={{ touchAction: "none", cursor: dragRef.current ? "grabbing" : "default" }} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp}>
        {links.map((l, i) => { const a = byId.get(l.s), b = byId.get(l.t); if (!a || !b) return null; return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={a.fill || b.fill || "#E3D9CF"} strokeWidth={l.w ? Math.max(1, Math.min(7, l.w)) : 1.5} opacity={0.35} />; })}
        {nodes.map((n) => (
          <g key={n.id} onPointerDown={onDown(n.id)} onMouseEnter={() => setHover(n)} onMouseLeave={() => setHover(null)} style={{ cursor: "grab" }}>
            <circle cx={n.x} cy={n.y} r={n.r} fill={n.fill ?? (n.hub ? NAVY : "#fff")} stroke={n.fill ?? (n.hub ? NAVY : "#E8DFD6")} strokeWidth={1} />
            {!n.fill && !n.hub && ring(n)}
            <text x={n.x} y={n.y + 4} textAnchor="middle" fontSize={Math.min(15, n.r * 0.7)} fontWeight="700" fill={n.fill || n.hub ? "#fff" : "var(--ink)"}>{n.count}</text>
            <text x={n.x} y={n.y + n.r + 14} textAnchor="middle" fontSize="11" fontWeight={n.hub || n.own ? 600 : 500} fill={n.own ? OWN : "var(--ink-soft)"}>{n.label}</text>
          </g>
        ))}
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: `${(hover.x / W) * 100}%`, top: `${(hover.y / height) * 100 - 6}%` }}>
          <b>{hover.label}</b>: {hover.count} mentions
          {!hover.hub && <SentimentLines neg={hover.neg} neu={hover.neu} pos={hover.pos} />}
        </div>
      )}
      <div className="muted" style={{ fontSize: 12, marginTop: 6, textAlign: "center" }}>Circle size shows the number of mentions. Hover a circle for its sentiment; drag to move it.</div>
    </div>
  );
}

// Topic network (Sympany centre → topics).
export function NetworkGraph({ topics }: { topics: Topic[] }) {
  const center: GInput = { id: "__c", label: BRAND_SHORT, count: topics.reduce((a, t) => a + t.count, 0), neg: 0, neu: 0, pos: 0, hub: true };
  const nodes: GInput[] = [center, ...topics.map((t) => ({ id: t.name, label: t.name, count: t.count, neg: t.negative, neu: t.neutral, pos: t.positive }))];
  const links: GLink[] = topics.map((t) => ({ s: "__c", t: t.name }));
  return <ForceGraph nodes={nodes} links={links} height={470} />;
}

// Hover lines: negative / neutral / positive counts.
function SentimentLines({ neg, neu, pos }: { neg: number; neu: number; pos: number }) {
  const rows: [string, number, string][] = [["Negative", neg, RED], ["Neutral", neu, NEUTRAL], ["Positive", pos, POSITIVE]];
  return <>{rows.map(([l, v, c]) => (
    <div key={l}><span className="ml-swatch" style={{ background: c, height: 9, width: 9, borderRadius: 2 }} /> {l}: {v}</div>
  ))}</>;
}

// Insurer-vs-competitor topic network: the insurers in the middle (Sympany in berry), the topics
// around them. A line's thickness is that insurer's number of posts on the topic, counted from its
// collected posts, on the channels collected for every insurer.
export function TopicComparisonNetwork({ mentions, posts, sov }: { mentions: Mention[]; posts: CompetitorPost[]; sov: CompetitorSov | null }) {
  const [hover, setHover] = useState<{ label: string; count: number; neg: number; neu: number; pos: number; x: number; y: number } | null>(null);
  const shared = new Set(posts.map((p) => p.platform));
  const own = posts.length ? mentions.filter((m) => shared.has(m.platform)) : mentions;
  const groups = [{ name: BRAND_SHORT, own: true, items: own as Mention[] },
    ...Object.keys(sov?.competitors ?? {}).map((n) => ({ name: n, own: false, items: posts.filter((p) => p.brand === n) as Mention[] }))]
    .filter((g) => g.items.length);
  const count = (ms: Mention[], s: string) => ms.filter((m) => m.sentiment === s).length;
  const brands = groups.map((g, i) => ({
    name: g.name, own: g.own, total: g.items.length,
    neg: count(g.items, "negative"), neu: count(g.items, "neutral"), pos: count(g.items, "positive"),
    byTopic: new Map(topicsOf(g.items).map((t) => [t.name, t.count])),
    color: g.own ? OWN : COMPETITOR_TINTS[(i - 1) % COMPETITOR_TINTS.length],
  }));
  const topicList: Topic[] = topicsOf(groups.flatMap((g) => g.items));
  if (!brands.length || !topicList.length) return <div className="muted" style={{ fontSize: 13 }}>No topics found in the posts yet.</div>;

  const W = 940, H = 640, cx = W / 2, cy = H / 2, Ri = 128, Ro = 248;
  const maxBrand = Math.max(1, ...brands.map((b) => b.total));
  const maxTopic = Math.max(1, ...topicList.map((t) => t.count));
  const maxLink = Math.max(1, ...brands.flatMap((b) => [...b.byTopic.values()]));
  const bpos = brands.map((b, i) => { const a = -Math.PI / 2 + (i / brands.length) * Math.PI * 2; return { ...b, x: cx + Ri * Math.cos(a), y: cy + Ri * Math.sin(a), r: 20 + (b.total / maxBrand) * 20 }; });
  const tpos = topicList.map((t, i) => { const a = -Math.PI / 2 + (i / topicList.length) * Math.PI * 2; return { t, x: cx + Ro * Math.cos(a), y: cy + Ro * Math.sin(a), r: 12 + (t.count / maxTopic) * 16, ang: a }; });

  const ring = (x: number, y: number, r: number, neg: number, neu: number, pos: number) => {
    const total = Math.max(1, neg + neu + pos), circ = 2 * Math.PI * (r - 3); let off = 0;
    return [{ v: neg, c: RED }, { v: neu, c: NEUTRAL }, { v: pos, c: POSITIVE }].map((s, k) => {
      const dash = (s.v / total) * circ;
      const el = <circle key={k} cx={x} cy={y} r={r - 3} fill="none" stroke={s.c} strokeWidth={4} strokeDasharray={`${dash} ${circ - dash}`} strokeDashoffset={-off} transform={`rotate(-90 ${x} ${y})`} />;
      off += dash; return el;
    });
  };

  return (
    <div className="chart-wrap" style={{ position: "relative" }}>
      <div className="ml-legend" style={{ justifyContent: "center", marginBottom: 4 }}>
        {bpos.map((b) => <span key={b.name} className="ml-leg"><span className="ml-swatch" style={{ background: b.color, height: 11, width: 11, borderRadius: 3 }} />{b.name}</span>)}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
        {bpos.map((b) => tpos.map((tp) => {
          const w = b.byTopic.get(tp.t.name) ?? 0; if (!w) return null;
          return <line key={b.name + tp.t.name} x1={b.x} y1={b.y} x2={tp.x} y2={tp.y} stroke={b.color} strokeWidth={0.8 + (w / maxLink) * 6} opacity={b.own ? 0.32 : 0.2} />;
        }))}
        {tpos.map((tp) => {
          const side = Math.cos(tp.ang) >= 0 ? 1 : -1;
          return (
            <g key={tp.t.name} onMouseEnter={() => setHover({ label: tp.t.name, count: tp.t.count, neg: tp.t.negative, neu: tp.t.neutral, pos: tp.t.positive, x: tp.x, y: tp.y })} onMouseLeave={() => setHover(null)}>
              <circle cx={tp.x} cy={tp.y} r={tp.r} fill="#fff" stroke="#E8DFD6" />
              {ring(tp.x, tp.y, tp.r, tp.t.negative, tp.t.neutral, tp.t.positive)}
              <text x={tp.x} y={tp.y + 4} textAnchor="middle" fontSize={12} fontWeight="700" fill="var(--ink)">{tp.t.count}</text>
              <text x={tp.x + side * (tp.r + 6)} y={tp.y + 4} textAnchor={side > 0 ? "start" : "end"} fontSize="12" fontWeight="500" fill="var(--ink-soft)">{tp.t.name}</text>
            </g>
          );
        })}
        {bpos.map((b) => (
          <g key={b.name} onMouseEnter={() => setHover({ label: b.name, count: b.total, neg: b.neg, neu: b.neu, pos: b.pos, x: b.x, y: b.y })} onMouseLeave={() => setHover(null)}>
            <circle cx={b.x} cy={b.y} r={b.r} fill={b.color} />
            <text x={b.x} y={b.y + 5} textAnchor="middle" fontSize={14} fontWeight="700" fill="#fff">{b.total}</text>
            <text x={b.x} y={b.y + b.r + 14} textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--ink)">{b.name}</text>
          </g>
        ))}
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: `${(hover.x / W) * 100}%`, top: `${(hover.y / H) * 100 - 4}%` }}>
          <b>{hover.label}</b>: {hover.count} posts
          <SentimentLines neg={hover.neg} neu={hover.neu} pos={hover.pos} />
        </div>
      )}
      <div className="muted" style={{ fontSize: 12, marginTop: 6, textAlign: "center" }}>
        Insurers in the middle, topics around them. A thicker line means more of that insurer's posts are about the topic.
        {posts.length ? ` Counted on ${[...shared].map(displayName).join(", ")}, where posts are collected for every insurer.` : ""}
      </div>
    </div>
  );
}

// Platform network for competition: each platform is a hub, brands orbit it (per-platform counts).
export function PlatformNetwork({ sov, mentions }: { sov: CompetitorSov | null; mentions: { platform: string; sentiment: string }[] }) {
  const brands: { name: string; by: Record<string, number>; neg: number; neu: number; pos: number }[] = [];
  if (sov) {
    brands.push({ name: BRAND_SHORT, by: sov.own.by_platform || {}, neg: sov.own.negative, neu: sov.own.neutral, pos: sov.own.positive });
    for (const [n, v] of Object.entries(sov.competitors)) brands.push({ name: n, by: v.by_platform || {}, neg: v.negative, neu: v.neutral, pos: v.positive });
  } else {
    // fall back to Sympany-only from mentions
    const by: Record<string, number> = {}; let neg = 0, neu = 0, pos = 0;
    for (const m of mentions) { by[m.platform] = (by[m.platform] || 0) + 1; if (m.sentiment === "negative") neg++; else if (m.sentiment === "positive") pos++; else neu++; }
    brands.push({ name: BRAND_SHORT, by, neg, neu, pos });
  }
  const platforms = [...new Set(brands.flatMap((b) => Object.keys(b.by)))];
  const nodes: GInput[] = []; const links: GLink[] = [];
  for (const p of platforms) {
    const total = brands.reduce((a, b) => a + (b.by[p] || 0), 0);
    if (!total) continue;
    nodes.push({ id: `p:${p}`, label: displayName(p), count: total, neg: 0, neu: total, pos: 0, hub: true });
    for (const b of brands) {
      const c = b.by[p] || 0; if (!c) continue;
      const t = Math.max(1, b.neg + b.neu + b.pos);
      const id = `${p}:${b.name}`;
      nodes.push({ id, label: b.name, count: c, neg: Math.round(c * b.neg / t), neu: Math.round(c * b.neu / t), pos: Math.round(c * b.pos / t), own: b.name === BRAND_SHORT });
      links.push({ s: `p:${p}`, t: id });
    }
  }
  return <ForceGraph nodes={nodes} links={links} height={560} />;
}
