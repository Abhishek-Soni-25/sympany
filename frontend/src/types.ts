export type Severity = "HIGH" | "MEDIUM" | "LOW" | "NONE";

export interface CaseFile {
  case_id: string;
  platform: string;
  rating?: number;                 // app / agency reviews: 1-5 stars
  source: string;
  timestamp: string;
  author_ref: string;
  raw_content: string;
  risk_category: string;
  severity: Severity;
  sentiment_polarity: string;
  sentiment_score: number;
  confidence: number;
  rationale: string;
  indicators: string[];
  mitigation_urgency: string;
  racm_ref: string;
  kri_ref: string;
  url: string | null;
  created_at: string;
  analysis_failed?: boolean;       // the AI analysis failed; retried on the next scan
}

export interface Stats {
  total_cases: number;
  by_severity: Record<string, number>;
  by_category: Record<string, number>;
  by_channel: Record<string, number>;
  latest: string | null;
}

// A single analysed item from the real Bright Data / Apify pipeline (/api/mentions).
export interface Mention {
  id: string;
  platform: string;
  provider: string | null;
  author: string;
  author_url: string | null;
  url: string | null;              // permalink — click to open & verify
  text: string;
  keyword: string | null;
  engagement: Record<string, number>;
  sentiment: "positive" | "neutral" | "negative";
  risk_category: string;
  severity: Severity;
  confidence: number;
  rationale: string;
  indicators: string[];
  timestamp: string;
  analysed_at: string;
  language?: string;               // main language of the post (Groq)
  author_type?: "individual" | "creator" | "media" | "brand" | "other";
  media_type?: "video" | "image" | "link" | "text";
  is_official?: boolean;           // posted by the brand's own account (outgoing)
  // "failed": the AI analysis failed (sentiment is then "failed"); the next scan retries it.
  analysis_status?: "ok" | "failed";
  retry_count?: number;
  engagement_updated_at?: string;  // likes / comments / views last refreshed by a scan
  rating?: number;                 // app / agency reviews: 1-5 stars
  app_version?: string;            // app reviews: the app version reviewed
}

// A collected competitor post (/api/competitors/mentions) — same shape, brand-tagged.
export interface CompetitorPost extends Mention {
  brand: string;
}

// Follower snapshots of the brand's own accounts (/api/followers).
export interface FollowerSnapshot { at: string; counts: Record<string, number>; }
export interface FollowerSummary {
  latest: FollowerSnapshot | null;
  previous: FollowerSnapshot | null;
  snapshots: FollowerSnapshot[];
}

// First-level response time per brand (/api/response-times).
export interface BrandResponseTime {
  handle: string;
  posts: number;
  comments: number;
  replied: number;
  reply_rate: number | null;
  avg_seconds: number | null;
  median_seconds: number | null;
  measured_at: string;
  by_platform?: Record<string, { comments: number; replied: number }>;
}
// A period in which a channel may have missed posts (/api/coverage).
export interface CoverageNote { channel: string; from: string | null; to: string; at: string; note: string; }

// One stored measurement per scan, so a date filter can show the reply time of a period.
export interface ResponseTimeEntry {
  measured_at: string;
  brands: Record<string, Pick<BrandResponseTime, "comments" | "replied" | "reply_rate" | "avg_seconds" | "median_seconds">>;
}
export interface ResponseTimes {
  measured_at: string | null;
  brands: Record<string, BrandResponseTime>;
  history?: ResponseTimeEntry[];
  measurements?: number;           // set when a date filter combines several measurements
  first_measured_at?: string;
}

// Per-account activity (/api/authors) — how many times an account posted about the keyword.
export interface AuthorActivity {
  author: string;
  platform: string;
  author_url: string | null;
  posts: number;
  negative: number;
  neutral: number;
  positive: number;
  flagged: number;
  latest_url: string | null;
  latest_at: string;
}

export interface Channel {
  name: string;
  enabled: boolean;
  mode: "live" | "demo";
  sources: string[];
}

export interface SovEntry {
  total: number;
  positive: number;
  neutral: number;
  negative: number;
  by_platform: Record<string, number>;
}
export interface CompetitorSov {
  own: SovEntry;
  competitors: Record<string, SovEntry>;
}

/** Today's Run Scan allowance (scan.manual_per_day; limit 0 = no limit). */
export interface ScanQuota {
  limit: number;
  used: number;
  available: boolean;
  last_ok_at: string | null;
  last_by: string | null;
}

export interface ScanStatus {
  running: boolean;
  last_run: string | null;
  last_stats: Record<string, unknown> | null;
  error: string | null;
  active_model: string | null;
  models: string[] | null;
  quota?: ScanQuota;
}
