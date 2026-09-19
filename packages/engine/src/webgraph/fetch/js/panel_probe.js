(markers) => {
  // Reach content that only a click reveals -- tabs, accordions and "show more" panels
  // wired in JavaScript alone, with no `aria-controls`, no `data-target` and no
  // `href="#id"` for `reveal.js` to follow. Three phases, driven from `render.py`:
  //
  //   survey  -- how many words are hidden outside the site's chrome, and which visible
  //              controls might open them; each candidate is stamped `markers.panel`.
  //   record  -- after one click: which hidden elements became visible (stamped
  //              `markers.revealed` = "click"), and which visible ones the click hid.
  //   finish  -- every element stamped by a click is forced visible again, so a tab
  //              set whose panels replace one another ends with every panel showing.
  //
  // The click itself is done by the driver (Playwright's actionability checks, a timeout,
  // an origin check and `go_back` if the page navigated). This script never clicks.
  //
  // The argument is the marker names as every script gets them, plus `phase` and `limit`
  // from `render._open_panels`.
  const args = markers;
  const PANEL = markers.panel;
  const REVEALED = markers.revealed;

  const CHROME = (el) => {
    for (let a = el; a && a !== document.body; a = a.parentElement) {
      const tag = a.tagName.toLowerCase();
      const role = (a.getAttribute('role') || '').toLowerCase();
      if (tag === 'nav' || tag === 'header' || tag === 'footer' || tag === 'form' || tag === 'dialog') return true;
      if (role === 'navigation' || role === 'banner' || role === 'contentinfo' || role === 'menu' || role === 'menubar' || role === 'dialog' || role === 'alertdialog') return true;
    }
    return false;
  };
  const words = (el) => ((el.textContent || '').trim().match(/\S+/g) || []).length;
  const hiddenNow = (el) => {
    if (el.hasAttribute('hidden')) return true;
    const s = window.getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return true;
    const box = el.getBoundingClientRect();
    return box.height <= 1 && (s.overflow === 'hidden' || s.overflowY === 'hidden' || parseFloat(s.maxHeight) === 0);
  };
  // A modal, drawer or popup is a different screen, not collapsed content of this one:
  // a "Contact us" button that opens a form is not a tab. Excluded by role and by the
  // names such things are given, so opening one is never counted as a gain.
  const MODAL = '[role="dialog"], [role="alertdialog"], [aria-modal="true"], dialog, [class*="modal"], [class*="popup"], [class*="overlay"], [class*="drawer"], [class*="lightbox"], [class*="offcanvas"], [class*="cookie"], [class*="consent"], [id*="modal"], [id*="popup"]';
  // Outermost hidden elements with text, outside the chrome: what a click could reveal.
  // The modal-like ones are kept apart (`layers`): a click that opens one is closing it
  // again, not a gain.
  const hiddenHolders = () => {
    const out = [];
    const layers = [];
    for (const el of document.body.querySelectorAll('*')) {
      if (!hiddenNow(el)) continue;
      if (out.some((o) => o.contains(el)) || layers.some((o) => o.contains(el))) continue;
      if (CHROME(el)) continue;
      if (words(el) === 0) continue;
      if (el.closest(MODAL)) { layers.push(el); continue; }
      out.push(el);
    }
    return { out, layers };
  };
  // A panel's visible siblings: in a tab set the panels share a parent, and the one
  // showing now is hidden by the click that shows the next. Remembered so the finish
  // step can bring it back too.
  const siblingsOf = (holders) => {
    const out = [];
    for (const h of holders) {
      const parent = h.parentElement;
      if (!parent) continue;
      for (const sib of parent.children) {
        if (sib === h || out.includes(sib) || hiddenNow(sib) || sib.tagName !== h.tagName) continue;
        if (words(sib) === 0 || sib.querySelector('a[href], button, [role="tab"]')) continue;
        out.push(sib);
      }
    }
    return out;
  };

  if (args.phase === 'survey') {
    for (const el of document.querySelectorAll('[' + PANEL + ']')) el.removeAttribute(PANEL);
    const { out: holders, layers } = hiddenHolders();
    const hiddenWords = holders.reduce((n, el) => n + words(el), 0);
    // Remember what was hidden before any click, so `record` can tell what a click opened.
    window.__wgHidden = holders;
    window.__wgLayers = layers;
    window.__wgShowing = siblingsOf(holders);
    window.__wgClickRevealed = [];

    // Candidates: things that look like a control and are not a link to somewhere else,
    // not inside a form, not in the chrome, and not labelled as a transaction.
    const DENY = /(buy|purchase|checkout|cart|subscribe|pay|donate|delete|remove|sign\s*(in|out|up)|log\s*(in|out)|register|unsubscribe|reject|decline|deny|refuse|exit|cancel|close|submit|send|download|share|print|next|previous|prev|back|accept|agree|allow|search|menu|language|currency|filter|sort)/i;
    const LOOKS = /(tab|accordion|toggle|collapse|expand|show|more|read|details|faq|panel|disclosure|spoiler)/i;
    const seen = new Set();
    const scored = [];
    const controls = document.body.querySelectorAll(
      'button, [role="button"], [role="tab"], [aria-expanded], summary, a[href^="#"], a:not([href]), [onclick], [class*="tab"], [class*="accordion"], [class*="toggle"], [class*="collapse"], [class*="expand"], [class*="more"], [class*="faq"]'
    );
    for (const el of controls) {
      if (seen.has(el)) continue;
      seen.add(el);
      if (CHROME(el)) continue;
      // A link is a candidate only when it goes nowhere: `javascript:` or `#id` with the
      // target hidden. An `href="#section"` to a visible heading is navigation.
      const href = el.tagName === 'A' ? (el.getAttribute('href') || '') : '';
      if (el.tagName === 'A') {
        if (href && !/^javascript:/i.test(href) && !href.startsWith('#')) continue;
        if (href.startsWith('#')) {
          const target = href.length > 1 ? document.getElementById(href.slice(1)) : null;
          if (!target || !hiddenNow(target)) continue;
        }
      }
      if (el.closest('a[href]:not([href^="#"]):not([href^="javascript:"])')) continue;
      if (el.disabled || el.getAttribute('type') === 'submit') continue;
      // A container of controls is not a control: the click should land on the tab, not
      // on the tab strip around it.
      if (el.querySelector('a[href], button, [role="tab"], [role="button"], [onclick]')) continue;
      const s = window.getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') continue;
      const box = el.getBoundingClientRect();
      if (box.width < 16 || box.height < 12) continue;
      const label = (el.innerText || el.getAttribute('aria-label') || '').trim();
      const n = (label.match(/\S+/g) || []).length;
      if (n === 0 || n > 8) continue;
      if (DENY.test(label)) continue;
      // A control that is itself a container of many words is a section, not a button.
      if (words(el) > 12) continue;
      const cls = (el.getAttribute('class') || '') + ' ' + (el.getAttribute('id') || '');
      const role = (el.getAttribute('role') || '').toLowerCase();
      let score = 0;
      if (role === 'tab' || el.getAttribute('aria-expanded') === 'false' || el.tagName === 'SUMMARY') score += 3;
      if (LOOKS.test(cls)) score += 2;
      if (el.tagName === 'BUTTON' || role === 'button') score += 1;
      if (el.hasAttribute('onclick')) score += 1;
      if (s.cursor === 'pointer') score += 1;
      // A bare button with a pointer cursor is not evidence enough: a page has dozens
      // of those, and each futile click costs a settle. Two signals, or a tab role.
      if (score < 2) continue;
      scored.push({ el, score, top: box.top + window.scrollY });
    }
    scored.sort((a, b) => (b.score - a.score) || (a.top - b.top));
    const marks = [];
    for (let i = 0; i < scored.length && marks.length < args.limit; i++) {
      scored[i].el.setAttribute(PANEL, String(marks.length));
      marks.push({ mark: String(marks.length), label: ((scored[i].el.innerText || '').trim()).slice(0, 60) });
    }
    return { hiddenWords, candidates: marks };
  }

  if (args.phase === 'click') {
    // A synthetic click on the page's own control: the same event its handler listens
    // for, without Playwright's scroll-into-view and actionability waits, which cost a
    // second per control on a page with a sticky header. Nothing is typed, nothing is
    // submitted; the driver checks the address afterwards.
    const el = document.querySelector('[' + PANEL + '="' + args.mark + '"]');
    if (!el) return { clicked: false };
    try { el.click(); } catch (e) { return { clicked: false }; }
    return { clicked: true };
  }

  if (args.phase === 'record') {
    const was = window.__wgHidden || [];
    let gained = 0;
    const still = [];
    const viewport = window.innerWidth * window.innerHeight;
    for (const el of was) {
      if (!el.isConnected) continue;
      if (hiddenNow(el)) { still.push(el); continue; }
      // What appeared is a layer over the page, not content in it: a popup with no
      // modal role or class (w3schools' `#err_message` "Contact Sales" box). Close it
      // again and count nothing; the survey excluded the named ones already.
      const s = window.getComputedStyle(el);
      const box = el.getBoundingClientRect();
      const layer = s.position === 'fixed' ||
        ((s.position === 'absolute' || s.position === 'sticky') && box.width * box.height > viewport * 0.25) ||
        /^\s*[×✕✖x]\s/i.test(el.innerText || '');
      if (layer) { el.style.setProperty('display', 'none', 'important'); continue; }
      el.setAttribute(REVEALED, 'click');
      window.__wgClickRevealed.push(el);
      gained += words(el);
    }
    window.__wgHidden = still;
    // A modal the click opened: close it again. It was never a gain.
    for (const el of window.__wgLayers || []) {
      if (el.isConnected && !hiddenNow(el)) el.style.setProperty('display', 'none', 'important');
    }
    // A panel that was showing and the click hid -- the tab the page opened with -- is
    // a panel too, and comes back at the finish.
    for (const el of window.__wgShowing || []) {
      if (el.isConnected && hiddenNow(el) && !window.__wgClickRevealed.includes(el)) {
        el.setAttribute(REVEALED, 'click');
        window.__wgClickRevealed.push(el);
      }
    }
    return { gained, textLength: ((document.body && document.body.innerText) || '').length };
  }

  if (args.phase === 'finish') {
    let forced = 0;
    for (const el of window.__wgClickRevealed || []) {
      if (!el.isConnected) continue;
      el.removeAttribute('hidden');
      if (el.getAttribute('aria-hidden') === 'true') el.setAttribute('aria-hidden', 'false');
      const s = window.getComputedStyle(el);
      if (s.display === 'none') el.style.setProperty('display', 'block', 'important');
      if (s.visibility === 'hidden') el.style.setProperty('visibility', 'visible', 'important');
      if (parseFloat(s.height) === 0 && el.scrollHeight > 0) {
        el.style.setProperty('height', 'auto', 'important');
        el.style.setProperty('overflow', 'visible', 'important');
      }
      if (parseFloat(s.maxHeight) === 0) el.style.setProperty('max-height', 'none', 'important');
      forced++;
    }
    return { forced };
  }
  return null;
}
