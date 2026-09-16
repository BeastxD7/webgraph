import { countryOf } from "@/lib/country";

import { CAM, EARTH, planetCentre } from "../geometry";

import { BLUR_FRAG, BRIGHT_FRAG, EARTH_FRAG, FULLSCREEN_VERT, POST_FRAG } from "./shaders";

/**
 * The live Earth: WebGL2, hand-written, no library.
 *
 * One canvas. The scene renders into an HDR framebuffer (RGBA16F where
 * EXT_color_buffer_float is there, RGBA8 otherwise): space, the planet as an analytic sphere
 * textured with NASA's Blue Marble, Black Marble and cloud map, the atmosphere's rim, the
 * sun disc. A bright pass at half size and two Gaussian passes at quarter size make the
 * bloom; the final pass adds it with the sun's rays, FXAA, ACES tone mapping, grain and a
 * vignette. Textures arrive small first (512×256) and are replaced by the 2k ones when they
 * land, so the first frame is never blank. The scene follows the page's theme: by night
 * (dark) the sunrise from behind the limb, stars and city lights; by day (light) the sun
 * high behind the viewer, a pale sky, and the marker as a green pin; `uTheme` crosses
 * between them over 600 ms when the toggle or the system setting changes.
 *
 * The planet turns once in five minutes on its own. A host in the frame's `data-hero-host`
 * (written by the prompt as an address is typed or an example hovered) turns it, on a
 * spring, to bring that country's longitude to face the camera, and lights a marker there;
 * `data-hero-state="running"` pushes the camera in for the hand-off to the run. The camera
 * settles in from further out on load, parallaxes with the pointer, drifts when idle, and
 * tilts down as the frame scrolls away. Quality tiers drop after a second over budget.
 * Reduced motion draws a still frame per state. No WebGL2 leaves the still where it is.
 */
export type MountOptions = { frame: HTMLElement; canvas: HTMLCanvasElement };

type V3 = [number, number, number];
const REDUCE = "(prefers-reduced-motion: reduce)";

/** Whether the page is in its dark theme: the explicit toggle first, then the system. */
function isDark(): boolean {
  const set = document.documentElement.dataset.theme;
  if (set === "dark" || set === "light") return set === "dark";
  return matchMedia("(prefers-color-scheme: dark)").matches;
}

// ---- GL helpers --------------------------------------------------------------------------------

type Program = { prog: WebGLProgram; u: Record<string, WebGLUniformLocation | null> };

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const sh = gl.createShader(type)!;
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(`shader: ${gl.getShaderInfoLog(sh)}`);
  return sh;
}

function program(gl: WebGL2RenderingContext, vs: string, fs: string): Program {
  const prog = gl.createProgram()!;
  gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, vs));
  gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(`link: ${gl.getProgramInfoLog(prog)}`);
  const u: Program["u"] = {};
  const count = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS) as number;
  for (let i = 0; i < count; i++) {
    const info = gl.getActiveUniform(prog, i);
    if (info) u[info.name.replace(/\[0\]$/, "")] = gl.getUniformLocation(prog, info.name);
  }
  return { prog, u };
}

type Fbo = { fb: WebGLFramebuffer; color: WebGLTexture; w: number; h: number };

function makeFbo(gl: WebGL2RenderingContext, w: number, h: number, hdr: boolean): Fbo {
  const color = gl.createTexture()!;
  gl.bindTexture(gl.TEXTURE_2D, color);
  if (hdr) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, w, h, 0, gl.RGBA, gl.HALF_FLOAT, null);
  else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const fb = gl.createFramebuffer()!;
  gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, color, 0);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  return { fb, color, w, h };
}

function freeFbo(gl: WebGL2RenderingContext, f: Fbo | null) {
  if (!f) return;
  gl.deleteFramebuffer(f.fb);
  gl.deleteTexture(f.color);
}

/** A texture that starts as one dark texel, takes the small image, then the large one. */
function loadTexture(gl: WebGL2RenderingContext, small: string, large: string, onLoad: () => void, luminance = false): WebGLTexture {
  const tex = gl.createTexture()!;
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB8, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE, new Uint8Array([6, 8, 12]));
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  let gen = 0;
  const put = (url: string, mine: number) => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => {
      if (gl.isContextLost() || mine < gen) return;
      gen = mine;
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, luminance ? gl.R8 : gl.RGB8, luminance ? gl.RED : gl.RGB, gl.UNSIGNED_BYTE, img);
      gl.generateMipmap(gl.TEXTURE_2D);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
      const aniso = gl.getExtension("EXT_texture_filter_anisotropic");
      if (aniso) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, Math.min(8, gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT) as number));
      onLoad();
    };
    img.src = url;
  };
  put(small, 1);
  put(large, 2);
  return tex;
}

// ---- Camera ------------------------------------------------------------------------------------

type Camera = { eye: V3; yaw: number; pitch: number; fov: number };

function basis(cam: Camera): { right: V3; up: V3; fwd: V3 } {
  const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
  const fwd: V3 = [sy * cp, sp, cy * cp];
  const right: V3 = [cy, 0, -sy];
  const up: V3 = [fwd[1] * right[2] - fwd[2] * right[1], fwd[2] * right[0] - fwd[0] * right[2], fwd[0] * right[1] - fwd[1] * right[0]];
  return { right, up, fwd };
}

/** Screen position in ndc of a world direction, or null behind the camera. */
function projectDir(cam: Camera, d: V3, aspect: number): [number, number] | null {
  const { right, up, fwd } = basis(cam);
  const vz = fwd[0] * d[0] + fwd[1] * d[1] + fwd[2] * d[2];
  if (vz <= 0.001) return null;
  const f = 1 / Math.tan(cam.fov / 2);
  return [((right[0] * d[0] + right[1] * d[1] + right[2] * d[2]) * f) / aspect / vz, ((up[0] * d[0] + up[1] * d[1] + up[2] * d[2]) * f) / vz];
}

const norm = (v: V3): V3 => {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
};

/** Quality tiers: dropped, never raised, after a second over budget. */
const TIERS = [
  { dpr: 1, starOct: 2, fxaa: 0, bloom: 0.18 },
  { dpr: 1.25, starOct: 3, fxaa: 0, bloom: 0.3 },
  { dpr: 1.5, starOct: 4, fxaa: 1, bloom: 0.3 },
] as const;

export function mountField({ frame, canvas }: MountOptions): () => void {
  const reduce = matchMedia(REDUCE).matches;
  const phone = matchMedia("(max-width: 40rem)").matches;
  const debug = new URLSearchParams(location.search).get("field") ?? "";
  const pinned = /tier:(\d)/.exec(debug);
  let tier = pinned ? Number(pinned[1]) : phone ? 1 : 2;

  const gl0 = canvas.getContext("webgl2", { alpha: false, antialias: false, depth: false, premultipliedAlpha: true, powerPreference: "high-performance" });
  if (!gl0) return () => {};
  const gl: WebGL2RenderingContext = gl0;
  const hdr = Boolean(gl.getExtension("EXT_color_buffer_float"));
  let earth: Program, bright: Program, blur: Program, post: Program;
  try {
    earth = program(gl, FULLSCREEN_VERT, EARTH_FRAG);
    bright = program(gl, FULLSCREEN_VERT, BRIGHT_FRAG);
    blur = program(gl, FULLSCREEN_VERT, BLUR_FRAG);
    post = program(gl, FULLSCREEN_VERT, POST_FRAG);
  } catch (error) {
    console.error("field:", error);
    return () => {};
  }

  let scene: Fbo | null = null;
  let half: Fbo | null = null;
  let q1: Fbo | null = null;
  let q2: Fbo | null = null;
  const wake = () => {
    if (!raf && !disposed) raf = requestAnimationFrame(tick);
  };
  const onTex = () => (reduce ? still() : wake());
  const texDay = loadTexture(gl, "/earth/day-512.jpg", "/earth/day-2k.jpg", onTex);
  const texNight = loadTexture(gl, "/earth/night-512.jpg", "/earth/night-2k.jpg", onTex);
  const texClouds = loadTexture(gl, "/earth/clouds-512.jpg", "/earth/clouds-2k.jpg", onTex, true);
  const texSpec = loadTexture(gl, "/earth/spec-1k.jpg", "/earth/spec-1k.jpg", onTex, true);

  let frameW = 1;
  let frameH = 1;
  let time = 0;
  let intro = reduce ? 1 : 0;
  let raf = 0;
  let last = 0;
  let disposed = false;
  let ema = 16;
  let overBudget = 0;
  let intersecting = false;
  let visible = false;
  let scrollTilt = 0;
  let push = 0; // 0..1, the camera pushing in for a run
  // The planet's turn, and the spring that brings a country round.
  let rot = 0;
  let rotV = 0;
  let rotTarget: number | null = null;
  let tilt = EARTH.tilt;
  let tiltV = 0;
  let tiltTarget = EARTH.tilt;
  let marker: { lat: number; lon: number; s: number } = { lat: 0, lon: 0, s: 0 };
  let host = "";
  // The theme: 0 is the night scene, 1 the day scene; it crosses over 600 ms.
  let themeTarget = isDark() ? 0 : 1;
  let theme = themeTarget;
  const par = { x: 0, y: 0, tx: 0, ty: 0, vx: 0, vy: 0 };
  const rest: Camera = { eye: [0, 0, 0], yaw: 0, pitch: 0, fov: (CAM.fovDeg * Math.PI) / 180 };
  const live: Camera = { eye: [0, 0, 0], yaw: 0, pitch: 0, fov: rest.fov };
  let centre: V3 = planetCentre();

  const fovFor = (aspect: number) => Math.min(rest.fov, 2 * Math.atan(Math.tan((31 * Math.PI) / 180) / aspect));

  const fit = () => {
    const rect = frame.getBoundingClientRect();
    frameW = Math.max(1, rect.width);
    frameH = Math.max(1, rect.height);
    const dpr = Math.min(TIERS[tier]!.dpr, window.devicePixelRatio || 1);
    const W = Math.round(frameW * dpr);
    const H = Math.round(frameH * dpr);
    rest.fov = fovFor(frameW / frameH);
    live.fov = rest.fov;
    if (canvas.width !== W || canvas.height !== H || !scene) {
      canvas.width = W;
      canvas.height = H;
      freeFbo(gl, scene);
      freeFbo(gl, half);
      freeFbo(gl, q1);
      freeFbo(gl, q2);
      scene = makeFbo(gl, W, H, hdr);
      half = makeFbo(gl, Math.max(1, W >> 1), Math.max(1, H >> 1), hdr);
      q1 = makeFbo(gl, Math.max(1, W >> 2), Math.max(1, H >> 2), hdr);
      q2 = makeFbo(gl, Math.max(1, W >> 2), Math.max(1, H >> 2), hdr);
    }
  };

  // The longitude under the limb's top is longitude zero plus the rotation (the axis leans
  // in the camera's plane, so the limb's crown lies on the prime meridian of the frame).
  // At rest Europe is there, its lights on the night side.
  rot = (30 * Math.PI) / 180;

  /**
   * The normal of the planet under a frame point (ndc), with the resting camera, or null
   * where the ray misses it.
   */
  const normalUnder = (nx: number, ny: number): V3 | null => {
    const tanHalf = Math.tan(rest.fov / 2);
    const dir = norm([nx * (frameW / frameH) * tanHalf, ny * tanHalf, 1]);
    const c = planetCentre();
    const b = -(dir[0] * c[0] + dir[1] * c[1] + dir[2] * c[2]);
    const h = b * b - (c[0] * c[0] + c[1] * c[1] + c[2] * c[2] - 1);
    if (h < 0) return null;
    const t = -b - Math.sqrt(h);
    return norm([dir[0] * t - c[0], dir[1] * t - c[1], dir[2] * t - c[2]]);
  };

  // A host was typed or hovered: turn to its country and light the marker; or let it go.
  // The country is brought to a point beside the prompt, on the night side: the tilt that
  // puts its latitude there, then the rotation that puts its longitude there.
  const readHost = () => {
    const next = frame.dataset.heroHost ?? "";
    if (next === host) return;
    host = next;
    const c = next ? countryOf(next) : null;
    const lat = c ? (c.lat * Math.PI) / 180 : 0;
    const lon = c ? (c.lon * Math.PI) / 180 : 0;
    const n = c ? (normalUnder(-0.4, -0.72) ?? normalUnder(0, -0.62)) : null;
    if (c && n) {
      // nl.y = n.y cos t - n.z sin t must equal sin(lat): R cos(t + phi) = sin(lat), two
      // solutions; take the one nearer the resting tilt, within the lean the scene allows.
      const R = Math.hypot(n[1], n[2]);
      const phi = Math.atan2(n[2], n[1]);
      const ratio = Math.max(-1, Math.min(1, Math.sin(lat) / R));
      const clampT = (v: number) => Math.min((70 * Math.PI) / 180, Math.max((-75 * Math.PI) / 180, v));
      const t1 = clampT(Math.acos(ratio) - phi);
      const t2 = clampT(-Math.acos(ratio) - phi);
      const t = Math.abs(t1 - EARTH.tilt) <= Math.abs(t2 - EARTH.tilt) ? t1 : t2;
      tiltTarget = t;
      const ct = Math.cos(t), st = Math.sin(t);
      const nlx = n[0], nlz = n[1] * st + n[2] * ct;
      let target = lon - Math.atan2(nlx, nlz);
      target = target - Math.round((target - rot) / (2 * Math.PI)) * 2 * Math.PI;
      rotTarget = target;
      marker = { lat, lon, s: marker.s };
    } else {
      rotTarget = null;
      tiltTarget = EARTH.tilt;
    }
  };

  const moveCamera = (dt: number) => {
    const k = 30, c = 2 * Math.sqrt(k) * 0.9;
    par.vx += (k * (par.tx - par.x) - c * par.vx) * dt;
    par.vy += (k * (par.ty - par.y) - c * par.vy) * dt;
    par.x += par.vx * dt;
    par.y += par.vy * dt;
    const drift = reduce ? 0 : 1;
    const enter = reduce ? 1 : 1 - Math.pow(1 - Math.min(1, intro), 3);
    live.yaw = par.x * 0.016 + Math.sin(time * 0.09) * 0.003 * drift;
    live.pitch = par.y * 0.01 + Math.sin(time * 0.06) * 0.002 * drift - scrollTilt * 0.05;
    // Further out on load, then in; further in for a run.
    const dist = CAM.distance + (1 - enter) * 0.7 - push * 0.55;
    centre = planetCentre(dist);
  };

  const stepPlanet = (dt: number) => {
    readHost();
    const w = 5.5, damp = 2 * w * 0.92;
    tiltV += (w * w * (tiltTarget - tilt) - damp * tiltV) * dt;
    tilt += tiltV * dt;
    if (rotTarget !== null) {
      rotV += (w * w * (rotTarget - rot) - damp * rotV) * dt;
      rot += rotV * dt;
      marker.s += (1 - marker.s) * Math.min(1, dt * 4);
    } else {
      rotV = 0;
      rot += ((2 * Math.PI) / EARTH.turnSeconds) * dt * (reduce ? 0 : 1);
      marker.s += (0 - marker.s) * Math.min(1, dt * 4);
    }
    const running = frame.dataset.heroState === "running";
    push += ((running ? 1 : 0) - push) * Math.min(1, dt * 6);
    theme += Math.sign(themeTarget - theme) * Math.min(Math.abs(themeTarget - theme), dt / 0.6);
  };

  const draw = () => {
    if (!scene || !half || !q1 || !q2) return;
    const q = TIERS[tier]!;
    const aspect = frameW / frameH;
    const { right, up, fwd } = basis(live);
    // The sun sits at 62% of the half-width on any aspect, so a phone keeps it in frame.
    const sunAz = Math.min(EARTH.sunAz, Math.atan(Math.tan(live.fov / 2) * aspect * 0.62));
    const sunS = norm([Math.sin(sunAz) * Math.cos(EARTH.sunEl), Math.sin(EARTH.sunEl), Math.cos(sunAz) * Math.cos(EARTH.sunEl)]);
    const nightL = norm([...EARTH.light] as V3);
    const dayL = norm([...EARTH.dayLight] as V3);
    const sunL = norm([nightL[0] + (dayL[0] - nightL[0]) * theme, nightL[1] + (dayL[1] - nightL[1]) * theme, nightL[2] + (dayL[2] - nightL[2]) * theme]);

    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.BLEND);
    // 1. The scene.
    gl.bindFramebuffer(gl.FRAMEBUFFER, scene.fb);
    gl.viewport(0, 0, scene.w, scene.h);
    gl.useProgram(earth.prog);
    const u = earth.u;
    gl.uniformMatrix3fv(u.uCamRot!, false, [right[0], right[1], right[2], up[0], up[1], up[2], fwd[0], fwd[1], fwd[2]]);
    gl.uniform3fv(u.uEye!, live.eye);
    gl.uniform1f(u.uAspect!, aspect);
    gl.uniform1f(u.uTanHalf!, Math.tan(live.fov / 2));
    gl.uniform1f(u.uTime!, time);
    gl.uniform3fv(u.uCentre!, centre);
    gl.uniform3fv(u.uSunL!, sunL);
    gl.uniform3fv(u.uSunS!, sunS);
    gl.uniform1f(u.uRot!, rot);
    gl.uniform1f(u.uTilt!, tilt);
    gl.uniform4f(u.uMarker!, marker.lat, marker.lon, marker.s, 0);
    gl.uniform1f(u.uTheme!, theme);
    gl.uniform1i(u.uStarOct!, q.starOct);
    const bind = (unit: number, tex: WebGLTexture, name: string) => {
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.uniform1i(u[name]!, unit);
    };
    bind(0, texDay, "uDay");
    bind(1, texNight, "uNight");
    bind(2, texClouds, "uClouds");
    bind(3, texSpec, "uSpec");
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    // 2. Bloom: the bright pass at half size, blurred twice at quarter size.
    gl.bindFramebuffer(gl.FRAMEBUFFER, half.fb);
    gl.viewport(0, 0, half.w, half.h);
    gl.useProgram(bright.prog);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, scene.color);
    gl.uniform1i(bright.u.uColor!, 0);
    gl.uniform1f(bright.u.uThreshold!, 1.4);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.useProgram(blur.prog);
    gl.uniform1i(blur.u.uColor!, 0);
    for (let pass = 0; pass < 2; pass++) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, q1.fb);
      gl.viewport(0, 0, q1.w, q1.h);
      gl.bindTexture(gl.TEXTURE_2D, pass === 0 ? half.color : q2.color);
      gl.uniform2f(blur.u.uStep!, (pass === 0 ? 1.5 : 3) / q1.w, 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.bindFramebuffer(gl.FRAMEBUFFER, q2.fb);
      gl.bindTexture(gl.TEXTURE_2D, q1.color);
      gl.uniform2f(blur.u.uStep!, 0, (pass === 0 ? 1.5 : 3) / q1.h);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }

    // 3. The final pass.
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.useProgram(post.prog);
    const pu = post.u;
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, scene.color);
    gl.uniform1i(pu.uColor!, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, q2.color);
    gl.uniform1i(pu.uBloom!, 1);
    gl.uniform2f(pu.uTexel!, 1 / scene.w, 1 / scene.h);
    const sp = projectDir(live, sunS, aspect) ?? [0, -2];
    gl.uniform2f(pu.uSunPx!, sp[0], sp[1]);
    // The sun above the limb: how far above, in the planet's angular radius, decides the rays.
    const toC = norm(centre);
    const angC = Math.acos(Math.max(-1, Math.min(1, toC[0] * sunS[0] + toC[1] * sunS[1] + toC[2] * sunS[2])));
    const angR = Math.asin(1 / Math.hypot(centre[0], centre[1], centre[2]));
    const vis = Math.min(1, Math.max(0, (angC - angR + 0.05) / 0.07)) * (1 - theme);
    gl.uniform1f(pu.uSunVis!, vis);
    gl.uniform1f(pu.uAspect!, aspect);
    gl.uniform1f(pu.uExposure!, 1.1 - 0.15 * theme);
    gl.uniform1f(pu.uGrain!, 0.028 - 0.008 * theme);
    gl.uniform1f(pu.uVignette!, 0.28 - 0.14 * theme);
    gl.uniform1f(pu.uTime!, time);
    gl.uniform1f(pu.uBloomK!, q.bloom);
    gl.uniform1i(pu.uFxaa!, q.fxaa);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };

  const frameStep = (dt: number) => {
    time += dt;
    if (intro < 1) intro = Math.min(1, intro + dt / 1.5);
    const top = frame.getBoundingClientRect().top;
    scrollTilt = Math.min(1, Math.max(0, -top / Math.max(1, frameH)));
    stepPlanet(dt);
    moveCamera(dt);
    draw();
  };

  const budget = (ms: number) => {
    if (tier === 0 || time < 3 || pinned) return;
    ema += (ms - ema) * 0.1;
    overBudget = ema > 24 ? overBudget + 1 : 0;
    if (overBudget > 60) {
      tier--;
      overBudget = 0;
      ema = 16;
      fit();
    }
  };

  const tick = (now: number) => {
    raf = 0;
    if (disposed) return;
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 1 / 60;
    if (last) budget(now - last);
    last = now;
    frameStep(dt);
    if (debug) frame.dataset.fieldStats = `tier ${tier} frame ${ema.toFixed(1)}`;
    if (visible && !reduce) raf = requestAnimationFrame(tick);
    else last = 0;
  };

  const still = () => {
    fit();
    readHost();
    if (rotTarget !== null) {
      rot = rotTarget;
      tilt = tiltTarget;
      marker.s = 1;
    }
    moveCamera(0);
    draw();
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
  const fine = matchMedia("(pointer: fine)").matches;
  const onPointer = (event: PointerEvent) => {
    const r = frame.getBoundingClientRect();
    par.tx = ((event.clientX - r.left) / Math.max(1, r.width)) * 2 - 1;
    par.ty = ((event.clientY - r.top) / Math.max(1, r.height)) * 2 - 1;
  };
  const onLeave = () => {
    par.tx = 0;
    par.ty = 0;
  };
  if (fine && !reduce) {
    frame.addEventListener("pointermove", onPointer, { passive: true });
    frame.addEventListener("pointerleave", onLeave);
  }
  const onLost = (event: Event) => {
    event.preventDefault();
    dispose();
  };
  canvas.addEventListener("webglcontextlost", onLost);
  const stateMo = new MutationObserver(() => (reduce ? still() : wake()));
  stateMo.observe(frame, { attributes: true, attributeFilter: ["data-hero-state", "data-hero-host"] });
  // The theme: the toggle writes data-theme on the root; the system setting may change too.
  const onTheme = () => {
    themeTarget = isDark() ? 0 : 1;
    if (reduce) {
      theme = themeTarget;
      still();
    } else wake();
  };
  const themeMo = new MutationObserver(onTheme);
  themeMo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const scheme = matchMedia("(prefers-color-scheme: dark)");
  scheme.addEventListener("change", onTheme);
  document.addEventListener("visibilitychange", onVisibility);
  const onScroll = () => wake();
  window.addEventListener("scroll", onScroll, { passive: true });

  fit();
  if (reduce) still();
  else frameStep(0);
  frame.dataset.field = reduce ? "still" : "live";
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
    stateMo.disconnect();
    themeMo.disconnect();
    scheme.removeEventListener("change", onTheme);
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("scroll", onScroll);
    frame.removeEventListener("pointermove", onPointer);
    frame.removeEventListener("pointerleave", onLeave);
    canvas.removeEventListener("webglcontextlost", onLost);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  }
  return dispose;
}
