/**
 * A site's country from its hostname alone -- the country-code top-level domain, with the
 * common second-level forms (`.ac.in`, `.co.uk`, `.gov.uk`) and the US-only generic ones
 * (`.edu`, `.gov`, `.mil`). Nothing is looked up anywhere: the landing promises that the
 * only requests made are to the site you name, and that promise stands. A generic TLD with
 * no country gives null, and the Earth simply keeps turning.
 *
 * Latitude and longitude are the country's rough centre, degrees; enough to turn the globe
 * to it and light a marker.
 */
export type Country = { code: string; name: string; lat: number; lon: number };

const T: Record<string, [string, number, number]> = {
  in: ["India", 22, 79], uk: ["United Kingdom", 54, -2], gb: ["United Kingdom", 54, -2], de: ["Germany", 51, 10],
  fr: ["France", 46.5, 2.5], jp: ["Japan", 36, 138], br: ["Brazil", -10, -53], au: ["Australia", -25, 134],
  cz: ["Czechia", 49.8, 15.5], ru: ["Russia", 60, 90], cn: ["China", 35, 104], us: ["United States", 39, -98],
  ca: ["Canada", 56, -106], mx: ["Mexico", 23, -102], ar: ["Argentina", -34, -64], cl: ["Chile", -33, -71],
  co: ["Colombia", 4, -73], pe: ["Peru", -10, -76], es: ["Spain", 40, -4], pt: ["Portugal", 39.5, -8],
  it: ["Italy", 42.5, 12.5], nl: ["Netherlands", 52.2, 5.3], be: ["Belgium", 50.6, 4.5], ch: ["Switzerland", 46.8, 8.2],
  at: ["Austria", 47.5, 14.5], pl: ["Poland", 52, 19.5], se: ["Sweden", 62, 15], no: ["Norway", 62, 10],
  dk: ["Denmark", 56, 10], fi: ["Finland", 64, 26], ie: ["Ireland", 53.2, -8], is: ["Iceland", 65, -18],
  gr: ["Greece", 39, 22], tr: ["Türkiye", 39, 35], ua: ["Ukraine", 49, 32], ro: ["Romania", 46, 25],
  hu: ["Hungary", 47, 19.5], sk: ["Slovakia", 48.7, 19.7], si: ["Slovenia", 46.1, 14.8], hr: ["Croatia", 45.2, 15.5],
  rs: ["Serbia", 44, 21], bg: ["Bulgaria", 42.7, 25.5], lt: ["Lithuania", 55.2, 24], lv: ["Latvia", 57, 25],
  ee: ["Estonia", 58.6, 25], il: ["Israel", 31.5, 34.9], ae: ["United Arab Emirates", 24, 54], sa: ["Saudi Arabia", 24, 45],
  eg: ["Egypt", 26, 30], za: ["South Africa", -29, 25], ng: ["Nigeria", 9.5, 8], ke: ["Kenya", 0.5, 38],
  ma: ["Morocco", 32, -6], pk: ["Pakistan", 30, 70], bd: ["Bangladesh", 24, 90], lk: ["Sri Lanka", 7.5, 80.7],
  np: ["Nepal", 28.2, 84], sg: ["Singapore", 1.35, 103.8], my: ["Malaysia", 4, 102], id: ["Indonesia", -2, 118],
  th: ["Thailand", 15, 101], vn: ["Vietnam", 16, 107], ph: ["Philippines", 12.5, 122], kr: ["South Korea", 36, 128],
  tw: ["Taiwan", 23.7, 121], hk: ["Hong Kong", 22.3, 114.2], nz: ["New Zealand", -41, 174], eu: ["European Union", 50, 9],
};

const US_ONLY = new Set(["edu", "gov", "mil"]);

export function countryOf(host: string): Country | null {
  const labels = host.trim().toLowerCase().replace(/\.$/, "").split(".").filter(Boolean);
  if (labels.length < 2) return null;
  const tld = labels[labels.length - 1]!;
  if (US_ONLY.has(tld)) return make("us");
  if (tld.length !== 2) return null;
  const entry = T[tld];
  if (!entry) return null;
  // `.ac.in`, `.co.uk`, `.com.au`: the second label is organisational; the country is the last.
  return make(tld);
}

function make(code: string): Country | null {
  const e = T[code];
  return e ? { code, name: e[0], lat: e[1], lon: e[2] } : null;
}

/** The host of an address as typed, without scheme, path or port; null if it is not one. */
export function hostOf(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  try {
    const u = new URL(/^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`);
    return u.hostname.includes(".") ? u.hostname : null;
  } catch {
    return null;
  }
}
