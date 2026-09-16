/**
 * The hero before JavaScript, and under reduced motion until the renderer's own still: the
 * resting frame in the page's theme, rendered once by the same code
 * (`tools/render_hero_still.py`, headless Chromium) and saved under `public/earth/` as
 * `still-1440-light.jpg` and `still-1440-dark.jpg`. The stylesheet picks one by theme
 * (`--scene-still`, globals.css §8) and cover-fits it, so at any frame size it is the same
 * scene cropped, never stretched; the two preloads carry the theme's media query, so only
 * the system's one is fetched early. The live Earth hides it once it draws.
 */
export default function HeroStill() {
  return (
    <>
      <link rel="preload" as="image" href="/earth/still-1440-light.jpg" media="(prefers-color-scheme: light)" />
      <link rel="preload" as="image" href="/earth/still-1440-dark.jpg" media="(prefers-color-scheme: dark)" />
      <div className="hero-still" aria-hidden />
    </>
  );
}
