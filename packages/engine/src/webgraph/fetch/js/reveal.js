(markers) => {
  // Open content the page collapsed, without clicking anything.
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

  return opened;
}
