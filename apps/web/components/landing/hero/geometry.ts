/**
 * What the still and the live field share: the camera, the ground, and the seed of every
 * page in the meadow. Both draw the same pages from the same seed, so when the canvas
 * takes over from the server-rendered SVG nothing jumps.
 *
 * Units are metres. The camera is low -- `eyeY` is not much above the pages, the way the
 * reference's camera sits in the grass, so the nearest pages rise past the card's foot -- and
 * pitched a little up so the horizon sits just below the frame's middle. Pages are ~A4 in
 * proportion, standing on the ground plane y = 0.
 */
export const CAM = { eyeY: 0.7, pitchDeg: 2.5, fovDeg: 38, near: 0.3, far: 140 } as const;

export const FIELD = {
  zNear: 2.6,
  zFar: 48,
  /** Half-width of the populated strip at depth z, as a multiple of z (the frustum + margin). */
  xSpread: 0.72,
  pageH: 0.2,
  pageW: 0.142,
} as const;

/** The plinth the card stands on, before the live field moves it under the card's DOM box. */
export const PLINTH = { x: 0, z: 3.6, w: 1.9, d: 0.7, h: 0.06 } as const;

export type PageKind = 0 | 1 | 2 | 3; // paper · junk (a naive reader's content) · hidden · graph node

export type PageSeed = {
  x: number;
  z: number;
  /** Height and width in metres, jittered around the A4 proportion. */
  h: number;
  w: number;
  kind: PageKind;
  /** Wind phase and a standing lean, radians. */
  phase: number;
  lean: number;
  /** Where the page's text lines end, 0..1 of the width (three lines). */
  lines: readonly [number, number, number];
};

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * `n` pages, screen-uniform: depth is log-distributed so a row of pages near the camera and a
 * row far away cover the frame alike; x spans the frustum at that depth. A clearing is left
 * around the plinth. Deterministic for a seed.
 */
export function seedPages(n: number, seed = 7): PageSeed[] {
  const rnd = mulberry32(seed);
  const out: PageSeed[] = [];
  const lnRange = Math.log(FIELD.zFar / FIELD.zNear);
  let graph = 0;
  while (out.length < n) {
    // Skewed toward the camera: the far pages are a few pixels each and a texture, not a crowd.
    const z = FIELD.zNear * Math.exp(Math.pow(rnd(), 1.45) * lnRange);
    const x = (rnd() * 2 - 1) * FIELD.xSpread * z;
    // The clearing: the plinth's footprint and a step around it.
    if (Math.abs(x - PLINTH.x) < PLINTH.w / 2 + 0.4 && Math.abs(z - PLINTH.z) < PLINTH.d / 2 + 0.35) continue;
    const r = rnd();
    // No junk in the immediate foreground: a dark page that large would be a wall.
    let kind: PageKind = z < 3.4 ? 0 : r < 0.09 ? 1 : r < 0.14 ? 2 : 0;
    // A handful of graph nodes in the mid-ground, where a thread between them can be seen.
    if (kind === 0 && graph < 9 && z > 4.8 && z < 9 && Math.abs(x) > 1.1 && Math.abs(x) < 0.42 * z && rnd() < 0.14) {
      kind = 3;
      graph++;
    }
    // The nearest pages are a little larger -- they are the grass in front of the prompt --
    // but capped, so the tallest of them rises only a step past the prompt's foot.
    let s = (0.82 + rnd() * 0.4) * (z < 4.5 ? 1 + ((4.5 - z) / 4.5) * 0.2 : 1);
    if (z < 3.2) s = Math.min(s, 1.05);
    out.push({
      x,
      z,
      h: FIELD.pageH * s,
      w: FIELD.pageW * s * (0.9 + rnd() * 0.2),
      kind,
      phase: rnd() * Math.PI * 2,
      lean: (rnd() - 0.5) * 0.42,
      lines: [0.55 + rnd() * 0.4, 0.5 + rnd() * 0.45, 0.25 + rnd() * 0.5],
    });
  }
  return out;
}

/** Perspective projection of a world point for a frame of `w`×`h` CSS pixels. Null if behind. */
export function project(
  px: number,
  py: number,
  pz: number,
  w: number,
  h: number,
): { x: number; y: number; s: number } | null {
  const pitch = (CAM.pitchDeg * Math.PI) / 180;
  const cy = py - CAM.eyeY;
  // Rotate about x by -pitch (camera pitched up by `pitch`): view z' = z cos + y sin, y' = y cos - z sin.
  const vz = pz * Math.cos(pitch) + cy * Math.sin(pitch);
  const vy = cy * Math.cos(pitch) - pz * Math.sin(pitch);
  if (vz < CAM.near) return null;
  const f = h / 2 / Math.tan((CAM.fovDeg * Math.PI) / 360);
  return { x: w / 2 + (px * f) / vz, y: h / 2 - (vy * f) / vz, s: f / vz };
}
