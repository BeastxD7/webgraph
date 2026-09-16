/**
 * The landing's ground: a slow gradient field in the ink-green family, a ruled grid — the
 * page is measured, and the ground says so — and a grain. All CSS (`globals.css` §7), no
 * script: the blobs drift on `transform` only, the grain is a static SVG tile, and under
 * `prefers-reduced-motion` the drift stops where it is.
 *
 * Kept off the copy columns: `muted` on `ground` is 7.1:1, the AAA floor with no headroom,
 * so the colour lives behind the stage and at the page's edges, and `--story-heat` (set by
 * the stage while the pain chapter is on screen) warms only the region behind the stage.
 */
export default function Backdrop() {
  return (
    <div aria-hidden className="landing-backdrop">
      <div className="bd-grid" />
      <div className="bd-blob bd-blob-a" />
      <div className="bd-blob bd-blob-b" />
      <div className="bd-blob bd-blob-c" />
      <div className="bd-heat" />
      <div className="bd-grain" />
    </div>
  );
}
