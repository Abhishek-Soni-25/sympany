/** The URL as a link target if it is an http(s) link, else undefined. Post and author
 *  links come from scraped or user-supplied data, so a "javascript:" or "data:" URL must
 *  never become clickable. */
export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const u = new URL(url.trim());
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : undefined;
  } catch {
    return undefined;
  }
}
