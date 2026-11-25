// Display names for values stored in code form (platform keys, risk categories).

const PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube",
  youtube_channel: "YouTube channel",
  youtube_shorts: "YouTube Shorts",
  facebook: "Facebook",
  instagram: "Instagram",
  quora: "Quora",
  linkedin: "LinkedIn",
  reddit: "Reddit",
  telegram: "Telegram",
  tiktok: "TikTok",
  x: "X",
  play_store: "Play Store",
  app_store: "App Store",
  google_maps: "Google Maps",
  whatsapp: "WhatsApp",
};

/** "youtube_shorts" -> "YouTube Shorts"; unknown keys become "Some name". */
export function platformLabel(p: string): string {
  if (PLATFORM_LABELS[p]) return PLATFORM_LABELS[p];
  const s = p.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** A chart label: platform keys get their display name ("youtube_shorts" -> "YouTube Shorts"),
 *  anything else is shown as stored. */
export function displayName(name: string): string {
  return PLATFORM_LABELS[name] ? PLATFORM_LABELS[name] : name;
}

/** "CYBER_OPERATIONAL" -> "Cyber operational". */
export function categoryLabel(c: string): string {
  const s = c.replace(/_/g, " ").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
