/**
 * What the still and the live field share: the camera, the ground, and the seed of every
 * page in the meadow. Both draw the same pages from the same seed, so when the canvas
 * takes over from the server-rendered SVG nothing jumps.
 *
 * Units are metres. The camera stands at `eyeY`, looking down the +z axis, pitched a
 * little up so the horizon sits just below the frame's middle; the sky has the larger half.
 * Pages are ~A4 in proportion, standing on the ground plane y = 0.
 */
export const CAM = { eyeY: 1.4, pitchDeg: 2, fovDeg: 38, near: 0.5, far: 140 } as const;

export const FIELD = {
  zNear: 4.4,
  zFar: 48,
  /** Half-width of the populated strip at depth z, as a multiple of z (the frustum + margin). */
  xSpread: 0.72,
  pageH: 0.28,
  pageW: 0.2,
} as const;

/** The plinth the card stands on, before the live field moves it under the card's DOM box. */
export const PLINTH = { x: 0, z: 7.6, w: 3.4, d: 1.5, h: 0.22 } as const;

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
    const z = FIELD.zNear * Math.exp(rnd() * lnRange);
    const x = (rnd() * 2 - 1) * FIELD.xSpread * z;
    // The clearing: the plinth's footprint and a step around it.
    if (Math.abs(x - PLINTH.x) < PLINTH.w / 2 + 0.7 && Math.abs(z - PLINTH.z) < PLINTH.d / 2 + 0.9) continue;
    const r = rnd();
    let kind: PageKind = r < 0.09 ? 1 : r < 0.14 ? 2 : 0;
    // A handful of graph nodes in the mid-ground, where a thread between them can be seen.
    if (kind === 0 && graph < 9 && z > 9 && z < 20 && Math.abs(x) < 0.45 * z && rnd() < 0.08) {
      kind = 3;
      graph++;
    }
    const s = 0.82 + rnd() * 0.4;
    out.push({
      x,
      z,
      h: FIELD.pageH * s,
      w: FIELD.pageW * s * (0.9 + rnd() * 0.2),
      kind,
      phase: rnd() * Math.PI * 2,
      lean: (rnd() - 0.5) * 0.5,
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
