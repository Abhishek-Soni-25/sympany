import { isOwnBrand } from "./brand";

// Chart colours (Sympany corporate design). Colour only carries meaning: Sympany berry marks
// Sympany's own data; a signal red, kept clear of the berry, marks negative sentiment and high
// risk; green is positive, warm grey is neutral. Competitors, channels and plain quantities sit
// in the Sympany lavender and sand families, so the berry always stands out.

export const BERRY = "#891350";        // Sympany berry (corporate design)
export const OWN = BERRY;              // Sympany's own data
export const RED = "#C8372D";          // negative sentiment / high risk
export const NAVY = "#4E4385";         // structural lavender (hubs, trend lines)
export const STEEL = "#7A6CB0";        // plain quantities (one-colour bar charts)
export const POSITIVE = "#2E7D4F";
export const NEUTRAL = "#B3AAA4";
export const GRID = "#EEE6DD";
export const AXIS = "#7A7075";

// Competitors, in order: four steps of the Sympany lavender family.
export const COMPETITOR_TINTS = ["#4E4385", "#7A6CB0", "#A79DCF", "#CFC9E6"];

export const sentimentColor = (s: string) => {
  const k = s.toLowerCase();
  return k.startsWith("neg") ? RED : k.startsWith("pos") ? POSITIVE : NEUTRAL;
};

/** Sympany in berry; competitors in lavender tints by their position in the list. */
export const brandColor = (name: string, i: number) =>
  isOwnBrand(name) ? OWN : COMPETITOR_TINTS[i % COMPETITOR_TINTS.length];

// Channels: lavender for the social channels (YouTube's three feeds share one hue), sand-browns
// for the review sources.
const CHANNEL_COLORS: Record<string, string> = {
  facebook: "#4E4385", instagram: "#7A6CB0", youtube_channel: "#9185BE", youtube: "#A79DCF",
  youtube_shorts: "#CFC9E6", quora: "#5C5160", x: "#2F2833",
  play_store: "#8C6A52", app_store: "#C4A285", google_maps: "#6B5444",
};
export const channelColor = (p: string) => CHANNEL_COLORS[p] ?? "#9A9095";

// Risk categories: reputational takes the signal red (the most common and most visible risk);
// the others use the risk scale's amber, a lavender and a warm slate, never a second red.
export const CATEGORY_COLORS: Record<string, string> = {
  REPUTATIONAL: RED, COMPLIANCE_CONDUCT: "#A35200", MARKET_ABUSE: "#6B6267", CYBER_OPERATIONAL: "#6E5FA6",
};
