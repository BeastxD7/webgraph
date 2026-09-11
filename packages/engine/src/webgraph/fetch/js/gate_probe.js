(markers) => {
  // Assess whether the mounted page is a gate rather than the site, and mark the controls
  // that would open it.
  //
  // The case this exists for: a client-rendered app whose entire mounted DOM is a first-run
  // interstitial -- a persona or role picker, a region or currency selector, an age gate, an
  // onboarding wizard. The real content is *unmounted*, not hidden, so `reveal.js`
  // cannot reach it: there is no collapsed panel to open, and nothing in the DOM to reveal.
  // Measured on zerotoonepmtoolkit.app, whose 21 routes all render the same persona modal:
  // 1,137 characters of text and ZERO internal links, against ~32,900 characters behind it.
  //
  // Two signals, both structural rather than textual, so this does not depend on guessing at
  // wording in any particular language:
  //
  //   1. Almost no internal links. A real page of a real site carries navigation. A gate
  //      screen carries none, because the nav lives in the subtree that has not mounted.
  //   2. Little text.
  //
  // Requiring both matters. A long article legitimately has few outbound links, and a link
  // hub legitimately has little prose; only the conjunction says "nothing has mounted yet".
  const MARK = markers.gate;
  for (const el of document.querySelectorAll('[' + MARK + ']')) el.removeAttribute(MARK);

  const text = ((document.body && document.body.innerText) || '').trim();
  const origin = location.origin;
  const internal = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    const raw = a.getAttribute('href') || '';
    if (!raw || raw.startsWith('#') || raw.startsWith('javascript:')) continue;
    let resolved;
    try { resolved = new URL(raw, location.href); } catch (e) { continue; }
    if (resolved.origin !== origin) continue;
    const path = resolved.pathname.replace(/\/$/, '');
    if (path && path !== location.pathname.replace(/\/$/, '')) internal.add(path);
  }

  // Candidate controls, ordered by how likely they are to be the thing that opens the gate.
  //
  // Deliberately excluded, because clicking them does something to somebody's site rather
  // than to the page:
  //   - anything inside a <form>, which may submit;
  //   - anchors carrying a real href, which navigate -- an ordinary link is not a gate;
  //   - controls whose accessible name reads as a transaction, a refusal or a sign-out.
  // The exclusions are on what the element *is*, not on what it says, except for the last,
  // which is a narrow deny-list rather than an attempt to understand the label.
  const DENY = /(buy|purchase|checkout|subscribe|pay|donate|delete|remove|sign\s*out|log\s*out|unsubscribe|reject|decline|deny|refuse|exit|cancel)/i;

  const viewport = window.innerWidth * window.innerHeight;
  const scored = [];
  const controls = document.querySelectorAll(
    'button, [role="button"], [role="radio"], [role="option"], [tabindex]:not([tabindex="-1"]), a:not([href])'
  );

  for (const el of controls) {
    if (el.closest('form')) continue;
    if (el.tagName === 'A' && el.getAttribute('href')) continue;
    if (el.disabled) continue;

    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
    const box = el.getBoundingClientRect();
    if (box.width < 24 || box.height < 16) continue;

    const label = (el.innerText || el.getAttribute('aria-label') || '').trim();
    if (DENY.test(label)) continue;

    // A control sitting inside a fixed or absolutely-positioned layer that covers much of
    // the viewport is the classic modal shape, and is tried first.
    let overlay = 0;
    for (let node = el; node && node !== document.body; node = node.parentElement) {
      const s = window.getComputedStyle(node);
      if (s.position === 'fixed' || s.position === 'absolute') {
        const b = node.getBoundingClientRect();
        if (b.width * b.height > viewport * 0.5) { overlay = 1; break; }
      }
    }
    scored.push({ el: el, overlay: overlay, area: box.width * box.height });
  }

  scored.sort((a, b) => (b.overlay - a.overlay) || (b.area - a.area));

  const marks = [];
  for (let i = 0; i < scored.length && marks.length < 8; i++) {
    scored[i].el.setAttribute(MARK, String(marks.length));
    marks.push(String(marks.length));
  }

  return { textLength: text.length, internalLinks: internal.size, candidates: marks };
}
