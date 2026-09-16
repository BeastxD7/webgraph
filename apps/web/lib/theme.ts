/**
 * The theme, kept the way next-themes keeps it.
 *
 * Storage key `theme`, values `light` | `dark` | `system`, written to `data-theme` on
 * `<html>` (removed for `system`, so the stylesheet's `prefers-color-scheme` block decides).
 * That is next-themes' default contract with `attribute: "data-theme"`, so the docs shell can
 * mount its `RootProvider` over the same storage later and both toggles agree without a
 * migration. No dependency is taken on for what is twelve lines of script.
 */

export type Theme = "light" | "dark" | "system";

export const THEME_KEY = "theme";

export const THEMES: readonly Theme[] = ["system", "light", "dark"];

export function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark" || value === "system";
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

export function readTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_KEY);
    return isTheme(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

export function writeTheme(theme: Theme): void {
  try {
    if (theme === "system") window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Private windows and blocked storage: the attribute still applies for this page.
  }
}

/**
 * Inlined in `<head>` so the attribute is set before first paint. Kept free of anything but
 * the storage read: a thrown error here would leave the page unstyled by theme, so it is
 * wrapped, and the values are re-checked rather than trusted.
 */
export const THEME_BOOT_SCRIPT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  THEME_KEY,
)});if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t)}}catch(e){}})();`;

/*
 * A store for `useSyncExternalStore`: the theme lives in localStorage and on `<html>`, both
 * outside React, so React subscribes to it rather than mirroring it in state. Another tab
 * changing the theme arrives through the `storage` event.
 */
const listeners = new Set<() => void>();

export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  // Another page (the docs shell has its own switch on the same key) may have changed the
  // stored value while no toggle of ours was mounted; catch up on mount.
  applyTheme(readTheme());
  const onStorage = (event: StorageEvent) => {
    if (event.key === THEME_KEY || event.key === null) {
      applyTheme(readTheme());
      listener();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function setTheme(theme: Theme): void {
  applyTheme(theme);
  writeTheme(theme);
  for (const listener of listeners) listener();
}

export const serverTheme = (): Theme => "system";
