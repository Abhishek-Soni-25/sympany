// The monitored insurer. BRAND_NAME is target.name in config/config.yaml, so the posts, share of
// voice and reply times the API returns carry the insurer under this name.
export const BRAND_NAME = "Sympany";
export const BRAND_SHORT = "Sympany";

/** Sympany's competitor set (competitors.set in config/config.yaml), in display order. */
export const COMPETITOR_NAMES = ["CSS", "Helsana", "SWICA", "Visana"];

/** True for the monitored insurer's own row in a brand list. */
export const isOwnBrand = (name: string) => /sympany/i.test(name);
