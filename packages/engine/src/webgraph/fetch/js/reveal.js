(markers) => {
  // Open content the page collapsed, without clicking anything: <details>, ARIA
  // disclosures, tab panels, and panels a control names by id. Never a menu.
  //
  // Accordions, FAQ sections and `<details>` blocks hold real content that no fetch and no
  // renderer sees, because it is `display:none` until someone interacts. Clicking is the
  // obvious way to reach it and the wrong one: a click can navigate, submit a form, open a
  // dialog that blocks the driver, or fire an analytics event on someone else's site.
  //
  // Everything here is a property or attribute change on the page's own DOM. Nothing is
  // clicked, no handler is invoked, and the page cannot navigate as a result.
  let opened = 0;

  for (const details of document.querySelectorAll('details:not([open])')) {
    details.open = true;
    opened++;
  }

  // ARIA disclosure pattern: a control says what it controls, and the panel says it is
  // hidden. Both halves are declared by the page, so honouring them is reading the page's
  // own description of itself rather than guessing at class names.
  for (const control of document.querySelectorAll('[aria-expanded="false"][aria-controls]')) {
    const ids = (control.getAttribute('aria-controls') || '').split(/\s+/);
    let revealed = false;
    for (const id of ids) {
      const panel = document.getElementById(id);
      if (!panel) continue;
      panel.removeAttribute('hidden');
      if (panel.getAttribute('aria-hidden') === 'true') panel.setAttribute('aria-hidden', 'false');
      const style = window.getComputedStyle(panel);
      if (style.display === 'none') panel.style.setProperty('display', 'block', 'important');
      if (style.visibility === 'hidden') panel.style.setProperty('visibility', 'visible', 'important');
      if (parseFloat(style.height) === 0 && panel.scrollHeight > 0) {
        panel.style.setProperty('height', 'auto', 'important');
        panel.style.setProperty('overflow', 'visible', 'important');
      }
      revealed = true;
    }
    if (revealed) { control.setAttribute('aria-expanded', 'true'); opened++; }
  }

  // Tabs: a `role="tab"` names its panel with `aria-controls` and says which one is
  // showing with `aria-selected`; the others are hidden until chosen. Every panel is
  // content the author wrote for the page, and every one is shown.
  const shown = new Set();
  const show = (panel) => {
    if (!panel || shown.has(panel) || !isHidden(panel) || inChrome(panel)) return false;
    if (!(panel.textContent || '').trim()) return false;
    panel.removeAttribute('hidden');
    if (panel.getAttribute('aria-hidden') === 'true') panel.setAttribute('aria-hidden', 'false');
    const style = window.getComputedStyle(panel);
    if (style.display === 'none') panel.style.setProperty('display', 'block', 'important');
    if (style.visibility === 'hidden') panel.style.setProperty('visibility', 'visible', 'important');
    if (parseFloat(style.height) === 0 && panel.scrollHeight > 0) {
      panel.style.setProperty('height', 'auto', 'important');
      panel.style.setProperty('overflow', 'visible', 'important');
    }
    if (parseFloat(style.maxHeight) === 0) panel.style.setProperty('max-height', 'none', 'important');
    panel.setAttribute(markers.revealed, '1');
    shown.add(panel);
    return true;
  };
  for (const tab of document.querySelectorAll('[role="tab"][aria-controls]')) {
    if (inChrome(tab)) continue;
    for (const id of (tab.getAttribute('aria-controls') || '').split(/\s+/)) {
      if (show(document.getElementById(id))) { tab.setAttribute('aria-selected', 'true'); opened++; }
    }
  }

  // Panels a control names without ARIA: Bootstrap's `data-bs-target`, the older
  // `data-target` / `data-toggle-target`, and an in-page `href="#id"` on a button or link.
  // Only a target that is hidden is touched -- an `href="#section"` that points at a
  // visible heading is navigation, and a visible panel is left as it is -- and only one
  // that carries text of its own. Menus are never opened: a panel under `<nav>`,
  // `<header>`, `<footer>` or a menu role is site furniture, and opening a mega-menu
  // would put a hundred links on a page that shows none of them.
  const NAMED = ['data-bs-target', 'data-target', 'data-toggle-target', 'data-collapse-target', 'data-tab-target', 'data-panel'];
  for (const control of document.querySelectorAll(NAMED.map((a) => '[' + a + ']').join(',') + ',a[href^="#"],button[data-tab]')) {
    if (inChrome(control)) continue;
    let ref = null;
    for (const a of NAMED) { const v = control.getAttribute(a); if (v) { ref = v; break; } }
    if (!ref && control.tagName === 'A') ref = control.getAttribute('href');
    if (!ref) continue;
    ref = ref.trim();
    if (ref.startsWith('#')) ref = ref.slice(1);
    if (!ref || /[\s>+~\[\]:(),]/.test(ref)) continue;  // an id, not a selector
    const panel = document.getElementById(ref);
    if (!panel || panel === document.body || panel === document.documentElement) continue;
    if (/^(main|article|section)$/i.test(panel.tagName) && !isHidden(panel)) continue;
    if (show(panel)) {
      if (control.hasAttribute('aria-expanded')) control.setAttribute('aria-expanded', 'true');
      opened++;
    }
  }

  return opened;

  function isHidden(el) {
    if (el.hasAttribute('hidden') || el.getAttribute('aria-hidden') === 'true') return true;
    const s = window.getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return true;
    const box = el.getBoundingClientRect();
    return box.height <= 1 && (s.overflow === 'hidden' || s.overflowY === 'hidden' || parseFloat(s.maxHeight) === 0);
  }
  function inChrome(el) {
    for (let a = el; a && a !== document.body; a = a.parentElement) {
      const tag = a.tagName.toLowerCase();
      const role = (a.getAttribute('role') || '').toLowerCase();
      if (tag === 'nav' || tag === 'header' || tag === 'footer') return true;
      if (role === 'navigation' || role === 'banner' || role === 'contentinfo' || role === 'menu' || role === 'menubar' || role === 'dialog') return true;
    }
    return false;
  }
}
