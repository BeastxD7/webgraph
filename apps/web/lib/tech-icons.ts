/**
 * The mark beside a detected technology's name.
 *
 * One style for every mark: Simple Icons (CC0, 24-unit grid, one colour), tinted with our
 * own tokens rather than each brand's colour, so a stack of eight technologies reads as one
 * list and not eight logos shouting. The icon is decorative and always sits beside the
 * visible name -- never alone -- and a technology whose mark is not in the set (or whose
 * owner has withdrawn it from Simple Icons: Amazon, Microsoft, Adobe, LinkedIn) gets the one
 * neutral glyph, `GENERIC_PATH`, never a neighbouring brand.
 *
 * Only the icons named below are imported, so the bundle carries these few kilobytes and
 * not the 3,400-icon set; `tech-icons.test.ts` proves every name the engine can emit
 * (`packages/engine/src/webgraph/profile/technology.py`, `profile/fingerprint.py`,
 * `fetch/js/collect.js`) resolves to a mark or to an explicit `null` -- a decision, not a
 * fallback. Names are matched case-insensitively, because the fingerprint pass emits
 * `next.js` and `wordpress` where the technology pass emits `Next.js` and `WordPress`.
 *
 * Marks are trademarks of their owners, shown to identify the detected technology; the
 * note is repeated where the list renders and in `public/ASSETS.md`.
 */

import type { SimpleIcon } from "simple-icons";
import {
  siAkamai,
  siAlgolia,
  siAlpinedotjs,
  siAngular,
  siApache,
  siAstra,
  siAstro,
  siAxios,
  siBigcommerce,
  siBootstrap,
  siBulma,
  siCaddy,
  siChartdotjs,
  siCloudflare,
  siContentful,
  siCss,
  siD3,
  siDocusaurus,
  siDotnet,
  siDrupal,
  siElementor,
  siEleventy,
  siEmberdotjs,
  siEnvoyproxy,
  siExpress,
  siFacebook,
  siFastly,
  siFontawesome,
  siFramer,
  siGatsby,
  siGhost,
  siGithubpages,
  siGoogleanalytics,
  siGooglefonts,
  siGoogletagmanager,
  siGsap,
  siHotjar,
  siHtml5,
  siHtmx,
  siHubspot,
  siHugo,
  siIntercom,
  siJavascript,
  siJekyll,
  siJoomla,
  siJquery,
  siJsdelivr,
  siLaravel,
  siLeaflet,
  siLivewire,
  siLodash,
  siLucide,
  siMailchimp,
  siMapbox,
  siMatomo,
  siMixpanel,
  siMui,
  siNetlify,
  siNextdotjs,
  siNginx,
  siNuxt,
  siOpenssl,
  siPaypal,
  siPerl,
  siPhp,
  siPlausibleanalytics,
  siPosthog,
  siPreact,
  siPrestashop,
  siPwa,
  siQwik,
  siRadixui,
  siReact,
  siReacthookform,
  siReactquery,
  siReactrouter,
  siRemix,
  siRubyonrails,
  siSanity,
  siSentry,
  siShadcnui,
  siShopify,
  siSphinx,
  siSquarespace,
  siStimulus,
  siStrapi,
  siStripe,
  siSvelte,
  siSwiper,
  siTailwindcss,
  siThreedotjs,
  siTurbo,
  siUmami,
  siUnpkg,
  siVercel,
  siVuedotjs,
  siWebflow,
  siWix,
  siWoocommerce,
  siWordpress,
  siYoast,
  siZod,
} from "simple-icons";

/**
 * The neutral glyph: a cube outline on the same 24-unit grid, drawn in our stroke style
 * (1.5 px, round joins, `fill="none"`) rather than as a fill like the marks -- so it reads
 * as "a component" and cannot be mistaken for anyone's logo.
 */
export const GENERIC_PATH =
  "M12 2.75 20.25 7.5v9L12 21.25 3.75 16.5v-9ZM12 12l8.25-4.5M12 12v9.25M12 12 3.75 7.5";

/**
 * The engine's display name (the key), and its mark. `null` is a decision: the technology
 * has no monochrome mark in the set, or the one that exists is a neighbouring brand's
 * (Framer's for Framer Motion, LottieFiles' for Lottie, Astro's for Starlight), and a wrong
 * mark is worse than none. Grouped as the engine's own CATEGORIES order.
 */
const ICONS: Readonly<Record<string, SimpleIcon | null>> = {
  // JavaScript frameworks
  "Next.js": siNextdotjs,
  React: siReact,
  Preact: siPreact,
  "Vue.js": siVuedotjs,
  Nuxt: siNuxt,
  Svelte: siSvelte,
  Angular: siAngular,
  Astro: siAstro,
  Gatsby: siGatsby,
  Remix: siRemix,
  Qwik: siQwik,
  "Alpine.js": siAlpinedotjs,
  "Ember.js": siEmberdotjs,
  HTMX: siHtmx,
  "React Router": siReactrouter,
  // Static site generators
  Hugo: siHugo,
  Jekyll: siJekyll,
  Eleventy: siEleventy,
  Docusaurus: siDocusaurus,
  Sphinx: siSphinx,
  Starlight: null,
  VuePress: null,
  MkDocs: null,
  // CMS
  WordPress: siWordpress,
  Drupal: siDrupal,
  Joomla: siJoomla,
  Ghost: siGhost,
  Contentful: siContentful,
  Sanity: siSanity,
  Strapi: siStrapi,
  // Ecommerce
  Shopify: siShopify,
  WooCommerce: siWoocommerce,
  BigCommerce: siBigcommerce,
  PrestaShop: siPrestashop,
  Magento: null,
  Stripe: siStripe,
  PayPal: siPaypal,
  // Website builders
  Webflow: siWebflow,
  Wix: siWix,
  Squarespace: siSquarespace,
  Framer: siFramer,
  // UI frameworks
  "Tailwind CSS": siTailwindcss,
  Bootstrap: siBootstrap,
  Bulma: siBulma,
  Foundation: null,
  "Material UI": siMui,
  "Font Awesome": siFontawesome,
  "Radix UI": siRadixui,
  "shadcn/ui": siShadcnui,
  cmdk: null,
  Sonner: null,
  Vaul: null,
  Elementor: siElementor,
  Astra: siAstra,
  Divi: null,
  WPBakery: null,
  "Beaver Builder": null,
  Kadence: null,
  GeneratePress: null,
  OceanWP: null,
  // JavaScript libraries
  jQuery: siJquery,
  Lodash: siLodash,
  Axios: siAxios,
  "Chart.js": siChartdotjs,
  D3: siD3,
  "Three.js": siThreedotjs,
  GSAP: siGsap,
  Swiper: siSwiper,
  Leaflet: siLeaflet,
  "Mapbox GL JS": siMapbox,
  Algolia: siAlgolia,
  "React Hook Form": siReacthookform,
  "TanStack Query": siReactquery,
  Zod: siZod,
  Turbo: siTurbo,
  Stimulus: siStimulus,
  Livewire: siLivewire,
  "Framer Motion": null,
  Lottie: null,
  "Moment.js": null,
  Modernizr: null,
  "Popper.js": null,
  Slick: null,
  "Owl Carousel": null,
  AOS: null,
  Lenis: null,
  "Embla Carousel": null,
  Zustand: null,
  "core-js": null,
  "class-variance-authority": null,
  // Font scripts
  "Google Font API": siGooglefonts,
  Lucide: siLucide,
  "Adobe Fonts": null,
  // Analytics
  "Google Analytics": siGoogleanalytics,
  Plausible: siPlausibleanalytics,
  Matomo: siMatomo,
  Mixpanel: siMixpanel,
  Hotjar: siHotjar,
  PostHog: siPosthog,
  Umami: siUmami,
  "Facebook Pixel": siFacebook,
  Amplitude: null,
  Segment: null,
  "LinkedIn Insight": null,
  "Microsoft Clarity": null,
  Tinybird: null,
  // Tag managers
  "Google Tag Manager": siGoogletagmanager,
  Tealium: null,
  // Marketing
  HubSpot: siHubspot,
  Mailchimp: siMailchimp,
  Intercom: siIntercom,
  Drift: null,
  Crisp: null,
  "Tawk.to": null,
  Klaviyo: null,
  // Security
  Cloudflare: siCloudflare,
  reCAPTCHA: null,
  hCaptcha: null,
  HSTS: null,
  // Performance
  "HTTP/3": null,
  "Priority Hints": null,
  // Miscellaneous
  PWA: siPwa,
  Sentry: siSentry,
  "Yoast SEO": siYoast,
  "Open Graph": null,
  WPForms: null,
  "Contact Form 7": null,
  // CDN and hosting
  Fastly: siFastly,
  Akamai: siAkamai,
  jsDelivr: siJsdelivr,
  unpkg: siUnpkg,
  cdnjs: null,
  Vercel: siVercel,
  Netlify: siNetlify,
  "GitHub Pages": siGithubpages,
  "Amazon S3": null,
  "Amazon CloudFront": null,
  AWS: null,
  // Web servers and languages
  nginx: siNginx,
  "Apache HTTP Server": siApache,
  Caddy: siCaddy,
  Envoy: siEnvoyproxy,
  LiteSpeed: null,
  "Microsoft IIS": null,
  OpenSSL: siOpenssl,
  mod_perl: siPerl,
  PHP: siPhp,
  "ASP.NET": siDotnet,
  Express: siExpress,
  "Ruby on Rails": siRubyonrails,
  Laravel: siLaravel,
  // The page's own languages, for the places that name them
  HTML5: siHtml5,
  CSS: siCss,
  JavaScript: siJavascript,
};

/**
 * Other spellings and the products that share a mark with their parent (Google Analytics 4
 * with Google Analytics, Cloudflare Turnstile with Cloudflare). Keys are matched
 * case-insensitively; values are keys of `ICONS`.
 */
const ALIASES: Readonly<Record<string, string>> = {
  next: "Next.js",
  nextjs: "Next.js",
  vue: "Vue.js",
  vuejs: "Vue.js",
  sveltekit: "Svelte",
  nuxtjs: "Nuxt",
  "alpine": "Alpine.js",
  ember: "Ember.js",
  "google analytics 4": "Google Analytics",
  ga4: "Google Analytics",
  "google fonts": "Google Font API",
  "font awesome cdn": "Font Awesome",
  "jquery ui": "jQuery",
  "cloudflare bot management": "Cloudflare",
  "cloudflare turnstile": "Cloudflare",
  "cloudflare web analytics": "Cloudflare",
  "cloudflare r2": "Cloudflare",
  "cloudflare pages": "Cloudflare",
  "vercel analytics": "Vercel",
  "vercel speed insights": "Vercel",
  "material-ui": "Material UI",
  mui: "Material UI",
  tailwind: "Tailwind CSS",
  apache: "Apache HTTP Server",
  "apache http server": "Apache HTTP Server",
  "plausible analytics": "Plausible",
  "react query": "TanStack Query",
  "mapbox": "Mapbox GL JS",
  "three": "Three.js",
  "threejs": "Three.js",
  "d3.js": "D3",
  rails: "Ruby on Rails",
  html: "HTML5",
  css3: "CSS",
  js: "JavaScript",
  "vanilla js": "JavaScript",
  "vanilla javascript": "JavaScript",
  "amazon web services": "AWS",
  cloudfront: "Amazon CloudFront",
  s3: "Amazon S3",
  envoyproxy: "Envoy",
  "envoy proxy": "Envoy",
  "asp.net core": "ASP.NET",
  "google tag manager (gtm)": "Google Tag Manager",
  gtm: "Google Tag Manager",
  "hubspot cms": "HubSpot",
  opengraph: "Open Graph",
  "iis": "Microsoft IIS",
};

export interface TechMark {
  /** SVG path data on the 24-unit grid. A fill for a brand mark; a stroke for the generic glyph. */
  path: string;
  /** The mark's own title (Simple Icons'), or "Technology" for the generic glyph. */
  title: string;
  /** True when this is the neutral glyph, drawn as an outline rather than a fill. */
  generic: boolean;
}

const GENERIC: TechMark = { path: GENERIC_PATH, title: "Technology", generic: true };

function normalise(name: string): string {
  return name.trim().toLowerCase().replace(/\s+/g, " ");
}

/** normalised name -> canonical key of ICONS. Built once. */
const CANONICAL: ReadonlyMap<string, string> = (() => {
  const map = new Map<string, string>();
  for (const key of Object.keys(ICONS)) map.set(normalise(key), key);
  for (const [alias, key] of Object.entries(ALIASES)) {
    if (!(key in ICONS)) throw new Error(`tech-icons: alias "${alias}" points at unknown "${key}"`);
    map.set(normalise(alias), key);
  }
  return map;
})();

/**
 * How a name resolves, for the test and the contact sheet: `"icon"` when a mark is mapped,
 * `"generic"` when the map says so explicitly, `undefined` when the name is unknown to the
 * map and the generic glyph is a fallback rather than a decision.
 */
export function techEntry(name: string): { key: string; kind: "icon" | "generic" } | undefined {
  const key = CANONICAL.get(normalise(name));
  if (key === undefined) return undefined;
  return { key, kind: ICONS[key] ? "icon" : "generic" };
}

/** The mark for a technology name; the generic glyph when the name is unmapped. */
export function techIcon(name: string): TechMark {
  const entry = techEntry(name);
  const icon = entry ? ICONS[entry.key] : null;
  if (!icon) return GENERIC;
  return { path: icon.path, title: icon.title, generic: false };
}

/** Every canonical name in the map, with its Simple Icons slug or `null` (generic). */
export const MAPPED_TECH: ReadonlyArray<{ name: string; slug: string | null }> = Object.entries(
  ICONS,
).map(([name, icon]) => ({ name, slug: icon ? icon.slug : null }));

/** The alias table, for the test's alias-group accounting. */
export const TECH_ALIASES: Readonly<Record<string, string>> = ALIASES;
