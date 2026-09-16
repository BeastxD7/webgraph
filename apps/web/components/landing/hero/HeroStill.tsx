/**
 * The hero before JavaScript, and under reduced motion until the renderer's own still: the
 * resting frame, rendered once by the same code (`tools/render_hero_still.py`, headless
 * Chromium) and saved under `public/earth/`. Cover-fit, so at any frame size it is the
 * same scene cropped, never stretched. The live Earth hides it once it draws.
 */
export default function HeroStill() {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/earth/still-1440.jpg"
      alt=""
      aria-hidden
      decoding="async"
      fetchPriority="high"
      className="hero-still absolute inset-0 size-full object-cover"
    />
  );
}
