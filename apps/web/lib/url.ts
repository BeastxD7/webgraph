/**
 * Input normalisation for the URL prompt.
 *
 * People type `example.com`. The engine needs an absolute URL, and getting this wrong
 * sends an unusable value into a crawl that then fails several seconds later with a
 * confusing message, so it is fixed at the point of entry instead.
 */

export interface NormalizedUrl {
  ok: boolean;
  url: string;
  reason?: string;
}

export function normalizeInput(raw: string): NormalizedUrl {
  const trimmed = raw.trim();
  if (!trimmed) return { ok: false, url: "", reason: "Enter a website address." };

  const candidate = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;

  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return { ok: false, url: trimmed, reason: "That does not look like a web address." };
  }

  // A hostname with no dot is either `localhost` or a typo. Allowing localhost keeps the
  // tool usable against a site you are developing.
  const isLocal = parsed.hostname === "localhost" || /^\d+(\.\d+){3}$/.test(parsed.hostname);
  if (!isLocal && !parsed.hostname.includes(".")) {
    return { ok: false, url: trimmed, reason: "That does not look like a web address." };
  }

  return { ok: true, url: parsed.toString() };
}
