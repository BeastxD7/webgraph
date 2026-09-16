import { CAM, PLINTH } from "../geometry";

import { PAGE_FRAG, PAGE_VERT, SKY_FRAG, SKY_VERT, THREAD_FRAG, THREAD_VERT } from "./shaders";
import { createSim, type Sim, STRIDE } from "./sim";

/**
 * The live field: WebGL2, hand-written, no library.
 *
 * One simulation (`sim.ts`) feeds up to two contexts. The back canvas draws the sky and
 * ground (one full-screen pass that also writes depth, so sunk pages vanish under the
 * ground), the pages behind the plinth, and the graph's threads. The front canvas, sized to
 * the frame's lower part and stacked above the card, draws only the pages between the
 * camera and the plinth, after a depth-only pass of the same ground so they too can sink.
 * The plinth is placed by unprojecting the card's DOM box onto the ground, so the card
 * stands on it at every frame size.
 *
 * Progress `p` (0 at rest → 1 organised) follows the prompt: the frame's `data-hero-state`
 * (`idle` · `focus` · `preview` · `running`, written by `SitePrompt`) sets a target and `p`
 * eases toward it, so the field organises while an example is hovered or a run starts and
 * scatters again when the pointer leaves. The loop runs only while the frame is on screen.
 * Reduced motion draws one frame. No WebGL2 leaves the still where it is.
 */
export type MountOptions = {
  frame: HTMLElement;
  back: HTMLCanvasElement;
  front?: HTMLCanvasElement;
};

const STATE_TARGET: Record<string, number> = { idle: 0, focus: 0.22, preview: 1, running: 1 };

type RGB = [number, number, number];

type Palette = {
  skyTop: RGB;
  skyMid: RGB;
  skyHorizon: RGB;
  haze: RGB;
  sun: RGB;
  cloud: RGB;
  fieldNear: RGB;
  fieldFar: RGB;
  paper: RGB;
  paperInk: RGB;
  junk: RGB;
  hidden: RGB;
  plinth: RGB;
  plinthSide: RGB;
  accent: RGB;
  dark: boolean;
};

const DPR_CAP = 1.5;
const REDUCE = "(prefers-reduced-motion: reduce)";

function parseColor(value: string): RGB {
  const v = value.trim();
  if (v.startsWith("#")) {
    const hex = v.length === 4 ? v.slice(1).split("").map((c) => c + c).join("") : v.slice(1, 7);
    const n = parseInt(hex, 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  const m = /rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/.exec(v);
  if (m) return [Number(m[1]) / 255, Number(m[2]) / 255, Number(m[3]) / 255];
  return [0.5, 0.5, 0.5];
}

function readPalette(el: HTMLElement): Palette {
  const cs = getComputedStyle(el);
  const c = (name: string) => parseColor(cs.getPropertyValue(name));
  return {
    skyTop: c("--sky-top"),
    skyMid: c("--sky-mid"),
    skyHorizon: c("--sky-horizon"),
    haze: c("--haze"),
    sun: c("--sun"),
    cloud: c("--cloud"),
    fieldNear: c("--field-near"),
    fieldFar: c("--field-far"),
    paper: c("--paper"),
    paperInk: c("--paper-ink"),
    junk: c("--paper-junk"),
    hidden: c("--paper-hidden"),
    plinth: c("--plinth"),
    plinthSide: c("--plinth-side"),
    accent: c("--accent"),
    dark: cs.colorScheme.includes("dark"),
  };
}

// ---- GL helpers ---------------------------------------------------------------------------

type Program = { prog: WebGLProgram; u: Record<string, WebGLUniformLocation | null>; a: Record<string, number> };

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const sh = gl.createShader(type);
  if (!sh) throw new Error("shader");
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(sh);
    gl.deleteShader(sh);
    throw new Error(`shader: ${log}`);
  }
  return sh;
}

function program(gl: WebGL2RenderingContext, vs: string, fs: string, uniforms: string[], attribs: string[]): Program {
  const prog = gl.createProgram();
  if (!prog) throw new Error("program");
  gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, vs));
  gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(`link: ${gl.getProgramInfoLog(prog)}`);
  const u: Program["u"] = {};
  for (const name of uniforms) u[name] = gl.getUniformLocation(prog, name);
  const a: Program["a"] = {};
  for (const name of attribs) a[name] = gl.getAttribLocation(prog, name);
  return { prog, u, a };
}

/** Column-major view-projection for the camera in `geometry.ts` at this aspect. */
function viewProjection(aspect: number): Float32Array {
  const f = 1 / Math.tan((CAM.fovDeg * Math.PI) / 360);
  const pitch = (CAM.pitchDeg * Math.PI) / 180;
  const c = Math.cos(pitch);
  const s = Math.sin(pitch);
  const n = CAM.near;
  const fa = CAM.far;
  const q = (fa + n) / (fa - n);
  const m = new Float32Array(16);
  m[0] = f / aspect;
  m[5] = f * c;
  m[6] = q * s;
  m[7] = s;
  m[9] = -f * s;
  m[10] = q * c;
  m[11] = c;
  m[13] = -f * CAM.eyeY * c;
  m[14] = -q * CAM.eyeY * s - (2 * fa * n) / (fa - n);
  m[15] = -CAM.eyeY * s;
  return m;
}

/** The world point where the ray through frame pixel (px, py) meets the plane y = planeY. */
function unproject(px: number, py: number, w: number, h: number, planeY: number): { x: number; z: number } | null {
  const tanHalf = Math.tan((CAM.fovDeg * Math.PI) / 360);
  const nx = (2 * px) / w - 1;
  const ny = 1 - (2 * py) / h;
  const dv = [nx * (w / h) * tanHalf, ny * tanHalf, 1];
  const pitch = (CAM.pitchDeg * Math.PI) / 180;
  const c = Math.cos(pitch);
  const s = Math.sin(pitch);
  const dir = [dv[0]!, dv[1]! * c + dv[2]! * s, dv[2]! * c - dv[1]! * s];
  if (dir[1]! >= -1e-4) return null;
  const t = (planeY - CAM.eyeY) / dir[1]!;
  return { x: dir[0]! * t, z: dir[2]! * t };
}

// ---- A context ----------------------------------------------------------------------------

type Layer = {
  canvas: HTMLCanvasElement;
  gl: WebGL2RenderingContext;
  sky: Program;
  pages: Program;
  thread: Program | null;
  vao: WebGLVertexArrayObject;
  inst: WebGLBuffer;
  threadVao: WebGLVertexArrayObject | null;
  threadBuf: WebGLBuffer | null;
  /** Instance range this layer draws. */
  first: number;
  count: number;
  /** Device-pixel size of the whole frame (the viewport); the canvas may be shorter. */
  w: number;
  h: number;
};

const SKY_UNIFORMS = [
  "uAspect", "uTanHalf", "uPitch", "uEyeY", "uNearFar", "uTime", "uDark", "uCloudOct", "uSkyTop", "uSkyMid",
  "uSkyHorizon", "uHaze", "uSun", "uCloud", "uFieldNear", "uFieldFar", "uPlinth", "uPlinthSide", "uPlinthBox",
  "uPlinthH", "uCardShadow",
];
const PAGE_UNIFORMS = ["uVP", "uTime", "uWind", "uIntro", "uGust", "uPaper", "uPaperInk", "uJunk", "uHidden", "uHaze", "uAccent", "uSun", "uFogK"];

function createLayer(canvas: HTMLCanvasElement, alpha: boolean, withThreads: boolean, sim: Sim): Layer | null {
  const gl = canvas.getContext("webgl2", {
    alpha,
    antialias: true,
    depth: true,
    premultipliedAlpha: true,
    powerPreference: "high-performance",
    preserveDrawingBuffer: false,
  });
  if (!gl) return null;
  const sky = program(gl, SKY_VERT, SKY_FRAG, SKY_UNIFORMS, []);
  const pages = program(gl, PAGE_VERT, PAGE_FRAG, PAGE_UNIFORMS, ["aQuad", "aPos", "aRot", "aSize", "aMeta"]);
  const thread = withThreads ? program(gl, THREAD_VERT, THREAD_FRAG, ["uVP", "uAccent", "uTime"], ["aPos", "aParam"]) : null;

  // The page: a 2×5 strip so the wind can bend it, as an indexed triangle list.
  const ROWS = 4;
  const quad = new Float32Array((ROWS + 1) * 4);
  for (let r = 0; r <= ROWS; r++) {
    quad[r * 4] = -0.5;
    quad[r * 4 + 1] = r / ROWS;
    quad[r * 4 + 2] = 0.5;
    quad[r * 4 + 3] = r / ROWS;
  }
  const index = new Uint16Array(ROWS * 6);
  for (let r = 0; r < ROWS; r++) {
    const a = r * 2;
    index.set([a, a + 1, a + 2, a + 1, a + 3, a + 2], r * 6);
  }
  const vao = gl.createVertexArray()!;
  gl.bindVertexArray(vao);
  const qb = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, qb);
  gl.bufferData(gl.ARRAY_BUFFER, quad, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(pages.a.aQuad!);
  gl.vertexAttribPointer(pages.a.aQuad!, 2, gl.FLOAT, false, 0, 0);
  const ib = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, index, gl.STATIC_DRAW);
  const inst = gl.createBuffer()!;
  gl.bindBuffer(gl.ARRAY_BUFFER, inst);
  gl.bufferData(gl.ARRAY_BUFFER, sim.data.byteLength, gl.DYNAMIC_DRAW);
  const stride = STRIDE * 4;
  const attr = (loc: number, size: number, offset: number) => {
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, size, gl.FLOAT, false, stride, offset * 4);
    gl.vertexAttribDivisor(loc, 1);
  };
  attr(pages.a.aPos!, 3, 0);
  attr(pages.a.aRot!, 2, 3);
  attr(pages.a.aSize!, 2, 5);
  attr(pages.a.aMeta!, 4, 7);
  gl.bindVertexArray(null);

  let threadVao: WebGLVertexArrayObject | null = null;
  let threadBuf: WebGLBuffer | null = null;
  if (thread) {
    threadVao = gl.createVertexArray();
    gl.bindVertexArray(threadVao);
    threadBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, threadBuf);
    gl.bufferData(gl.ARRAY_BUFFER, 4096 * 5 * 4, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(thread.a.aPos!);
    gl.vertexAttribPointer(thread.a.aPos!, 3, gl.FLOAT, false, 20, 0);
    gl.enableVertexAttribArray(thread.a.aParam!);
    gl.vertexAttribPointer(thread.a.aParam!, 2, gl.FLOAT, false, 20, 12);
    gl.bindVertexArray(null);
  }

  gl.enable(gl.DEPTH_TEST);
  gl.depthFunc(gl.LEQUAL);
  gl.disable(gl.CULL_FACE);
  return { canvas, gl, sky, pages, thread, vao, inst, threadVao, threadBuf, first: 0, count: 0, w: 1, h: 1 };
}

// ---- Mount ---------------------------------------------------------------------------------

export function mountField({ frame, back, front }: MountOptions): () => void {
  const reduce = matchMedia(REDUCE).matches;
  const phone = matchMedia("(max-width: 40rem)").matches;
  const count = phone ? 450 : 1000;
  const sim = createSim(count, 7);

  const layers: Layer[] = [];
  const backLayer = createLayer(back, false, true, sim);
  if (!backLayer) return () => {};
  layers.push(backLayer);
  const frontLayer = front ? createLayer(front, true, false, sim) : null;
  if (frontLayer) layers.push(frontLayer);

  const card = frame.querySelector<HTMLElement>("[data-scene-card]");
  let palette = readPalette(frame);
  let vp = viewProjection(1);
  let plinth: { x: number; z: number; hw: number; hd: number } = { x: PLINTH.x, z: PLINTH.z, hw: PLINTH.w / 2, hd: PLINTH.d / 2 };
  let cardShadow: [number, number, number, number] = [-1, 1, PLINTH.z - 0.2, 0];
  let frameW = 1;
  let frameH = 1;
  let time = 0;
  let intro = reduce ? 1 : 0;
  let p = 0;
  let intersecting = false;
  let visible = false;
  let raf = 0;
  let last = 0;
  let disposed = false;
  const gust = { x: 0, z: 0, s: 0, tx: 0, tz: 0, ts: 0 };

  const threadData = new Float32Array(4096 * 5);

  const fit = () => {
    const rect = frame.getBoundingClientRect();
    frameW = Math.max(1, rect.width);
    frameH = Math.max(1, rect.height);
    const dpr = Math.min(DPR_CAP, window.devicePixelRatio || 1);
    const W = Math.round(frameW * dpr);
    const H = Math.round(frameH * dpr);
    for (const layer of layers) {
      const ch = layer === frontLayer ? Math.round(layer.canvas.getBoundingClientRect().height * dpr) : H;
      if (layer.canvas.width !== W || layer.canvas.height !== ch) {
        layer.canvas.width = W;
        layer.canvas.height = ch;
      }
      layer.w = W;
      layer.h = H;
    }
    vp = viewProjection(frameW / frameH);
    placePlinth(rect);
  };

  // The plinth goes under the card: its foot's corners, unprojected onto the plinth's top.
  const placePlinth = (frameRect: DOMRect) => {
    let x = PLINTH.x;
    let z = PLINTH.z;
    let hw = PLINTH.w / 2;
    if (card) {
      const r = card.getBoundingClientRect();
      const yb = r.bottom - frameRect.top;
      const a = unproject(r.left - frameRect.left, yb, frameW, frameH, PLINTH.h);
      const b = unproject(r.right - frameRect.left, yb, frameW, frameH, PLINTH.h);
      if (a && b && a.z > 2.0 && a.z < 12) {
        x = (a.x + b.x) / 2;
        hw = (b.x - a.x) / 2 + 0.05;
        cardShadow = [a.x, b.x, a.z, 1];
        // The card's foot stands a step in from the plinth's front edge.
        z = a.z - 0.12 + Math.max(0.3, hw * 0.3);
      }
    }
    const hd = Math.max(0.3, hw * 0.3);
    if (Math.abs(x - plinth.x) > 0.01 || Math.abs(z - plinth.z) > 0.01 || Math.abs(hw - plinth.hw) > 0.01) {
      plinth = { x, z, hw, hd };
      sim.place(x, z, hw, hd);
    }
  };

  // Where the field is heading: set by the prompt through the frame's state attribute.
  const target = () => STATE_TARGET[frame.dataset.heroState ?? "idle"] ?? 0;

  const uploadThreads = (layer: Layer, glow: number) => {
    if (!layer.thread || !layer.threadBuf) return 0;
    const nodes = sim.nodes;
    let v = 0;
    const put = (x: number, y: number, z: number, u: number, a: number) => {
      threadData[v * 5] = x;
      threadData[v * 5 + 1] = y;
      threadData[v * 5 + 2] = z;
      threadData[v * 5 + 3] = u;
      threadData[v * 5 + 4] = a;
      v++;
    };
    // Threads: from the first node (the hub) to each other, and a chain along them, as thin
    // quads facing the camera (a horizontal offset is enough at this angle).
    const edges: Array<[number, number]> = [];
    for (let i = 1; i < nodes.length; i++) edges.push([0, i]);
    for (let i = 1; i + 1 < nodes.length; i += 2) edges.push([i, i + 1]);
    for (const [ia, ib] of edges) {
      const a = nodes[ia]!;
      const b = nodes[ib]!;
      const alpha = Math.min(a.glow, b.glow) * glow;
      if (alpha <= 0.001) continue;
      const wa = 0.0035 * a.z;
      const wb = 0.0035 * b.z;
      put(a.x - wa, a.y, a.z, 0, alpha);
      put(a.x + wa, a.y, a.z, 0, alpha);
      put(b.x - wb, b.y, b.z, 1, alpha);
      put(a.x + wa, a.y, a.z, 0, alpha);
      put(b.x + wb, b.y, b.z, 1, alpha);
      put(b.x - wb, b.y, b.z, 1, alpha);
    }
    // Node glows: a camera-facing disc at each node's top.
    for (const nd of nodes) {
      const alpha = nd.glow * glow;
      if (alpha <= 0.001) continue;
      const r = 0.03 * nd.z + 0.06;
      const cx = nd.x;
      const cy = nd.y;
      const cz = nd.z;
      const corner = (dx: number, dy: number) => put(cx + dx * r, cy + dy * r, cz, 2 + Math.hypot(dx, dy), alpha);
      corner(-1, -1);
      corner(1, -1);
      corner(-1, 1);
      corner(1, -1);
      corner(1, 1);
      corner(-1, 1);
    }
    const gl = layer.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, layer.threadBuf);
    gl.bufferData(gl.ARRAY_BUFFER, threadData.subarray(0, v * 5), gl.DYNAMIC_DRAW);
    return v;
  };

  const render = (layer: Layer) => {
    const { gl } = layer;
    const isFront = layer === frontLayer;
    gl.viewport(0, 0, layer.w, layer.h);
    gl.clearColor(0, 0, 0, 0);
    gl.clearDepth(1);
    gl.depthMask(true);
    gl.disable(gl.BLEND);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    // Sky and ground; on the front canvas only their depth.
    gl.useProgram(layer.sky.prog);
    const u = layer.sky.u;
    gl.uniform1f(u.uAspect!, frameW / frameH);
    gl.uniform1f(u.uTanHalf!, Math.tan((CAM.fovDeg * Math.PI) / 360));
    const pitch = (CAM.pitchDeg * Math.PI) / 180;
    gl.uniform2f(u.uPitch!, Math.cos(pitch), Math.sin(pitch));
    gl.uniform1f(u.uEyeY!, CAM.eyeY);
    gl.uniform2f(u.uNearFar!, CAM.near, CAM.far);
    gl.uniform1f(u.uTime!, time);
    gl.uniform1f(u.uDark!, palette.dark ? 1 : 0);
    gl.uniform1i(u.uCloudOct!, isFront ? 1 : phone ? 3 : 4);
    gl.uniform3fv(u.uSkyTop!, palette.skyTop);
    gl.uniform3fv(u.uSkyMid!, palette.skyMid);
    gl.uniform3fv(u.uSkyHorizon!, palette.skyHorizon);
    gl.uniform3fv(u.uHaze!, palette.haze);
    gl.uniform3fv(u.uSun!, palette.sun);
    gl.uniform3fv(u.uCloud!, palette.cloud);
    gl.uniform3fv(u.uFieldNear!, palette.fieldNear);
    gl.uniform3fv(u.uFieldFar!, palette.fieldFar);
    gl.uniform3fv(u.uPlinth!, palette.plinth);
    gl.uniform3fv(u.uPlinthSide!, palette.plinthSide);
    gl.uniform4f(u.uPlinthBox!, plinth.x, plinth.z, plinth.hw, plinth.hd);
    gl.uniform1f(u.uPlinthH!, PLINTH.h);
    gl.uniform4fv(u.uCardShadow!, cardShadow);
    if (isFront) gl.colorMask(false, false, false, false);
    gl.bindVertexArray(null);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    if (isFront) gl.colorMask(true, true, true, true);

    // Pages.
    gl.useProgram(layer.pages.prog);
    const pu = layer.pages.u;
    gl.uniformMatrix4fv(pu.uVP!, false, vp);
    gl.uniform1f(pu.uTime!, time);
    gl.uniform1f(pu.uWind!, 1 - p * 0.85);
    gl.uniform1f(pu.uIntro!, intro);
    gl.uniform3f(pu.uGust!, gust.x, gust.z, gust.s);
    gl.uniform3fv(pu.uPaper!, palette.paper);
    gl.uniform3fv(pu.uPaperInk!, palette.paperInk);
    gl.uniform3fv(pu.uJunk!, palette.junk);
    gl.uniform3fv(pu.uHidden!, palette.hidden);
    gl.uniform3fv(pu.uHaze!, palette.haze);
    gl.uniform3fv(pu.uAccent!, palette.accent);
    gl.uniform3fv(pu.uSun!, palette.sun);
    gl.uniform1f(pu.uFogK!, 0.03);
    gl.bindVertexArray(layer.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, layer.inst);
    const first = isFront ? 0 : sim.frontCount;
    const n = isFront ? sim.frontCount : sim.n - sim.frontCount;
    if (n > 0) {
      // Re-specified, not patched: a new store each frame, so the upload never waits on the
      // frame still drawing from the old one.
      gl.bufferData(gl.ARRAY_BUFFER, sim.data.subarray(first * STRIDE, (first + n) * STRIDE), gl.DYNAMIC_DRAW);
      gl.drawElementsInstanced(gl.TRIANGLES, 24, gl.UNSIGNED_SHORT, 0, n);
    }

    // Threads, additive, over everything at their depth.
    if (layer.thread && layer.threadVao) {
      const glow = p > 0.55 ? Math.min(1, (p - 0.55) / 0.35) : 0;
      const v = glow > 0 ? uploadThreads(layer, glow) : 0;
      if (v > 0) {
        gl.useProgram(layer.thread.prog);
        gl.uniformMatrix4fv(layer.thread.u.uVP!, false, vp);
        gl.uniform3fv(layer.thread.u.uAccent!, palette.accent);
        gl.uniform1f(layer.thread.u.uTime!, time);
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        gl.depthMask(false);
        gl.bindVertexArray(layer.threadVao);
        gl.drawArrays(gl.TRIANGLES, 0, v);
        gl.depthMask(true);
        gl.disable(gl.BLEND);
      }
    }
    gl.bindVertexArray(null);
  };

  const frameStep = (dt: number) => {
    time += dt;
    if (intro < 1) intro = Math.min(1, intro + dt / 1.6);
    // The gust follows the pointer with a little lag and dies when it leaves.
    gust.x += (gust.tx - gust.x) * Math.min(1, dt * 8);
    gust.z += (gust.tz - gust.z) * Math.min(1, dt * 8);
    gust.s += (gust.ts - gust.s) * Math.min(1, dt * 5);
    const goal = target();
    if (Math.abs(goal - p) > 0.0005) p += (goal - p) * Math.min(1, dt * 3.2);
    else p = goal;
    sim.step(dt, p);
    for (const layer of layers) render(layer);
  };

  const tick = (now: number) => {
    raf = 0;
    if (disposed) return;
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 1 / 60;
    last = now;
    frameStep(dt);
    if (visible && !reduce) raf = requestAnimationFrame(tick);
    else last = 0;
  };
  const wake = () => {
    if (!raf && !disposed) raf = requestAnimationFrame(tick);
  };

  // One still frame under reduced motion: settle the springs first so nothing is mid-flight.
  const still = () => {
    fit();
    p = target();
    for (let i = 0; i < 90; i++) sim.step(1 / 30, p);
    for (const layer of layers) render(layer);
  };

  const ro = new ResizeObserver(() => {
    fit();
    if (reduce) still();
    else wake();
  });
  ro.observe(frame);
  const io = new IntersectionObserver(
    ([entry]) => {
      intersecting = Boolean(entry?.isIntersecting);
      visible = intersecting && document.visibilityState === "visible";
      if (visible) wake();
    },
    { threshold: 0.01 },
  );
  io.observe(frame);
  const onVisibility = () => {
    visible = intersecting && document.visibilityState === "visible";
    if (visible) wake();
  };
  const onTheme = () => {
    palette = readPalette(frame);
    if (reduce) still();
    else wake();
  };
  const mo = new MutationObserver(onTheme);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
  const mq = matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", onTheme);

  const fine = matchMedia("(pointer: fine)").matches;
  const onPointer = (event: PointerEvent) => {
    const r = frame.getBoundingClientRect();
    const hit = unproject(event.clientX - r.left, event.clientY - r.top, frameW, frameH, 0);
    if (hit && hit.z > 3 && hit.z < 40) {
      gust.tx = hit.x;
      gust.tz = hit.z;
      gust.ts = 1;
    } else gust.ts = 0;
  };
  const onLeave = () => {
    gust.ts = 0;
  };
  if (fine && !reduce) {
    frame.addEventListener("pointermove", onPointer, { passive: true });
    frame.addEventListener("pointerleave", onLeave);
  }
  const onLost = (event: Event) => {
    event.preventDefault();
    dispose();
  };
  for (const layer of layers) layer.canvas.addEventListener("webglcontextlost", onLost);

  // The prompt's state changes are what move the field; under reduced motion each is a new still.
  const stateMo = new MutationObserver(() => {
    if (reduce) still();
    else wake();
  });
  stateMo.observe(frame, { attributes: true, attributeFilter: ["data-hero-state"] });
  document.addEventListener("visibilitychange", onVisibility);

  fit();
  if (reduce) still();
  else {
    // Draw the first frame before the intro starts so the still hands over without a gap.
    frameStep(0);
  }
  frame.dataset.field = reduce ? "still" : "live";
  // On screen until the observer says otherwise: the first frames must not wait for it.
  intersecting = true;
  visible = document.visibilityState === "visible";
  wake();

  function dispose() {
    if (disposed) return;
    disposed = true;
    delete frame.dataset.field;
    if (raf) cancelAnimationFrame(raf);
    ro.disconnect();
    io.disconnect();
    mo.disconnect();
    stateMo.disconnect();
    mq.removeEventListener("change", onTheme);
    document.removeEventListener("visibilitychange", onVisibility);
    frame.removeEventListener("pointermove", onPointer);
    frame.removeEventListener("pointerleave", onLeave);
    for (const layer of layers) {
      layer.canvas.removeEventListener("webglcontextlost", onLost);
      layer.gl.getExtension("WEBGL_lose_context")?.loseContext();
    }
  }
  return dispose;
}
