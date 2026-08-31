"""Technology fingerprinting across markup, headers and cookies.

Rules are hand-written rather than imported. Every maintained Wappalyzer ruleset --
`enthec/webappanalyzer`, `HTTPArchive/wappalyzer`, `dochne/wappalyzer` -- is **GPL-3.0**,
verified via the GitHub API, and vendoring any of them would force this Apache-2.0 engine to
GPL. There is no permissively-licensed alternative, so the rules here are original.

Three signal sources, because each carries things the others cannot:

- **Response headers** are the only place server-side technology appears. `Apache/2.4.37`,
  `PHP/7.4.33` and `OpenSSL/1.1.1k` live in `Server` and `X-Powered-By` and are invisible in
  the markup. An earlier version of the profiler read only HTML and reported "none detected"
  for a site running all three.
- **Markup** carries client-side frameworks, libraries, analytics and fonts.
- **Cookies** identify platforms that are otherwise silent.

Versions are captured where the signal exposes one, since "jQuery" and "jQuery 3.6.0" are
different facts -- the second tells you whether it is a decade out of date.

**Patterns must match implementation, never prose.** A bare word matches a docs site that
merely *documents* the technology: `docs.astro.build` was reported as running Strapi and
Alpine.js purely because its sidebar links to `/guides/cms/strapi/` and
`/guides/integrations-guide/alpinejs/`. Every rule therefore anchors to structure -- a
`src`/`href` attribute, a generator meta tag, a namespaced class, a JavaScript global -- so
that writing *about* a technology cannot be mistaken for using it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "CATEGORIES",
    "IMPLICATIONS",
    "TECH_RULES",
    "RuntimeEvidence",
    "TechRule",
    "Technology",
    "detect_technologies",
    "merge_technologies",
]

CATEGORIES: Final[tuple[str, ...]] = (
    "JavaScript frameworks",
    "JavaScript libraries",
    "UI frameworks",
    "Static site generators",
    "CMS",
    "Ecommerce",
    "Website builders",
    "Analytics",
    "Tag managers",
    "Font scripts",
    "Web servers",
    "Programming languages",
    "Web server extensions",
    "CDN",
    "Security",
    "Marketing",
    "Hosting",
    "Performance",
    "Miscellaneous",
)


@dataclass(frozen=True, slots=True)
class RuntimeEvidence:
    """Everything a rendered fetch observes that a bare HTTP request cannot.

    Carried as one object rather than five parameters because it travels together through
    four call layers -- render, resolve, pipeline, profile -- and adding a signal source
    should not mean editing every signature on the way down.

    Empty by default, so a static-only fetch simply contributes nothing and every rule that
    depends on runtime evidence declines to fire rather than guessing.
    """

    versions: Mapping[str, str] = field(default_factory=dict)
    """Technology name -> version, read from the live page by an explicit probe."""

    custom_globals: tuple[str, ...] = ()
    """Every name the page added to `window`, diffed against a pristine one."""

    requests: tuple[str, ...] = ()
    """Every URL requested while loading."""

    cookies: Mapping[str, str] = field(default_factory=dict)
    """The browser's cookie jar after load, including third-party writes."""

    bundle_source: str = ""
    """Concatenated text of the page's own JavaScript bundles, when fetched."""

    @property
    def present(self) -> bool:
        return bool(
            self.versions or self.custom_globals or self.requests or self.cookies
            or self.bundle_source
        )


@dataclass(frozen=True, slots=True)
class Technology:
    name: str
    category: str
    version: str | None = None
    confidence: int = 100
    evidence: str = ""

    def label(self) -> str:
        return f"{self.name} {self.version}" if self.version else self.name


@dataclass(frozen=True, slots=True)
class TechRule:
    """One fingerprint, over any of six signal sources.

    | field | matched against |
    |---|---|
    | `html` | the raw markup |
    | `header` | a named response header |
    | `cookie` | a cookie **name**, from the browser jar or `Set-Cookie` |
    | `js` | the **name** of a global the page added to `window` |
    | `request` | any URL the page requested while loading |
    | `source` | the text of the page's own JavaScript bundles |

    A capture group named `version` in any pattern is extracted as the version.

    The last three are what a browser extension has and a bare fetch does not, and they
    carry most of what markup cannot: a service invisible in the HTML is unmistakable in the
    network log, and a bundled library that exposes no global is still named in its own
    source.
    """

    name: str
    category: str
    html: re.Pattern[str] | None = None
    header: tuple[str, re.Pattern[str]] | None = None
    cookie: re.Pattern[str] | None = None
    js: re.Pattern[str] | None = None
    request: re.Pattern[str] | None = None
    source: re.Pattern[str] | None = None
    confidence: int = 100


def _h(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def _rule(
    name: str,
    category: str,
    *,
    html: str | None = None,
    header: tuple[str, str] | None = None,
    cookie: str | None = None,
    js: str | None = None,
    request: str | None = None,
    source: str | None = None,
    confidence: int = 100,
) -> TechRule:
    return TechRule(
        name=name,
        category=category,
        html=_h(html) if html else None,
        header=(header[0], _h(header[1])) if header else None,
        cookie=_h(cookie) if cookie else None,
        js=_h(js) if js else None,
        request=_h(request) if request else None,
        source=_h(source) if source else None,
        confidence=confidence,
    )


TECH_RULES: Final[tuple[TechRule, ...]] = (
    # --- Web servers, languages, server extensions (headers only) ---
    _rule("Apache HTTP Server", "Web servers", header=("server", r"Apache(?:/(?P<version>[\d.]+))?")),
    _rule("nginx", "Web servers", header=("server", r"nginx(?:/(?P<version>[\d.]+))?")),
    _rule("Microsoft IIS", "Web servers", header=("server", r"Microsoft-IIS(?:/(?P<version>[\d.]+))?")),
    _rule("LiteSpeed", "Web servers", header=("server", r"LiteSpeed")),
    _rule("Caddy", "Web servers", header=("server", r"Caddy")),
    _rule("Envoy", "Web servers", header=("server", r"envoy")),
    _rule("PHP", "Programming languages", header=("x-powered-by", r"PHP(?:/(?P<version>[\d.]+))?")),
    _rule("PHP", "Programming languages", header=("set-cookie", r"PHPSESSID"), confidence=80),
    _rule("ASP.NET", "Programming languages", header=("x-powered-by", r"ASP\.NET")),
    _rule("Express", "Programming languages", header=("x-powered-by", r"Express")),
    _rule("Ruby on Rails", "Programming languages", header=("x-powered-by", r"Phusion Passenger")),
    _rule("OpenSSL", "Web server extensions", header=("server", r"OpenSSL(?:/(?P<version>[\d.\w]+))?")),
    _rule("mod_perl", "Web server extensions", header=("server", r"mod_perl(?:/(?P<version>[\d.]+))?")),

    # --- CDN / hosting ---
    _rule("Cloudflare", "CDN", header=("server", r"cloudflare")),
    _rule("Fastly", "CDN", header=("x-served-by", r"cache-")),
    _rule("Amazon CloudFront", "CDN", header=("x-amz-cf-id", r".")),
    _rule("Akamai", "CDN", header=("x-akamai-transformed", r".")),
    _rule("Vercel", "Hosting", header=("server", r"Vercel")),
    _rule("Vercel", "Hosting", header=("x-vercel-id", r".")),
    _rule("Netlify", "Hosting", header=("server", r"Netlify")),
    _rule("GitHub Pages", "Hosting", header=("server", r"GitHub\.com")),
    _rule("Amazon S3", "Hosting", header=("server", r"AmazonS3")),

    # ------------------------------------------------------------------
    # Runtime signals: globals, network requests, cookies, bundle source
    # ------------------------------------------------------------------
    # These are the rules a bare HTTP fetch cannot evaluate. They exist because the markup
    # is frequently silent about what a page is actually running: a Vite bundle names no
    # framework, an analytics SDK injected at runtime appears in no `<script>` tag, and a
    # CDN's bot challenge is a request and a cookie and nothing else.

    # --- Product analytics and error tracking ---
    _rule("PostHog", "Analytics", js=r"^(?:posthog|__PosthogExtensions__|_POSTHOG_REMOTE_CONFIG)$"),
    _rule("PostHog", "Analytics", request=r"https?://[^/]*\.i\.posthog\.com/"),
    _rule("PostHog", "Analytics", cookie=r"^ph_phc_"),
    _rule("Tinybird", "Analytics", js=r"^Tinybird$"),
    _rule("Tinybird", "Analytics", request=r"tinybird\.co|/v0/events"),
    _rule("Google Analytics", "Analytics", js=r"^(?:gtag|dataLayer|google_tag_data)$"),
    _rule("Google Analytics", "Analytics", request=r"google-analytics\.com|/gtag/js\?id=G-"),
    _rule("Google Tag Manager", "Tag managers", js=r"^google_tag_manager$"),
    _rule("Google Tag Manager", "Tag managers", request=r"googletagmanager\.com/gtm\.js"),
    _rule("Facebook Pixel", "Analytics", js=r"^_?fbq$"),
    _rule("Facebook Pixel", "Analytics", cookie=r"^_fbp$"),
    _rule("Facebook Pixel", "Analytics", request=r"connect\.facebook\.net/[a-z_]+/fbevents\.js"),
    _rule("Hotjar", "Analytics", js=r"^(?:hj|_hjSettings)$"),
    _rule("Hotjar", "Analytics", request=r"static\.hotjar\.com"),
    _rule("Microsoft Clarity", "Analytics", js=r"^clarity$"),
    _rule("Microsoft Clarity", "Analytics", request=r"clarity\.ms"),
    _rule("Segment", "Analytics", request=r"cdn\.segment\.(?:com|io)"),
    _rule("Amplitude", "Analytics", js=r"^amplitude$"),
    _rule("Mixpanel", "Analytics", js=r"^mixpanel$"),
    _rule("Plausible", "Analytics", js=r"^plausible$"),
    _rule("Matomo", "Analytics", js=r"^(?:_paq|Matomo|Piwik)$"),
    _rule("Sentry", "Miscellaneous", js=r"^(?:__SENTRY__|Sentry)$"),
    _rule("Sentry", "Miscellaneous", request=r"\.ingest\.(?:us\.|de\.)?sentry\.io|browser\.sentry-cdn\.com"),
    _rule("Vercel Analytics", "Analytics", request=r"/_vercel/insights/"),
    _rule("Vercel Speed Insights", "Performance", request=r"/_vercel/speed-insights/"),
    _rule("Cloudflare Web Analytics", "Analytics", request=r"static\.cloudflareinsights\.com"),

    # --- Security / bot management (a request and a cookie, nothing in the markup) ---
    _rule("Cloudflare Bot Management", "Security", cookie=r"^__cf_bm$"),
    _rule("Cloudflare Bot Management", "Security", request=r"/cdn-cgi/challenge-platform/"),
    _rule("Cloudflare Turnstile", "Security", request=r"challenges\.cloudflare\.com/turnstile"),
    _rule("hCaptcha", "Security", request=r"hcaptcha\.com/1/api\.js"),
    _rule("reCAPTCHA", "Security", request=r"google\.com/recaptcha/"),

    # --- Frameworks and routers that announce themselves on `window` ---
    _rule("React Router", "JavaScript frameworks", js=r"^__react[Rr]outer(?:Version|Context)$"),
    _rule("Next.js", "JavaScript frameworks", js=r"^__NEXT_DATA__$"),
    _rule("Nuxt", "JavaScript frameworks", js=r"^__NUXT__$"),
    _rule("Remix", "JavaScript frameworks", js=r"^__remix(?:Context|Manifest)$"),
    _rule("SvelteKit", "JavaScript frameworks", js=r"^__sveltekit_"),
    _rule("Gatsby", "Static site generators", js=r"^___gatsby$"),
    _rule("Qwik", "JavaScript frameworks", js=r"^qwikevents$"),
    _rule("Alpine.js", "JavaScript frameworks", js=r"^(?:Alpine|deferLoadingAlpine)$"),
    _rule("htmx", "JavaScript libraries", js=r"^htmx$"),
    _rule("Turbo", "JavaScript libraries", js=r"^Turbo$"),
    _rule("Livewire", "JavaScript libraries", js=r"^Livewire$"),
    _rule("Stimulus", "JavaScript libraries", js=r"^Stimulus$"),

    # --- Libraries with a global but no markup trace ---
    _rule("core-js", "JavaScript libraries", js=r"^__core-js_shared__$"),
    _rule("Lenis", "JavaScript libraries", js=r"^lenis(?:Version)?$"),
    _rule("GSAP", "JavaScript libraries", js=r"^(?:gsap|ScrollTrigger|TweenMax)$"),
    _rule("Framer Motion", "JavaScript libraries", js=r"^__FRAMER_MOTION__$"),
    _rule("Three.js", "JavaScript libraries", js=r"^THREE$"),
    _rule("Lottie", "JavaScript libraries", js=r"^(?:lottie|bodymovin)$"),
    _rule("Chart.js", "JavaScript libraries", js=r"^Chart$"),
    _rule("Leaflet", "JavaScript libraries", request=r"unpkg\.com/leaflet|leaflet[.-][\d.]*(?:min\.)?js"),
    _rule("Mapbox GL JS", "JavaScript libraries", js=r"^mapboxgl$"),
    _rule("Algolia", "JavaScript libraries", js=r"^(?:algoliasearch|instantsearch)$"),
    _rule("Stripe", "Ecommerce", js=r"^Stripe$"),
    _rule("Stripe", "Ecommerce", request=r"js\.stripe\.com"),
    _rule("Shopify", "Ecommerce", js=r"^Shopify$"),
    _rule("Klaviyo", "Marketing", js=r"^(?:klaviyo|_learnq)$"),
    _rule("HubSpot", "Marketing", js=r"^(?:_hsq|hbspt)$"),
    _rule("Intercom", "Marketing", js=r"^(?:Intercom|intercomSettings)$"),
    _rule("Drift", "Marketing", js=r"^(?:drift|driftt)$"),
    _rule("Crisp", "Marketing", js=r"^\$crisp$"),

    # --- Hosting inferred from where the assets come from ---
    _rule("Cloudflare R2", "Hosting", request=r"https?://[^/]*\.r2\.dev/"),
    _rule("Amazon S3", "Hosting", request=r"https?://[^/]*\.s3[.-][a-z0-9-]*\.amazonaws\.com/"),
    _rule("jsDelivr", "CDN", request=r"cdn\.jsdelivr\.net"),
    _rule("unpkg", "CDN", request=r"unpkg\.com"),
    _rule("cdnjs", "CDN", request=r"cdnjs\.cloudflare\.com"),

    # --- Read out of the page's own bundle ---
    # Radix and shadcn only mount their data attributes once a component opens, so a
    # homepage that ships a dialog but never opens it looks like neither. The bundle
    # still names them. Source patterns are anchored to package or attribute strings so
    # a comment mentioning the library does not match.
    _rule("Radix UI", "UI frameworks", source=r"@radix-ui/|data-radix-[a-z-]+", confidence=90),
    _rule("shadcn/ui", "UI frameworks", source=r'data-slot=|"data-slot"|class-variance-authority', confidence=70),
    _rule("Tailwind CSS", "UI frameworks", source=r"tailwind-merge|tw-merge|tailwindcss", confidence=80),
    _rule("React", "JavaScript frameworks", source=r"react-dom|__reactContainer\$", confidence=90),
    _rule("Vue.js", "JavaScript frameworks", source=r"__vue_app__|@vue/runtime-core", confidence=90),
    _rule("Zustand", "JavaScript libraries", source=r"zustand", confidence=70),
    _rule("TanStack Query", "JavaScript libraries", source=r"@tanstack/(?:react-)?query", confidence=80),
    _rule("Embla Carousel", "JavaScript libraries", source=r"embla-carousel", confidence=80),
    _rule("Swiper", "JavaScript libraries", source=r"swiper-slide|swiper-wrapper", confidence=80),
    _rule("Sonner", "UI frameworks", source=r"\bsonner\b", confidence=80),
    _rule("cmdk", "UI frameworks", source=r"\bcmdk\b", confidence=80),
    _rule("Vaul", "UI frameworks", source=r"\bvaul\b", confidence=80),
    _rule("Zod", "JavaScript libraries", source=r"\bzod\b", confidence=75),
    _rule("React Hook Form", "JavaScript libraries", source=r"react-hook-form", confidence=85),
    _rule("Framer Motion", "JavaScript libraries", source=r"framer-motion", confidence=85),
    _rule("Lucide", "Font scripts", source=r"lucide-react", confidence=85),
    _rule("class-variance-authority", "JavaScript libraries", source=r"class-variance-authority", confidence=85),

    # --- Component libraries, icon sets and scroll/motion runtimes ---
    # Anchored to the attributes these libraries actually emit. A page that merely writes
    # about Radix or Lucide has no `data-radix-*` attribute and no `class="lucide ..."`.
    _rule("Radix UI", "UI frameworks", html=r"data-radix-[a-z-]+"),
    _rule("Lucide", "Font scripts", html=r"class=[\"'][^\"']*\blucide\s+lucide-[a-z-]+"),
    _rule("Lenis", "JavaScript libraries", html=r"class=[\"'][^\"']*\blenis\b"),
    # Responsive-prefixed utilities are close to unique to Tailwind; no other framework
    # puts `md:` in a class name. Matching a single utility keyword would fire on prose.
    _rule(
        "Tailwind CSS",
        "UI frameworks",
        html=r"class=[\"'][^\"']*\b(?:sm|md|lg|xl|2xl):[a-z][a-z0-9-]*(?:-[a-z0-9./\[\]]+)?\b",
        confidence=85,
    ),

    # --- Product analytics loaded as modules (no global to probe) ---
    _rule("PostHog", "Analytics", html=r"posthog\.init\(|(?:src|href)=[\"'][^\"']*posthog"),
    _rule("PostHog", "Analytics", html=r"(?:us|eu)-assets\.i\.posthog\.com", confidence=70),
    _rule("Tinybird", "Analytics", html=r"(?:src|href)=[\"'][^\"']*tinybird|api\.tinybird\.co"),
    _rule("Plausible", "Analytics", html=r"(?:src|href)=[\"'][^\"']*plausible\.io"),
    _rule("Umami", "Analytics", html=r"(?:src|href)=[\"'][^\"']*umami"),
    _rule("Vercel Analytics", "Analytics", html=r"(?:src|href)=[\"'][^\"']*/_vercel/insights"),

    # --- Standards a page either implements or does not ---
    _rule("Open Graph", "Miscellaneous", html=r"<meta[^>]+property=[\"']og:"),
    _rule("PWA", "Miscellaneous", html=r"<link[^>]+rel=[\"']manifest[\"']"),
    _rule("Priority Hints", "Performance", html=r"fetchpriority=[\"'](?:high|low)[\"']"),
    _rule("HTTP/3", "Performance", header=("alt-svc", r"h3")),

    # --- Security ---
    _rule("HSTS", "Security", header=("strict-transport-security", r".")),
    _rule("reCAPTCHA", "Security", html=r"grecaptcha\.|google\.com/recaptcha/api"),
    _rule("Cloudflare Bot Management", "Security", html=r"__cf_bm|challenge-platform"),

    # --- JavaScript frameworks ---
    _rule("Next.js", "JavaScript frameworks", html=r'id="__NEXT_DATA__"|/_next/static|self\.__next_f'),
    _rule("Next.js", "JavaScript frameworks", header=("x-powered-by", r"Next\.js")),
    _rule("Nuxt", "JavaScript frameworks", html=r"window\.__NUXT__|/_nuxt/"),
    _rule("Gatsby", "JavaScript frameworks", html=r"___gatsby|window\.___chunkMapping"),
    _rule("SvelteKit", "JavaScript frameworks", html=r"__sveltekit_|data-sveltekit"),
    _rule("Astro", "JavaScript frameworks", html=r'name="generator"\s+content="Astro v(?P<version>[\d.]+)"'),
    _rule("Astro", "JavaScript frameworks", html=r"/_astro/|astro-island|data-astro-|<astro-", confidence=90),
    _rule("Remix", "JavaScript frameworks", html=r"__remixContext|window\.__remixManifest"),
    _rule("Angular", "JavaScript frameworks", html=r'ng-version="(?P<version>[\d.]+)"'),
    _rule("Angular", "JavaScript frameworks", html=r"_nghost-|_ngcontent-", confidence=80),
    _rule("Vue.js", "JavaScript frameworks", html=r"data-v-[0-9a-f]{6,}|__VUE__|vue(?:\.min)?\.js"),
    _rule("React", "JavaScript frameworks", html=r"data-reactroot|__REACT_DEVTOOLS|react(?:-dom)?(?:\.production)?(?:\.min)?\.js"),
    _rule("Ember.js", "JavaScript frameworks", html=r"ember(?:\.min)?\.js|data-ember"),
    _rule("Alpine.js", "JavaScript frameworks", html=r'\\sx-data=|(?:src)=\"[^\"]*alpinejs[^\"]*\"'),
    _rule("HTMX", "JavaScript frameworks", html=r"htmx(?:\.min)?\.js|hx-get="),

    # --- JavaScript libraries ---
    _rule("jQuery", "JavaScript libraries", html=r"jquery[.-](?P<version>\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js"),
    _rule("jQuery", "JavaScript libraries", html=r'src="[^"]*jquery[^"]*\.js"', confidence=85),
    _rule("jQuery UI", "JavaScript libraries", html=r"jquery-ui[.-]?(?P<version>[\d.]+)?(?:\.min)?\.js"),
    _rule("Lodash", "JavaScript libraries", html=r"lodash(?:\.min)?\.js"),
    _rule("Moment.js", "JavaScript libraries", html=r"moment(?:\.min)?\.js"),
    _rule("Axios", "JavaScript libraries", html=r"axios(?:\.min)?\.js"),
    _rule("Swiper", "JavaScript libraries", html=r"swiper(?:-bundle)?(?:\.min)?\.(?:js|css)"),
    _rule("Slick", "JavaScript libraries", html=r"slick(?:\.min)?\.(?:js|css)"),
    _rule("Owl Carousel", "JavaScript libraries", html=r"owl\.carousel(?:\.min)?\.(?:js|css)"),
    _rule("AOS", "JavaScript libraries", html=r"aos(?:\.min)?\.(?:js|css)"),
    _rule("GSAP", "JavaScript libraries", html=r"gsap(?:\.min)?\.js|TweenMax"),
    _rule("Chart.js", "JavaScript libraries", html=r'src="[^"]*chart(?:\.min)?\.js"'),
    _rule("Modernizr", "JavaScript libraries", html=r"modernizr[.-]?(?P<version>[\d.]+)?(?:\.min)?\.js"),
    _rule("Popper.js", "JavaScript libraries", html=r"popper(?:\.min)?\.js"),

    # --- UI frameworks ---
    _rule("Bootstrap", "UI frameworks", html=r"bootstrap[.-](?P<version>\d+\.\d+(?:\.\d+)?)(?:\.min)?\.(?:js|css)"),
    _rule("Bootstrap", "UI frameworks", html=r"bootstrap(?:\.bundle)?(?:\.min)?\.(?:js|css)", confidence=85),
    _rule("Tailwind CSS", "UI frameworks", html=r"tailwind(?:css)?(?:\.min)?\.css|cdn\.tailwindcss\.com"),
    _rule("Foundation", "UI frameworks", html=r"foundation(?:\.min)?\.(?:js|css)"),
    _rule("Bulma", "UI frameworks", html=r"bulma(?:\.min)?\.css"),
    _rule("Material UI", "UI frameworks", html=r"MuiBox-root|material-ui"),
    _rule("Font Awesome", "UI frameworks", html=r"font-?awesome[.-]?(?P<version>[\d.]+)?"),

    # --- Analytics ---
    _rule("Google Analytics", "Analytics", html=r"google-analytics\.com/analytics\.js|gtag/js\?id=UA-|ga\('create'"),
    _rule("Google Analytics 4", "Analytics", html=r"gtag/js\?id=G-|gtag\('config',\s*'G-"),
    _rule("Hotjar", "Analytics", html=r"_hjSettings|static\.hotjar\.com/c/hotjar"),
    _rule("Matomo", "Analytics", html=r'(?:src|href)=["\'][^"\']*(?:matomo\.js|piwik\.js)'),
    _rule("Plausible", "Analytics", html=r'(?:src|href)=["\'][^"\']*(?:plausible\.io/js)'),
    _rule("Mixpanel", "Analytics", html=r"mixpanel\.init\("),
    _rule("Segment", "Analytics", html=r'(?:src|href)=["\'][^"\']*(?:cdn\.segment\.com)'),
    _rule("Amplitude", "Analytics", html=r'(?:src|href)=["\'][^"\']*(?:cdn\.amplitude\.com)'),
    _rule("Microsoft Clarity", "Analytics", html=r'(?:src|href)=["\'][^"\']*(?:clarity\.ms)'),
    _rule("Facebook Pixel", "Analytics", html=r"fbq\(\s*.init."),
    _rule("LinkedIn Insight", "Analytics", html=r'(?:src|href)=["\'][^"\']*(?:snap\.licdn\.com)'),

    # --- Tag managers ---
    _rule("Google Tag Manager", "Tag managers", html=r"googletagmanager\.com/gtm\.js|GTM-[A-Z0-9]+"),
    _rule("Tealium", "Tag managers", html=r'(?:src|href)=["\'][^"\']*(?:tags\.tiqcdn\.com)'),

    # --- Font scripts ---
    _rule("Google Font API", "Font scripts", html=r'(?:src|href)=["\'][^"\']*(?:fonts\.googleapis\.com|fonts\.gstatic\.com)'),
    _rule("Adobe Fonts", "Font scripts", html=r'(?:src|href)=["\'][^"\']*(?:use\.typekit\.net)'),
    _rule("Font Awesome CDN", "Font scripts", html=r'(?:src|href)=["\'][^"\']*(?:cdnjs\.cloudflare\.com/ajax/libs/font-awesome)'),

    # --- CMS ---
    # A bare `/wp-content/` match fires on a *link to somebody else's* WordPress. Hacker
    # News was reported as WordPress because its front page linked to a PDF hosted on one.
    # These three are all same-site by construction: a root-relative asset path, the REST
    # API discovery link WordPress emits by default, and its own bundled scripts.
    _rule(
        "WordPress",
        "CMS",
        html=r"(?:src|href)=[\"']/(?:wp-content|wp-includes)/",
    ),
    _rule("WordPress", "CMS", html=r'rel=["\']https://api\.w\.org/["\']'),
    _rule("WordPress", "CMS", html=r"wp-(?:emoji-release|embed|includes/js/wp-)"),
    _rule("WordPress", "CMS", html=r'name="generator"\s+content="WordPress (?P<version>[\d.]+)"'),
    _rule("Drupal", "CMS", html=r'name="generator"\s+content="Drupal (?P<version>[\d.]+)'),
    # Same anchoring as WordPress, for the same reason: a link to another site's Drupal is
    # not evidence about this one. `drupal-settings-json` is an attribute the page itself
    # emits and needs no anchoring.
    _rule(
        "Drupal",
        "CMS",
        html=r"drupal-settings-json|(?:src|href)=[\"']/sites/default/files/",
        confidence=85,
    ),
    _rule(
        "Joomla",
        "CMS",
        html=r"(?:src|href)=[\"']/media/(?:jui|system/js)/"
        r'|name="generator"\s+content="Joomla',
    ),
    _rule("Ghost", "CMS", html=r'content="Ghost (?P<version>[\d.]+)"|/ghost/api/'),
    _rule("Contentful", "CMS", html=r"cdn\.contentful\.com|images\.ctfassets\.net"),
    _rule("Sanity", "CMS", html=r"cdn\.sanity\.io"),
    _rule("Strapi", "CMS", html=r'strapi\.io|\.strapiapp\.com|cdn\.strapi"[^\"]*strapi[^\"]*\"|strapi\\.io/uploads'),

    # --- Ecommerce ---
    _rule("Shopify", "Ecommerce", html=r"cdn\.shopify\.com|Shopify\.theme|/cdn/shop/"),
    _rule("WooCommerce", "Ecommerce", html=r"woocommerce/assets|wc-ajax|wp-content/plugins/woocommerce"),
    _rule("Magento", "Ecommerce", html=r"/static/version\d+/frontend/|Magento_"),
    _rule("BigCommerce", "Ecommerce", html=r"cdn\d*\.bigcommerce\.com"),
    _rule("PrestaShop", "Ecommerce", html=r"var prestashop|/themes/[^/]+/assets/.*prestashop"),
    _rule("Stripe", "Ecommerce", html=r'(?:src|href)=["\'][^"\']*(?:js\.stripe\.com)'),
    _rule("PayPal", "Ecommerce", html=r'(?:src|href)=["\'][^"\']*(?:paypal\.com/sdk|paypalobjects\.com)'),

    # --- Website builders ---
    _rule("Webflow", "Website builders", html=r"data-wf-page|data-wf-site|webflow\.js"),
    _rule("Wix", "Website builders", html=r"static\.wixstatic\.com|_wixCssImports"),
    _rule("Squarespace", "Website builders", html=r"static1\.squarespace\.com|Static\.SQUARESPACE_CONTEXT"),
    _rule("Framer", "Website builders", html=r"framerusercontent\.com"),

    # --- Static site generators ---
    _rule("Hugo", "Static site generators", html=r'name="generator"\s+content="Hugo (?P<version>[\d.]+)"'),
    _rule("Jekyll", "Static site generators", html=r'content="Jekyll(?: v(?P<version>[\d.]+))?"'),
    _rule("Eleventy", "Static site generators", html=r'content="Eleventy(?: v(?P<version>[\d.]+))?"'),
    _rule("Docusaurus", "Static site generators", html=r'name="generator"\s+content="Docusaurus v(?P<version>[\d.]+)"'),
    _rule("Docusaurus", "Static site generators", html=r"docusaurus\.config|__docusaurus", confidence=90),
    _rule("Starlight", "Static site generators", html=r'name="generator"\s+content="Starlight v(?P<version>[\d.]+)"'),
    _rule("Gatsby", "JavaScript frameworks", html=r'name="generator"\s+content="Gatsby (?P<version>[\d.]+)"'),
    _rule("Next.js", "JavaScript frameworks", html=r'name="generator"\s+content="Next\.js (?P<version>[\d.]+)"'),
    _rule("Nuxt", "JavaScript frameworks", html=r'name="generator"\s+content="Nuxt (?P<version>[\d.]+)"'),
    _rule("SvelteKit", "JavaScript frameworks", html=r'name="generator"\s+content="SvelteKit'),
    _rule("VuePress", "Static site generators", html=r'name="generator"\s+content="VuePress (?P<version>[\d.]+)"'),
    _rule("MkDocs", "Static site generators", html=r'name="generator"\s+content="mkdocs-(?P<version>[\d.]+)'),
    _rule("Sphinx", "Static site generators", html=r'name="generator"\s+content="(?:Docutils|Sphinx) ?(?P<version>[\d.]+)?'),
    _rule("Wix", "Website builders", html=r'name="generator"\s+content="Wix\.com'),
    _rule("MkDocs", "Static site generators", html=r'content="mkdocs'),

    # --- WordPress themes and page builders (extremely common, previously invisible) ---
    _rule("Astra", "UI frameworks", html=r'wp-content/themes/astra|astra-theme-css|class=\"[^\"]*\bast-(?:container|header|desktop|mobile|site)'),
    _rule("GeneratePress", "UI frameworks", html=r"wp-content/themes/generatepress"),
    _rule("OceanWP", "UI frameworks", html=r"wp-content/themes/oceanwp"),
    _rule("Divi", "UI frameworks", html=r"wp-content/themes/[Dd]ivi|et_pb_"),
    _rule("Elementor", "UI frameworks", html=r"elementor-(?:widget|section|element)|/elementor/assets/"),
    _rule("WPBakery", "UI frameworks", html=r"js_composer|vc_row"),
    _rule("Beaver Builder", "UI frameworks", html=r"fl-builder"),
    _rule("Kadence", "UI frameworks", html=r"wp-content/themes/kadence"),
    _rule("Yoast SEO", "Miscellaneous", html=r"This site is optimized with the Yoast|yoast-schema-graph"),
    _rule("WPForms", "Miscellaneous", html=r"wp-content/plugins/wpforms|wpforms-form"),
    _rule("Contact Form 7", "Miscellaneous", html=r"wpcf7-form|plugins/contact-form-7"),

    # --- Marketing ---
    _rule("HubSpot", "Marketing", html=r'(?:src|href)=["\'][^"\']*(?:js\.hs-scripts\.com|js\.hsforms\.net)'),
    _rule("Mailchimp", "Marketing", html=r'(?:src|href)=["\'][^"\']*(?:chimpstatic\.com|list-manage\.com)'),
    _rule("Intercom", "Marketing", html=r'(?:src|href)=["\'][^"\']*(?:widget\.intercom\.io)'),
    _rule("Drift", "Marketing", html=r'(?:src|href)=["\'][^"\']*(?:js\.driftt\.com)'),
    _rule("Crisp", "Marketing", html=r'(?:src|href)=["\'][^"\']*(?:client\.crisp\.chat)'),
    _rule("Tawk.to", "Marketing", html=r'(?:src|href)=["\'][^"\']*(?:(?:embed|cdn)\.tawk\.to)'),
)


_RUNTIME_CATEGORIES: Final[dict[str, str]] = {
    "React": "JavaScript frameworks",
    "Preact": "JavaScript frameworks",
    "Vue.js": "JavaScript frameworks",
    "Svelte": "JavaScript frameworks",
    "Angular": "JavaScript frameworks",
    "React Router": "JavaScript frameworks",
    "Framer Motion": "JavaScript libraries",
    "Three.js": "JavaScript libraries",
}
"""Categories for technologies that are only ever seen at runtime, so have no markup rule."""


@dataclass(frozen=True, slots=True)
class Implication:
    """One technology inferred from the presence of others.

    Some things leave no fingerprint of their own. **shadcn/ui is the clearest case: it is
    not a dependency at all.** Its components are copied into the project's own source, so
    there is no package name in the bundle, no global, no request and no attribute that says
    "shadcn". What there is, reliably, is the set of packages its registry installs --
    Radix primitives, Tailwind, and one or more of `sonner` / `cmdk` / `vaul` /
    `class-variance-authority`.

    Inference is therefore explicit and separate from matching, and it always lowers
    confidence: `requires` names what must be present, `confidence` says how strongly that
    combination implies the result, and the evidence string lists what it was inferred from
    so a reader can disagree.
    """

    name: str
    category: str
    requires: frozenset[str]
    """All of these must already be detected."""

    any_of: frozenset[str] = frozenset()
    """And at least one of these, when non-empty."""

    confidence: int = 70


IMPLICATIONS: Final[tuple[Implication, ...]] = (
    # A meta-framework is proof of the framework under it, and is usually the only thing
    # visible: Next.js exposes `__NEXT_DATA__` where React exposes nothing.
    Implication("React", "JavaScript frameworks", frozenset({"Next.js"}), confidence=95),
    Implication("React", "JavaScript frameworks", frozenset({"Remix"}), confidence=95),
    Implication("React", "JavaScript frameworks", frozenset({"Gatsby"}), confidence=95),
    Implication("React", "JavaScript frameworks", frozenset({"React Router"}), confidence=90),
    Implication("Vue.js", "JavaScript frameworks", frozenset({"Nuxt"}), confidence=95),
    Implication("Svelte", "JavaScript frameworks", frozenset({"SvelteKit"}), confidence=95),
    Implication("Astro", "Static site generators", frozenset({"Starlight"}), confidence=95),
    Implication("WordPress", "CMS", frozenset({"WooCommerce"}), confidence=95),
    Implication("Ruby on Rails", "Programming languages", frozenset({"Turbo"}), confidence=70),
    Implication("Laravel", "Programming languages", frozenset({"Livewire"}), confidence=80),
    # shadcn/ui: see the class docstring. Radix and Tailwind alone are not enough -- plenty
    # of projects use both directly -- so one of the registry's own packages is required.
    Implication(
        "shadcn/ui",
        "UI frameworks",
        frozenset({"Radix UI", "Tailwind CSS"}),
        any_of=frozenset({"Sonner", "cmdk", "Vaul", "class-variance-authority", "Lucide"}),
        confidence=65,
    ),
)


def merge_technologies(*groups: Iterable[Technology]) -> list[Technology]:
    """Union several detection passes, then apply implications across the whole result.

    Passes are separate because they run at different costs: markup and headers are free,
    the browser adds globals and the network log, and the bundle is fetched once per site.
    Implications must see the union -- shadcn/ui needs Tailwind from the markup pass and
    Radix from the bundle pass, and neither pass alone can infer it.

    Within a name, the entry with a version wins, then the one with higher confidence.
    """
    found: dict[str, Technology] = {}
    for group in groups:
        for technology in group:
            existing = found.get(technology.name)
            if existing is None:
                found[technology.name] = technology
                continue
            better_version = bool(technology.version) and not existing.version
            better_confidence = technology.confidence > existing.confidence
            if better_version or better_confidence:
                found[technology.name] = Technology(
                    name=technology.name,
                    category=technology.category,
                    version=technology.version or existing.version,
                    confidence=max(technology.confidence, existing.confidence),
                    evidence=technology.evidence,
                )

    apply_implications(found)
    order = {category: index for index, category in enumerate(CATEGORIES)}
    return sorted(
        found.values(),
        key=lambda t: (order.get(t.category, len(order)), t.name.lower()),
    )


def apply_implications(found: dict[str, Technology]) -> None:
    """Add technologies implied by combinations already detected. Mutates `found`.

    Applied repeatedly until nothing new appears, so a chain resolves in one call: Starlight
    implies Astro, and anything implied by Astro then follows. The loop terminates because
    each pass either adds a name or stops, and the name set is finite.
    """
    for _ in range(len(IMPLICATIONS)):
        added = False
        for implication in IMPLICATIONS:
            if implication.name in found:
                continue
            if not implication.requires <= found.keys():
                continue
            supporting = sorted(implication.requires)
            if implication.any_of:
                extra = sorted(implication.any_of & found.keys())
                if not extra:
                    continue
                supporting += extra
            found[implication.name] = Technology(
                name=implication.name,
                category=implication.category,
                version=None,
                confidence=implication.confidence,
                evidence=f"implied by {', '.join(supporting)}",
            )
            added = True
        if not added:
            return


def _category_for(name: str) -> str:
    """Category for a technology known only from a runtime global."""
    for rule in TECH_RULES:
        if rule.name == name:
            return rule.category
    return _RUNTIME_CATEGORIES.get(name, "JavaScript libraries")


def _version_from(match: re.Match[str]) -> str | None:
    """Extract the named `version` group, if this pattern declares one.

    Checked via `groupindex` rather than caught as an exception: most rules have no version
    group, so the miss is the common path and should not cost a raised IndexError.
    """
    if "version" not in match.re.groupindex:
        return None
    value = match.group("version")
    return value.strip() if value else None


def detect_technologies(
    html: str,
    headers: dict[str, str] | None = None,
    runtime_globals: dict[str, str] | None = None,
    *,
    custom_globals: Sequence[str] = (),
    requests: Sequence[str] = (),
    cookies: Mapping[str, str] | None = None,
    bundle_source: str = "",
) -> list[Technology]:
    """Identify technologies from every signal the caller managed to collect.

    Only `html` is required. The rest are what a rendered fetch adds, and they are where
    most of the coverage lives:

    - `runtime_globals` maps a technology name to a version read from the live page. It is
      authoritative: `jquery.min.js` carries no version in its filename, while
      `jQuery.fn.jquery` reports it exactly.
    - `custom_globals` is every name the page added to `window`, found by diffing against a
      pristine one. Hand-written probes only find what someone thought to name; this finds
      `Tinybird` and `__reactRouterVersion` without anyone naming them first.
    - `requests` is the network log. A service invisible in the markup is unmistakable here.
    - `cookies` come from the browser jar, so cookies set by third-party scripts are
      included -- `__cf_bm` is the only trace Cloudflare's bot management leaves.
    - `bundle_source` is the text of the page's own JavaScript. Component libraries that
      mount their attributes only on interaction are still named in it.

    Headers are matched case-insensitively by name, since HTTP header casing is arbitrary
    and servers are inconsistent about it.
    """
    normalized_headers = {k.lower(): v for k, v in (headers or {}).items()}
    cookie_names = list(cookies or ())
    set_cookie = normalized_headers.get("set-cookie", "")
    found: dict[str, Technology] = {}

    def _consider(rule: TechRule, match: re.Match[str], evidence: str) -> None:
        version = _version_from(match)
        existing = found.get(rule.name)
        # A later rule that supplies a version, or higher confidence, supersedes an earlier
        # bare match -- "jQuery 3.6.0" is strictly more useful than "jQuery".
        if existing is not None:
            better_version = bool(version) and not existing.version
            better_confidence = rule.confidence > existing.confidence
            if not (better_version or better_confidence):
                return
            version = version or existing.version
        found[rule.name] = Technology(
            name=rule.name,
            category=rule.category,
            version=version,
            confidence=rule.confidence,
            evidence=evidence,
        )

    for rule in TECH_RULES:
        if rule.header is not None:
            header_name, pattern = rule.header
            value = normalized_headers.get(header_name)
            if value:
                match = pattern.search(value)
                if match:
                    _consider(rule, match, f"header {header_name}: {value[:80]}")
                    continue

        if rule.js is not None:
            hit = next((n for n in custom_globals if rule.js.search(n)), None)
            if hit is not None:
                match = rule.js.search(hit)
                assert match is not None
                _consider(rule, match, f"global: window.{hit}")
                continue

        if rule.request is not None:
            hit = next((u for u in requests if rule.request.search(u)), None)
            if hit is not None:
                match = rule.request.search(hit)
                assert match is not None
                _consider(rule, match, f"request: {hit[:100]}")
                continue

        if rule.cookie is not None:
            hit = next((c for c in cookie_names if rule.cookie.search(c)), None)
            if hit is not None:
                match = rule.cookie.search(hit)
                assert match is not None
                _consider(rule, match, f"cookie: {hit}")
                continue
            if set_cookie:
                match = rule.cookie.search(set_cookie)
                if match:
                    _consider(rule, match, "cookie (Set-Cookie)")
                    continue

        if rule.html is not None and html:
            match = rule.html.search(html)
            if match:
                _consider(rule, match, f"markup: {match.group(0)[:60]}")
                continue

        if rule.source is not None and bundle_source:
            match = rule.source.search(bundle_source)
            if match:
                _consider(rule, match, f"bundle: {match.group(0)[:60]}")
                continue

    # Runtime globals are authoritative, and are the *only* evidence for a bundled
    # framework: a Vite build of React exposes no `window.React`, so detection relies on the
    # private properties React leaves on the DOM nodes it owns.
    for name, reported in (runtime_globals or {}).items():
        existing = found.get(name)
        category = existing.category if existing else _category_for(name)
        # A value that does not start with a digit is the browser side's "loaded, but the
        # library exposes no version" sentinel, not a version string.
        version = reported if reported[:1].isdigit() else None
        found[name] = Technology(
            name=name,
            category=category,
            version=version or (existing.version if existing else None),
            confidence=100,
            evidence="runtime global",
        )

    apply_implications(found)

    order = {category: index for index, category in enumerate(CATEGORIES)}
    return sorted(
        found.values(),
        key=lambda t: (order.get(t.category, len(order)), t.name.lower()),
    )
