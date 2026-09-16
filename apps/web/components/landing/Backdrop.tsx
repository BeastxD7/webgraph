/**
 * The landing's ground below the hero: a slow gradient field in the ink-green family, a ruled
 * grid — the page is measured, and the ground says so — and a grain. It starts where the hero
 * frame ends (`top` in the stylesheet), so the Earth has no grid and the story does. All CSS (`globals.css` §7), no
 * script: the blobs drift on `transform` only, the grain is a static SVG tile, and under
 * `prefers-reduced-motion` the drift stops where it is.
 *
 * Kept off the copy columns: `muted` on `ground` is 7.1:1, the AAA floor with no headroom,
 * so the colour lives at the page's edges here; the "how it reads a page" panel brings its
 * own faint ground behind its scene (`.how-stage`).
 */
export default function Backdrop() {
  return (
    <div aria-hidden className="landing-backdrop">
      <div className="bd-grid" />
      <div className="bd-blob bd-blob-a" />
      <div className="bd-blob bd-blob-b" />
      <div className="bd-blob bd-blob-c" />
      <div className="bd-grain" />
    </div>
  );
}
