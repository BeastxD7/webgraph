(markers) => {
  const MARKER = markers.marker;
  const BREAK = markers.brk;
  const HIDDEN = markers.hidden;
  const FLOAT = markers.float;
  const rects = {};
  let counter = 0;

  // Walk into open shadow roots as well as the light DOM.
  //
  // A TreeWalker stops at a shadow boundary and `outerHTML` does not serialise across one,
  // so a component that renders its content inside a shadow root was previously invisible
  // *twice over*: absent from the HTML lxml parses, and absent from the geometry map. The
  // loss is total rather than partial, and nothing reported it. Web Almanac 2024 puts shadow
  // DOM on 2.51% of mobile pages, up 6x in two years, and custom elements on 7.9%.
  //
  // getBoundingClientRect() inside a shadow root already returns page coordinates, so the
  // rectangles need no transform.
  const shadowRoots = [];
  const nodes = [document.documentElement];
  const descend = (root) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    while (walker.nextNode()) {
      const el = walker.currentNode;
      nodes.push(el);
      if (el.shadowRoot) { shadowRoots.push(el.shadowRoot); descend(el.shadowRoot); }
    }
  };
  descend(document.documentElement);

  for (const el of nodes) {
    const id = String(counter++);
    el.setAttribute(MARKER, id);

    const style = window.getComputedStyle(el);

    // Mark elements the browser lays out as their own box.
    //
    // lxml's `text_content()` concatenates descendants with nothing between them, so a
    // navigation of `<a>Mac</a><a>iPad</a><a>iPhone</a>` arrives as `MaciPadiPhone` -- the
    // words destroyed, not merely unwanted. Measured on apple.com/airpods-pro, whose whole
    // nav came out as `AppleStoreShopShop the LatestMaciPadiPhoneApple Watch...`.
    //
    // A separator cannot be inserted between every pair of elements, because inline siblings
    // genuinely do run together: `<b>bold</b><i>italic</i>` renders as `bolditalic` and
    // splitting it would be the same corruption in the other direction. What decides is the
    // computed `display`: a block-level box starts a new line, an inline one does not. That
    // is the rule `innerText` itself follows, and it is a measurement of this page rather
    // than an assumption about markup.
    const display = style.display;
    if (display && display !== 'inline' && display !== 'inline-block' &&
        display !== 'contents' && display !== 'none') {
      el.setAttribute(BREAK, '1');
    }

    // Marked, not just skipped: the parser can then tell a hidden twin -- the mobile copy
    // of a badge beside its desktop copy -- from an inline sibling that is really there,
    // and a control the reader cannot see (a copy button shown on hover) from one they can.
    // The value says how it is hidden; opacity 0 is kept apart because content faded in by
    // a scroll animation also starts there and must not be treated as absent.
    // A float is beside the flow, not in it; the parser keeps what is inside one together.
    const floated = style.cssFloat || style.float;
    if (floated === 'left' || floated === 'right') el.setAttribute(FLOAT, floated);

    if (style.display === 'none') { el.setAttribute(HIDDEN, 'display'); continue; }
    if (style.visibility === 'hidden') { el.setAttribute(HIDDEN, 'visibility'); continue; }
    // Opacity 0 is marked but still measured: the box is laid out, and content faded in
    // by an entrance animation has to be ordered by where it sits, not by where it is in
    // the source (apple.com/iphone's "iPhone 18 Pro" hero, unmeasured, was slotted after the
    // other hero's image and before its heading).
    if (style.opacity === '0') { el.setAttribute(HIDDEN, 'opacity'); }
    const box = el.getBoundingClientRect();
    // Screen-reader-only text, measured rather than named: the convention clips the element
    // to a 1px box with overflow hidden (or `clip: rect(0 0 0 0)` / `clip-path: inset(50%)`).
    // linear.app's <h1> carries a second copy of the headline in a CSS-module class the
    // name rule cannot know (`Fzcv4W_visuallyHidden`); the box says what the class means.
    const clipped = (box.width <= 1 && box.height <= 1 && style.overflow === 'hidden') ||
      /^rect\(0px,? 0px,? 0px,? 0px\)$/.test(style.clip || '') ||
      /^inset\((?:50|100)%\)$/.test(style.clipPath || '');
    if (clipped && (el.textContent || '').trim()) { el.setAttribute(HIDDEN, 'clipped'); continue; }
    if (box.width <= 0 || box.height <= 0) continue;
    // Inside a collapsed ancestor: an accordion tray is `overflow: hidden` at height 0 and
    // its paragraphs keep their natural boxes underneath the next item's heading
    // (apple.com/iphone, "Significant others"). Ordered by those boxes the trays zip with
    // the headings; the text is real, but it has no position on the page. It is marked
    // `overflow`, kept, and slotted after its heading like any unmeasured block. Only an
    // ancestor that is itself collapsed (a box of no height or no width) counts: a carousel
    // clips horizontally at full height and its later cards are reachable by scrolling, and
    // their boxes say, correctly, that they come later.
    let collapsed = false;
    for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
      const as = window.getComputedStyle(a);
      const ox = as.overflowX, oy = as.overflowY;
      if (ox !== 'hidden' && ox !== 'clip' && oy !== 'hidden' && oy !== 'clip') continue;
      const ab = a.getBoundingClientRect();
      if (((oy === 'hidden' || oy === 'clip') && ab.height <= 1) ||
          ((ox === 'hidden' || ox === 'clip') && ab.width <= 1)) { collapsed = true; break; }
    }
    if (collapsed && (el.textContent || '').trim()) { el.setAttribute(HIDDEN, 'overflow'); continue; }

    // Page-relative, not viewport-relative: a scrolled viewport would otherwise
    // report negative coordinates for content above the fold.
    const px = box.left + window.scrollX, py = box.top + window.scrollY;
    // A box lying entirely at negative page coordinates is somewhere no reader can
    // scroll to. vtu.ac.in carries sixty injected gambling links per page, each in
    // `position:absolute; left:-20914565266523px`; they have a box, and the box is
    // twenty trillion pixels to the left. Hidden the way `display: none` is -- not
    // measured, not on the page -- and, like `clipped`, only when there is text to hide.
    if ((px + box.width <= 0 || py + box.height <= 0) && (el.textContent || '').trim()) {
      el.setAttribute(HIDDEN, 'offscreen'); continue;
    }
    rects[id] = { x: px, y: py, width: box.width, height: box.height };
  }
  // Library versions are frequently only available at runtime. `jquery.min.js` carries no
  // version in its filename, but `jQuery.fn.jquery` reports it exactly. Reading these while
  // the page is live is the only reliable way to get them.
  const globals = {};
  // Sentinel for "this is loaded but exposes no version". The Python side treats any value
  // that does not begin with a digit as presence without a version.
  const PRESENT = 'present';
  const probe = (name, fn) => { try { const v = fn(); if (v) globals[name] = String(v); } catch (e) {} };

  // Every global the page added, found by diffing against a pristine window.
  //
  // This is the signal that closes most of the gap with a browser extension. Hand-written
  // probes only find what someone thought to ask for; the diff finds `window.Tinybird`,
  // `window.__reactRouterVersion` and `window.lenisVersion` without anyone naming them
  // first, and the rules then map names to technologies.
  //
  // The baseline comes from a blank same-origin iframe rather than a hard-coded list,
  // because the set of standard globals differs by browser and by version.
  let customGlobals = [];
  try {
    const frame = document.createElement('iframe');
    frame.setAttribute('aria-hidden', 'true');
    frame.style.cssText = 'display:none;width:0;height:0';
    document.body.appendChild(frame);
    const baseline = new Set(Object.keys(frame.contentWindow));
    frame.remove();
    // Cap the list: a page that assigns hundreds of globals is doing something unusual, and
    // the interesting names are always near the front of the enumeration order anyway.
    customGlobals = Object.keys(window).filter((k) => !baseline.has(k)).slice(0, 400);
  } catch (e) { /* CSP can forbid the iframe; the explicit probes still apply. */ }

  probe('jQuery', () => window.jQuery && window.jQuery.fn && window.jQuery.fn.jquery);
  probe('React', () => window.React && window.React.version);
  probe('Vue.js', () => window.Vue && window.Vue.version);
  probe('Angular', () => window.ng && window.ng.version && window.ng.version.full);
  probe('Bootstrap', () => window.bootstrap && window.bootstrap.Tooltip && window.bootstrap.Tooltip.VERSION);
  probe('Modernizr', () => window.Modernizr && window.Modernizr._version);
  probe('Lodash', () => window._ && window._.VERSION);
  probe('Moment.js', () => window.moment && window.moment.version);
  probe('D3', () => window.d3 && window.d3.version);
  probe('GSAP', () => window.gsap && window.gsap.version);
  probe('Next.js', () => window.next && window.next.version);
  probe('Swiper', () => window.Swiper && window.Swiper.version);
  probe('PostHog', () => window.posthog && (window.posthog.version || window.posthog.config ? (window.posthog.version || PRESENT) : null));
  probe('Lenis', () => window.Lenis && (window.Lenis.version || PRESENT));
  probe('core-js', () => window['__core-js_shared__'] && PRESENT);
  probe('Alpine.js', () => window.Alpine && (window.Alpine.version || PRESENT));
  probe('Three.js', () => window.THREE && (window.THREE.REVISION || PRESENT));
  probe('Framer Motion', () => window.__FRAMER_MOTION__ && PRESENT);

  // Bundled frameworks expose no global at all -- a Vite build of React has no
  // `window.React`. They do leave private properties on the DOM nodes they own, which is
  // the only honest evidence that the framework is *running* rather than merely mentioned.
  const domKeyed = (prefixes) => {
    const roots = [document.body, document.getElementById('root'), document.getElementById('app')];
    const seen = [];
    for (const root of roots) {
      if (!root) continue;
      seen.push(root);
      for (let i = 0; i < root.children.length && seen.length < 40; i++) seen.push(root.children[i]);
    }
    for (const el of seen) {
      for (const key of Object.keys(el)) {
        for (const prefix of prefixes) {
          if (key.startsWith(prefix)) return true;
        }
      }
    }
    return false;
  };

  probe('React', () => {
    if (window.React && window.React.version) return window.React.version;
    return domKeyed(['__reactContainer$', '__reactFiber$', '__reactProps$', '__reactInternalInstance$'])
      ? PRESENT : null;
  });
  probe('Preact', () => domKeyed(['__preactattr_', '_prevVNode', '__k']) && !window.React ? PRESENT : null);
  probe('Vue.js', () => {
    if (window.Vue && window.Vue.version) return window.Vue.version;
    const el = document.querySelector('#app, [data-v-app]');
    return el && el.__vue_app__ ? (el.__vue_app__.version || PRESENT) : null;
  });
  probe('Svelte', () => document.querySelector('[class*=svelte-]') || domKeyed(['__svelte_meta']) ? PRESENT : null);
  probe('React Router', () => {
    if (window.__reactRouterVersion) return String(window.__reactRouterVersion);
    if (window.__reactRouterContext || window.__staticRouterHydrationData) return PRESENT;
    return document.querySelector('[data-discover="true"]') ? PRESENT : null;
  });

  // Versions, where the library exposes one somewhere other than a bare `.version`.
  probe('Facebook Pixel', () => window.fbq && window.fbq.version);
  probe('core-js', () => {
    const shared = window['__core-js_shared__'];
    if (!shared) return null;
    const versions = shared.versions;
    if (Array.isArray(versions) && versions.length && versions[0].version) return versions[0].version;
    return PRESENT;
  });
  probe('Lenis', () => window.lenisVersion || (window.lenis || document.documentElement.classList.contains('lenis') ? PRESENT : null));
  probe('PostHog', () => {
    const ph = window.posthog;
    if (ph) return ph.version || (ph.LIB_VERSION) || PRESENT;
    return window.__PosthogExtensions__ || window._POSTHOG_REMOTE_CONFIG ? PRESENT : null;
  });
  probe('Tinybird', () => window.Tinybird && PRESENT);

  const scripts = Array.from(document.scripts).map((s) => s.src).filter(Boolean).slice(0, 60);
  const links = Array.from(document.querySelectorAll('link[rel][href]'))
    .map((l) => l.rel + ' ' + l.href).slice(0, 60);

  // Serialise shadow roots as `<template shadowrootmode>`, which the Python side unwraps.
  // `getHTML` is Chromium 125+; without it we fall back to the light DOM only rather than
  // failing, and the shadow content is lost as it always was.
  let serialized;
  try {
    serialized = (shadowRoots.length && typeof document.documentElement.getHTML === 'function')
      ? document.documentElement.getHTML({ serializableShadowRoots: true, shadowRoots })
      : document.documentElement.outerHTML;
  } catch (e) {
    serialized = document.documentElement.outerHTML;
  }

  return {
    rects,
    shadowRoots: shadowRoots.length,
    html: serialized,
    globals,
    customGlobals,
    scripts,
    links,
  };
}
