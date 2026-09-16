import { CAM, FIELD, mulberry32, type PageSeed, seedPages } from "../geometry";

/**
 * The pages' motion. Each page has a position, a yaw and a lean, and a velocity for each;
 * every frame it is pulled by a lightly under-damped spring toward a target that is a pure
 * function of the scroll progress `p`, so scrolling back up reverses the scene.
 *
 * Three things happen as `p` runs 0 → 1, each page on its own threshold:
 *   organise -- from its seeded, scattered stance to a slot in a row (reading order),
 *               facing the camera, upright; the wave runs outward from the plinth;
 *   sink     -- the junk and the hidden pages (kinds 1 and 2) go under the ground;
 *   lift     -- the graph nodes (kind 3) rise and glow, and the threads join them.
 */
export const STRIDE = 11; // floats per instance in the GPU buffer: pos3 rot2 size2 meta4
const FRONT_MAX_Z = 2.95;

export type Sim = {
  n: number;
  seeds: PageSeed[];
  /** Instance data, `STRIDE` floats each; front-band instances first. */
  data: Float32Array;
  /** How many instances stand between the camera and the plinth (the front canvas draws these). */
  frontCount: number;
  /** World positions of the graph nodes' tops after `step`, for the threads. */
  nodes: Array<{ x: number; y: number; z: number; glow: number }>;
  step(dt: number, p: number): void;
  /** Move the clearing (and the front/back split) to the plinth's actual place. */
  place(plinthX: number, plinthZ: number, halfW: number, halfD: number): void;
  settled(): boolean;
};

type Slot = { x: number; z: number };

/**
 * Rows in geometric progression: seen from `eyeY`, a row at z × ratio sits exactly one
 * page-height higher on screen than the row at z, so rows meet without overlapping -- the
 * field becomes lines of text. Columns are a constant step in the world.
 */
function buildSlots(zNear: number, zFar: number): Slot[][] {
  const rows: Slot[][] = [];
  const ratio = 1 / (1 - (FIELD.pageH * 1.12) / CAM.eyeY);
  for (let z = zNear; z < zFar; z *= ratio) {
    const sx = 0.24;
    const half = FIELD.xSpread * z;
    const row: Slot[] = [];
    for (let x = -half; x <= half; x += sx) row.push({ x, z });
    rows.push(row);
  }
  return rows;
}

export function createSim(count: number, seed = 7): Sim {
  const seeds = seedPages(count, seed);
  const rnd = mulberry32(seed * 31 + 5);
  const n = seeds.length;

  // State: current and velocity, five channels each.
  const cur = new Float32Array(n * 5); // x, y, z, yaw, lean
  const vel = new Float32Array(n * 5);
  const tgt = new Float32Array(n * 5);
  const chaos = new Float32Array(n * 5); // the scattered stance
  const order = new Float32Array(n * 3); // slot x, z, and 1 if the page got a slot
  const thr = new Float32Array(n * 3); // organise, sink, lift thresholds
  const glow = new Float32Array(n);
  const data = new Float32Array(n * STRIDE);
  const idx = new Uint32Array(n); // instance order: front band first

  let plinth = { x: 0, z: 7.6, hw: 1.7, hd: 0.75 };
  let frontCount = 0;
  let moving = true;

  seeds.forEach((s, i) => {
    chaos[i * 5] = s.x;
    chaos[i * 5 + 1] = 0;
    chaos[i * 5 + 2] = s.z;
    chaos[i * 5 + 3] = (rnd() - 0.5) * 0.9;
    chaos[i * 5 + 4] = s.lean;
    for (let k = 0; k < 5; k++) cur[i * 5 + k] = chaos[i * 5 + k]!;
    thr[i * 3 + 1] = 0.3 + rnd() * 0.34;
    thr[i * 3 + 2] = 0.56 + rnd() * 0.26;
  });

  const nodes: Sim["nodes"] = [];
  seeds.forEach((s, i) => {
    if (s.kind === 3) nodes.push({ x: s.x, y: s.h, z: s.z, glow: 0 });
    void i;
  });

  function assignSlots() {
    const rows = buildSlots(FIELD.zNear, FIELD.zFar);
    const taken = new Set<string>();
    const inPlinth = (x: number, z: number) =>
      Math.abs(x - plinth.x) < plinth.hw + 0.4 && Math.abs(z - plinth.z) < plinth.hd + 0.35;
    // A page keeps to its side of the line: the front canvas draws what stands before it,
    // the back canvas what stands behind, and a slot across the line would be drawn on the
    // wrong canvas -- over the prompt, or hidden by it.
    const frontZ = frontLimit();
    const sameSide = (za: number, zb: number) => za < frontZ === zb < frontZ;
    // Nearest pages claim first, so the front rows fill cleanly.
    const byZ = Array.from({ length: n }, (_, i) => i).sort((a, b) => seeds[a]!.z - seeds[b]!.z);
    for (const i of byZ) {
      const s = seeds[i]!;
      // The row nearest in 1/z, then the free column nearest in x, in a small spiral.
      let best = -1;
      let bestD = Infinity;
      rows.forEach((row, r) => {
        const dz = Math.abs(1 / row[0]!.z - 1 / s.z);
        if (dz < bestD) {
          bestD = dz;
          best = r;
        }
      });
      let found: Slot | null = null;
      for (let dr = 0; dr <= 2 && !found; dr++) {
        for (const r of dr === 0 ? [best] : [best - dr, best + dr]) {
          const row = rows[r];
          if (!row) continue;
          const sx = row[1] ? row[1].x - row[0]!.x : 0.2;
          const c0 = Math.round((s.x - row[0]!.x) / sx);
          for (let dc = 0; dc <= 6; dc++) {
            for (const c of dc === 0 ? [c0] : [c0 - dc, c0 + dc]) {
              const slot = row[c];
              if (!slot || taken.has(`${r}:${c}`) || inPlinth(slot.x, slot.z) || !sameSide(slot.z, s.z)) continue;
              taken.add(`${r}:${c}`);
              found = slot;
              break;
            }
            if (found) break;
          }
          if (found) break;
        }
      }
      order[i * 3] = found ? found.x : s.x;
      order[i * 3 + 1] = found ? found.z + (rnd() - 0.5) * 0.006 : s.z;
      order[i * 3 + 2] = found ? 1 : 0;
    }
    // The organise wave runs outward from the plinth.
    let maxD = 1;
    seeds.forEach((s) => {
      maxD = Math.max(maxD, Math.hypot(s.x - plinth.x, s.z - plinth.z));
    });
    seeds.forEach((s, i) => {
      const d = Math.hypot(s.x - plinth.x, s.z - plinth.z) / maxD;
      thr[i * 3] = 0.02 + Math.pow(d, 0.75) * 0.36 + rnd() * 0.04;
    });
  }

  /**
   * The front canvas draws pages nearer than this. Just before the plinth, and never beyond
   * the nearest rows: the clearing keeps everything between the two lines beside the prompt,
   * where either canvas draws it the same, and a page much taller on screen than the
   * prompt's foot would cover its controls.
   */
  function frontLimit(): number {
    return Math.min(plinth.z - plinth.hd - 0.1, FRONT_MAX_Z);
  }

  function partition() {
    const frontZ = frontLimit();
    let f = 0;
    let b = n - 1;
    seeds.forEach((s, i) => {
      if (s.z < frontZ) idx[f++] = i;
      else idx[b--] = i;
    });
    frontCount = f;
  }

  function place(px: number, pz: number, hw: number, hd: number) {
    plinth = { x: px, z: pz, hw, hd };
    // Pages standing where the plinth now is step out of it, to its nearer or farther side.
    seeds.forEach((s, i) => {
      if (Math.abs(s.x - px) < hw + 0.4 && Math.abs(s.z - pz) < hd + 0.35) {
        const toFront = s.z < pz;
        s.z = toFront ? pz - hd - 0.4 - rnd() * 0.3 : pz + hd + 0.4 + rnd() * 0.5;
        chaos[i * 5 + 2] = s.z;
        cur[i * 5 + 2] = s.z;
      }
    });
    assignSlots();
    partition();
    moving = true;
  }

  const smooth = (a: number, b: number, x: number) => {
    const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
    return t * t * (3 - 2 * t);
  };

  function step(dt: number, p: number) {
    // Under-damped, a hair: a little overshoot as a row snaps into place reads as weight.
    const w = 5.2;
    const damp = 1.75 * w;
    const k = w * w;
    let maxV = 0;
    let node = 0;
    for (let i = 0; i < n; i++) {
      const s = seeds[i]!;
      const o = smooth(thr[i * 3]!, thr[i * 3]! + 0.12, p);
      const sink = s.kind === 1 || s.kind === 2 ? smooth(thr[i * 3 + 1]!, thr[i * 3 + 1]! + 0.14, p) : 0;
      const lift = s.kind === 3 ? smooth(thr[i * 3 + 2]!, thr[i * 3 + 2]! + 0.16, p) : 0;

      const ox = order[i * 3 + 2] ? order[i * 3]! : chaos[i * 5]!;
      const oz = order[i * 3 + 2] ? order[i * 3 + 1]! : chaos[i * 5 + 2]!;
      tgt[i * 5] = chaos[i * 5]! + (ox - chaos[i * 5]!) * o;
      tgt[i * 5 + 2] = chaos[i * 5 + 2]! + (oz - chaos[i * 5 + 2]!) * o;
      tgt[i * 5 + 1] = -s.h * 1.35 * sink + (0.2 + s.h * 0.8 + (i % 5) * 0.05) * lift;
      tgt[i * 5 + 3] = chaos[i * 5 + 3]! * (1 - o);
      tgt[i * 5 + 4] = chaos[i * 5 + 4]! * (1 - o);
      glow[i] = lift;

      for (let c = 0; c < 5; c++) {
        const j = i * 5 + c;
        const a = k * (tgt[j]! - cur[j]!) - damp * vel[j]!;
        vel[j] = vel[j]! + a * dt;
        cur[j] = cur[j]! + vel[j]! * dt;
        if (c < 3) maxV = Math.max(maxV, Math.abs(vel[j]!));
      }
      if (s.kind === 3) {
        const nd = nodes[node++];
        if (nd) {
          nd.x = cur[i * 5]!;
          nd.y = cur[i * 5 + 1]! + s.h;
          nd.z = cur[i * 5 + 2]!;
          nd.glow = lift;
        }
      }
    }
    // Pack, front band first.
    for (let slot = 0; slot < n; slot++) {
      const i = idx[slot]!;
      const s = seeds[i]!;
      const o = slot * STRIDE;
      data[o] = cur[i * 5]!;
      data[o + 1] = cur[i * 5 + 1]!;
      data[o + 2] = cur[i * 5 + 2]!;
      data[o + 3] = cur[i * 5 + 3]!;
      data[o + 4] = cur[i * 5 + 4]!;
      data[o + 5] = s.w;
      data[o + 6] = s.h;
      data[o + 7] = s.kind;
      data[o + 8] = s.phase / (Math.PI * 2);
      data[o + 9] = glow[i]!;
      data[o + 10] = s.lines[0];
    }
    moving = maxV > 0.002;
  }

  assignSlots();
  partition();

  return {
    n,
    seeds,
    data,
    get frontCount() {
      return frontCount;
    },
    nodes,
    step,
    place,
    settled: () => !moving,
  };
}
