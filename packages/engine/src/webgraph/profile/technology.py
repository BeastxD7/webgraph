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
from dataclasses import dataclass
from typing import Final

__all__ = ["CATEGORIES", "TECH_RULES", "TechRule", "Technology", "detect_technologies"]

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
    "Miscellaneous",
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
    """One fingerprint.

    `html` matches the raw markup; `header` matches a named response header. A capture group
    named `version` in either pattern is extracted as the version.
    """

    name: str
    category: str
    html: re.Pattern[str] | None = None
    header: tuple[str, re.Pattern[str]] | None = None
    cookie: re.Pattern[str] | None = None
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
    confidence: int = 100,
) -> TechRule:
    return TechRule(
        name=name,
        category=category,
        html=_h(html) if html else None,
        header=(header[0], _h(header[1])) if header else None,
        cookie=_h(cookie) if cookie else None,
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
    _rule("WordPress", "CMS", html=r"/wp-content/|/wp-includes/|/wp-json/"),
    _rule("WordPress", "CMS", html=r'name="generator"\s+content="WordPress (?P<version>[\d.]+)"'),
    _rule("Drupal", "CMS", html=r'name="generator"\s+content="Drupal (?P<version>[\d.]+)'),
    _rule("Drupal", "CMS", html=r"drupal-settings-json|/sites/default/files/", confidence=85),
    _rule("Joomla", "CMS", html=r'/media/jui/|/media/system/js/|name=\"generator\"\\s+content=\"Joomla'),
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


def _category_for(name: str) -> str:
    """Category for a technology known only from a runtime global."""
    for rule in TECH_RULES:
        if rule.name == name:
            return rule.category
    return "JavaScript libraries"


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
) -> list[Technology]:
    """Identify technologies from markup, response headers and live JavaScript globals.

    Headers are matched case-insensitively by name, since HTTP header casing is arbitrary
    and servers are inconsistent about it.

    `runtime_globals` maps a technology name to a version read from the rendered page. It is
    authoritative where present: `jquery.min.js` carries no version in its filename, while
    `jQuery.fn.jquery` reports it exactly.
    """
    normalized_headers = {k.lower(): v for k, v in (headers or {}).items()}
    found: dict[str, Technology] = {}

    for rule in TECH_RULES:
        match: re.Match[str] | None = None
        evidence = ""

        if rule.header is not None:
            header_name, pattern = rule.header
            value = normalized_headers.get(header_name)
            if value:
                match = pattern.search(value)
                if match:
                    evidence = f"{header_name}: {value[:80]}"

        if match is None and rule.html is not None and html:
            match = rule.html.search(html)
            if match:
                evidence = f"markup: {match.group(0)[:60]}"

        if match is None and rule.cookie is not None:
            cookies = normalized_headers.get("set-cookie", "")
            if cookies:
                match = rule.cookie.search(cookies)
                if match:
                    evidence = "cookie"

        if match is None:
            continue

        version = _version_from(match)
        existing = found.get(rule.name)

        # A later rule that supplies a version, or higher confidence, supersedes an earlier
        # bare match -- "jQuery 3.6.0" is strictly more useful than "jQuery".
        if existing is not None:
            better_version = version and not existing.version
            better_confidence = rule.confidence > existing.confidence
            if not (better_version or better_confidence):
                continue

        found[rule.name] = Technology(
            name=rule.name,
            category=rule.category,
            version=version,
            confidence=rule.confidence,
            evidence=evidence,
        )

    # Runtime globals are authoritative for versions, and also prove a library is actually
    # loaded rather than merely referenced in markup.
    for name, version in (runtime_globals or {}).items():
        existing = found.get(name)
        category = existing.category if existing else _category_for(name)
        found[name] = Technology(
            name=name,
            category=category,
            version=version or (existing.version if existing else None),
            confidence=100,
            evidence="runtime global",
        )

    order = {category: index for index, category in enumerate(CATEGORIES)}
    return sorted(
        found.values(),
        key=lambda t: (order.get(t.category, len(order)), t.name.lower()),
    )
