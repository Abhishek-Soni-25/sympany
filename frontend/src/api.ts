import type {
  AuthorActivity, CaseFile, Channel, CompetitorPost, CompetitorSov, CoverageNote, FollowerSummary, Mention, ResponseTimes, ScanStatus, Stats,
} from "./types";

const BASE = "/api";

export class HttpError extends Error {
  constructor(public status: number, message: string, public body: Record<string, unknown> = {}) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new HttpError(res.status, `${res.status} ${res.statusText}`, body);
  }
  return res.json() as Promise<T>;
}

export type AuthMode = "password" | "alb" | "none";
export type Me = {
  sub: string; email: string; name: string; groups: string[]; is_admin: boolean;
  auth_mode: AuthMode; features: { media_compliance: boolean };
};

export const api = {
  health: () => get<{ status: string }>("/health"),
  stats: () => get<Stats>("/stats"),
  cases: (filters: Partial<Record<"severity" | "category" | "channel", string>> = {}) => {
    const q = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => v && q.set(k, v));
    const qs = q.toString();
    return get<CaseFile[]>(`/cases${qs ? `?${qs}` : ""}`);
  },
  channels: () => get<Channel[]>("/channels"),
  mentions: (filters: Partial<Record<"platform" | "sentiment" | "severity", string>> = {}) => {
    const q = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => v && q.set(k, v));
    const qs = q.toString();
    return get<Mention[]>(`/mentions${qs ? `?${qs}` : ""}`);
  },
  authors: (platform = "") =>
    get<AuthorActivity[]>(`/authors${platform ? `?platform=${platform}` : ""}`),
  sentiment: () => get<Record<string, Record<string, number>>>("/sentiment"),
  competitors: () => get<CompetitorSov>("/competitors"),
  competitorMentions: () => get<CompetitorPost[]>("/competitors/mentions"),
  followers: () => get<FollowerSummary>("/followers"),
  responseTimes: () => get<ResponseTimes>("/response-times"),
  coverage: () => get<CoverageNote[]>("/coverage"),
  keywords: () => get<{ base: string[]; custom: string[] }>("/keywords"),
  saveKeywords: async (custom: string[]) => {
    const res = await fetch(`${BASE}/keywords`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ custom }) });
    return res.json() as Promise<{ base: string[]; custom: string[] }>;
  },
  me: () => get<Me>("/me"),
  login: async (username: string, password: string): Promise<{ ok: boolean; detail?: string }> => {
    const res = await fetch(`${BASE}/login`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }),
    });
    const body = await res.json().catch(() => ({}));
    return res.ok ? { ok: true } : { ok: false, detail: body.detail || `Sign-in failed (${res.status}).` };
  },
  live: () => get<{ items: CaseFile[]; error?: string }>("/live"),
  scanStatus: () => get<ScanStatus>("/scan/status"),
  startScan: async (): Promise<{ started: boolean; reason?: string; detail?: string }> => {
    const res = await fetch(`${BASE}/scan`, { method: "POST" });
    return res.json();
  },
  complianceNotify: async (payload: { author: string; status: string; channel?: string; mentionId?: string }) => {
    const res = await fetch(`${BASE}/compliance/notify`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    return res.json() as Promise<{ ok: boolean; message: string }>;
  },
};
