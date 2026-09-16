/**
 * GLSL ES 3.00 for the field. Three programs:
 *   sky    -- one full-screen triangle: the sky (gradient, sun or dusk line, fbm clouds,
 *             stars at dusk), and where the ray meets the ground, the meadow with its fog,
 *             the plinth (an analytic box) and the contact shadows. Writes depth so pages
 *             that sink below the ground are hidden by it.
 *   pages  -- instanced paper pages, a 2×5 strip bent by the wind in the vertex shader,
 *             with procedural text lines and fog in the fragment.
 *   thread -- the graph's threads and node glows, additive.
 */

const NOISE = /* glsl */ `
float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash12(i), hash12(i + vec2(1, 0)), u.x), mix(hash12(i + vec2(0, 1)), hash12(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p, int oct) {
  float v = 0.0;
  float a = 0.5;
  mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < 5; i++) {
    if (i >= oct) break;
    v += a * vnoise(p);
    p = m * p;
    a *= 0.5;
  }
  return v;
}
`;

export const SKY_VERT = /* glsl */ `#version 300 es
out vec2 vNdc;
void main() {
  // One triangle covering the clip square.
  vec2 p = vec2((gl_VertexID == 1) ? 3.0 : -1.0, (gl_VertexID == 2) ? 3.0 : -1.0);
  vNdc = p;
  gl_Position = vec4(p, 0.0, 1.0);
}
`;

export const SKY_FRAG = /* glsl */ `#version 300 es
precision highp float;
in vec2 vNdc;
out vec4 fragColor;

uniform float uAspect;      // width / height
uniform float uTanHalf;     // tan(fov / 2)
uniform vec2 uPitch;        // cos, sin of the camera's pitch (positive: up)
uniform float uEyeY;
uniform vec2 uNearFar;
uniform float uTime;
uniform float uDark;        // 0 day, 1 dusk
uniform int uCloudOct;      // fbm octaves for the clouds (fewer on a phone)
uniform vec3 uSkyTop, uSkyMid, uSkyHorizon, uHaze, uSun, uCloud;
uniform vec3 uFieldNear, uFieldFar;
uniform vec3 uPlinth, uPlinthSide;
uniform vec4 uPlinthBox;    // centre x, centre z, half width, half depth
uniform float uPlinthH;
uniform vec4 uCardShadow;   // x0, x1 of the card's foot on the plinth, its z, strength

${NOISE}

float depthOf(float vz) {
  float n = uNearFar.x, f = uNearFar.y;
  float ndc = ((f + n) * vz - 2.0 * f * n) / ((f - n) * vz);
  return ndc * 0.5 + 0.5;
}

// Signed distance to a rounded rectangle in the ground plane.
float sdBox2(vec2 p, vec2 b, float r) {
  vec2 d = abs(p) - b + r;
  return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0) - r;
}

void main() {
  // The view ray for this pixel, in world space (camera at (0, eyeY, 0) looking down +z).
  vec3 dv = normalize(vec3(vNdc.x * uAspect * uTanHalf, vNdc.y * uTanHalf, 1.0));
  vec3 dir = vec3(dv.x, dv.y * uPitch.x + dv.z * uPitch.y, dv.z * uPitch.x - dv.y * uPitch.y);
  vec3 eye = vec3(0.0, uEyeY, 0.0);

  // ---- sky: golden hour. The sun is low and to the right; its bloom warms the haze.
  float e = dir.y;
  vec3 sunDir = normalize(vec3(0.62, mix(0.09, -0.02, uDark), 1.0));
  float sd = max(dot(dir, sunDir), 0.0);
  float az = dot(normalize(vec2(dir.x, dir.z)), normalize(vec2(sunDir.x, sunDir.z)));

  vec3 sky = mix(uSkyHorizon, uSkyMid, smoothstep(-0.02, 0.2, e));
  sky = mix(sky, uSkyTop, smoothstep(0.14, 0.75, e));
  // The warm band at the horizon, strongest toward the sun.
  float band = exp(-max(e, 0.0) * 9.0) * (0.55 + 0.45 * az);
  sky = mix(sky, uSun, band * mix(0.38, 0.55, uDark));
  // Bloom: a broad glow, a tighter halo, and the disc itself by day.
  sky += uSun * (pow(sd, 3.0) * 0.22 + pow(sd, 24.0) * 0.45 + pow(sd, 400.0) * 1.2 * (1.0 - uDark));
  // At dusk the sun is under the horizon: only its afterglow along the line.
  sky += uSun * exp(-abs(e) * 30.0) * (0.35 + 0.65 * max(az, 0.0)) * 0.5 * uDark;

  // Clouds: the ray meets a sheet 300 m up; two fbm layers drift with the wind. Their
  // undersides take the sun's colour near the horizon.
  if (e > 0.004) {
    float t = 300.0 / e;
    vec2 cp = dir.xz * t;
    float c1 = fbm(cp * 0.0011 + vec2(uTime * 0.006, uTime * 0.002), uCloudOct);
    float c2 = fbm(cp * 0.0027 + vec2(-uTime * 0.004, uTime * 0.0035) + 7.0, max(uCloudOct - 1, 2));
    float dens = c1 * 0.72 + c2 * 0.38;
    float cover = smoothstep(0.44, 0.74, dens);
    float wisp = smoothstep(0.36, 0.56, dens) * 0.35;
    float fade = smoothstep(0.0, 0.12, e) * (1.0 - smoothstep(0.35, 0.9, e) * 0.55);
    vec3 lit = mix(uCloud, uSun, (1.0 - smoothstep(0.0, 0.35, e)) * (0.35 + 0.4 * az));
    lit = mix(lit, uSkyMid, 0.12 * (1.0 - uDark));
    vec3 shade = mix(lit, uSkyMid, 0.35);
    vec3 cloud = mix(shade, lit, smoothstep(0.5, 0.9, dens));
    sky = mix(sky, cloud, min(1.0, cover * 0.9 + wisp) * fade);
  }
  // Stars, at dusk only, high in the sky.
  if (uDark > 0.5 && e > 0.12) {
    vec2 sp = dir.xz / (e + 0.15) * 90.0;
    vec2 cell = floor(sp);
    float h = hash12(cell);
    float d = length(fract(sp) - 0.5 - (vec2(hash12(cell + 1.7), hash12(cell + 3.1)) - 0.5) * 0.6);
    float tw = 0.75 + 0.25 * sin(uTime * 1.3 + h * 40.0);
    sky += vec3(0.9, 0.92, 1.0) * smoothstep(0.986, 1.0, h) * smoothstep(0.09, 0.0, d) * smoothstep(0.12, 0.35, e) * tw;
  }

  // Film grain and a soft vignette, the photograph's own.
  float grain = (hash12(gl_FragCoord.xy + fract(uTime) * 61.0) - 0.5) * 0.035;
  float vig = 1.0 - 0.16 * smoothstep(0.55, 1.5, length(vNdc * vec2(1.0, 1.15)));

  if (dir.y >= -0.0005) {
    fragColor = vec4((sky + grain) * vig, 1.0);
    gl_FragDepth = 1.0;
    return;
  }

  // ---- ground
  float tg = -eye.y / dir.y;
  vec3 g = eye + dir * tg;
  float dist = tg;

  // The plinth: ray vs. an axis-aligned box on the ground.
  vec3 bmin = vec3(uPlinthBox.x - uPlinthBox.z, 0.0, uPlinthBox.y - uPlinthBox.w);
  vec3 bmax = vec3(uPlinthBox.x + uPlinthBox.z, uPlinthH, uPlinthBox.y + uPlinthBox.w);
  vec3 inv = 1.0 / dir;
  vec3 t0 = (bmin - eye) * inv;
  vec3 t1 = (bmax - eye) * inv;
  vec3 tmin = min(t0, t1);
  vec3 tmax = max(t0, t1);
  float tn = max(max(tmin.x, tmin.y), tmin.z);
  float tf = min(min(tmax.x, tmax.y), tmax.z);
  bool hitBox = tn < tf && tn > 0.0 && tn < tg;

  vec3 col;
  float vz;
  if (hitBox) {
    vec3 hp = eye + dir * tn;
    bool top = tmin.y >= max(tmin.x, tmin.z);
    col = top ? uPlinth : uPlinthSide;
    if (top) {
      // Stone: a fine grain, lighter toward the back edge.
      col *= 0.96 + 0.06 * vnoise(hp.xz * 14.0) + 0.03 * smoothstep(bmin.z, bmax.z, hp.z);
      // The card stands on it: a soft shadow along the card's foot.
      float dx = max(0.0, max(uCardShadow.x - hp.x, hp.x - uCardShadow.y));
      float dz = abs(hp.z - uCardShadow.z);
      float s = exp(-(dx * dx * 20.0 + dz * dz * 60.0)) * uCardShadow.w;
      col *= 1.0 - s * 0.55;
      // A hairline at the front edge.
      col *= 1.0 - smoothstep(0.03, 0.0, hp.z - bmin.z) * 0.12;
    } else {
      col *= 1.0 - smoothstep(uPlinthH, 0.0, hp.y) * 0.25;
    }
    dist = tn;
    vz = tn * dir.z;
  } else {
    // The meadow: near green to far green, a mown texture, a darker foot around the plinth.
    float n = vnoise(g.xz * 1.7) * 0.6 + vnoise(g.xz * 0.35 + 3.0) * 0.4;
    float band = fbm(vec2(g.x * 0.09, g.z * 0.05), 3);
    vec3 grass = mix(uFieldNear, uFieldFar, smoothstep(2.0, 40.0, dist));
    grass *= 0.9 + 0.2 * n;
    grass = mix(grass, grass * 0.9, smoothstep(0.55, 0.75, band));
    // The low sun rakes across it: warmer on the side facing the sun.
    grass = mix(grass, grass * (uSun * 0.5 + 0.6), smoothstep(-0.2, 1.0, az) * 0.25);
    float sd = sdBox2(g.xz - uPlinthBox.xy, uPlinthBox.zw, 0.3);
    grass *= 1.0 - smoothstep(0.7, -0.1, sd) * 0.4;
    col = grass;
    vz = tg * dir.z;
  }

  // Atmosphere: the far ground fades into the horizon's haze, warmer toward the sun.
  float fog = 1.0 - exp(-dist * 0.04);
  vec3 hazeCol = mix(uHaze, uSun, 0.18 * (0.5 + 0.5 * az));
  col = mix(col, mix(hazeCol, uSkyHorizon, 0.45), pow(fog, 1.7));
  fragColor = vec4((col + grain) * vig, 1.0);
  gl_FragDepth = depthOf(vz);
}
`;

export const PAGE_VERT = /* glsl */ `#version 300 es
precision highp float;
in vec2 aQuad;      // x in [-0.5, 0.5], y in [0, 1]
in vec3 aPos;       // base of the page: x, y (0 on the ground, below it when sunk), z
in vec2 aRot;       // yaw about y, lean about the page's own x axis
in vec2 aSize;      // width, height
in vec4 aMeta;      // kind, phase, glow (0..1), text-line seed

uniform mat4 uVP;
uniform float uTime;
uniform float uWind;      // 0..1, how much the wind moves the pages (order stills them)
uniform float uIntro;     // 0..1, pages grow out of the ground on first paint
uniform vec3 uGust;       // pointer on the ground: x, z, strength

out vec2 vUv;
out vec4 vMeta;
out float vDist;
out float vShade;

${NOISE}

void main() {
  float yaw = aRot.x;
  float lean = aRot.y;
  vec3 right = vec3(cos(yaw), 0.0, -sin(yaw));
  vec3 fwd = vec3(sin(yaw), 0.0, cos(yaw));
  vec3 up = normalize(vec3(0.0, cos(lean), 0.0) - fwd * sin(lean));

  // The intro: each page grows out of the ground in a wave keyed to its distance.
  float grow = smoothstep(0.0, 1.0, (uIntro * 1.7 - aMeta.y * 0.08 - aPos.z * 0.012));
  float h = aSize.y * grow;

  float hf = aQuad.y;
  float bend = hf * hf;
  vec3 pos = aPos + right * (aQuad.x * aSize.x) + up * (hf * h);

  // Wind: a slow travelling field plus each page's own flutter, all applied at the top.
  vec2 wp = aPos.xz * 0.18 + vec2(uTime * 0.35, uTime * 0.12);
  float w1 = vnoise(wp) - 0.5;
  float w2 = vnoise(wp * 2.3 + 9.0) - 0.5;
  vec2 wind = vec2(w1 * 0.7 + 0.25, w2 * 0.5) * 0.28;
  float flutter = sin(uTime * 2.1 + aMeta.y * 6.2831) * 0.035 + sin(uTime * 3.7 + aMeta.y * 12.0) * 0.012;
  vec2 sway = (wind + fwd.xz * flutter) * uWind * h;
  // The pointer's gust pushes nearby pages over.
  vec2 away = aPos.xz - uGust.xy;
  float gd = length(away);
  sway += (gd > 0.001 ? away / gd : vec2(0.0)) * pow(max(0.0, 1.0 - gd / 2.2), 2.0) * 0.45 * uGust.z * h;
  pos.xz += sway * bend;

  vUv = vec2(aQuad.x + 0.5, hf);
  vMeta = aMeta;
  vec4 clip = uVP * vec4(pos, 1.0);
  vDist = clip.w;
  // Two-sided paper under the low sun: the face toward it is lit, the shade only tints.
  vShade = 0.8 + 0.2 * abs(dot(fwd, normalize(vec3(0.62, 0.0, 1.0)))) - (0.06 * hf) * (1.0 - grow);
  gl_Position = clip;
}
`;

export const PAGE_FRAG = /* glsl */ `#version 300 es
precision highp float;
in vec2 vUv;
in vec4 vMeta;
in float vDist;
in float vShade;
out vec4 fragColor;

uniform vec3 uPaper, uPaperInk, uJunk, uHidden, uHaze, uAccent, uSun;
uniform float uFogK;

float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

void main() {
  int kind = int(vMeta.x + 0.5);
  vec3 col = kind == 1 ? uJunk : kind == 2 ? uHidden : uPaper;
  vec3 ink = kind == 1 ? uPaper : uPaperInk;

  // Three text lines, each a different length, in the page's own margins.
  float row = (vUv.y - 0.22) / 0.19;
  float r = fract(row);
  float i = floor(row);
  if (kind != 2 && i >= 0.0 && i < 3.0) {
    float len = fract(vMeta.w * (1.0 + i * 0.37)) * 0.45 + 0.4;
    float inLine = step(0.18, vUv.x) * step(vUv.x, 0.18 + 0.64 * len) * step(r, 0.34);
    // Soften with distance so far pages read as grey, not as stripes.
    col = mix(col, ink, inLine * 0.42 * (1.0 - smoothstep(6.0, 22.0, vDist)));
  }
  // Graph nodes: an accent edge that brightens as they lift.
  float edge = 1.0 - smoothstep(0.0, 0.09, min(min(vUv.x, 1.0 - vUv.x), min(vUv.y, 1.0 - vUv.y) * 0.75));
  col = mix(col, uAccent, edge * vMeta.z * 0.9);
  col = mix(col, mix(col, uAccent, 0.16), vMeta.z);

  // The sun's warmth on the lit face; the haze with distance.
  col *= mix(vec3(1.0), uSun * 1.05, (vShade - 0.8) * 0.9);
  col *= vShade;
  float fog = 1.0 - exp(-vDist * uFogK);
  col = mix(col, uHaze, pow(fog, 1.6));
  col += (hash12(gl_FragCoord.xy) - 0.5) * 0.03;
  fragColor = vec4(col, 1.0);
}
`;

export const THREAD_VERT = /* glsl */ `#version 300 es
precision highp float;
in vec3 aPos;
in vec2 aParam;   // u along the thread (0..1) or 2+radial for a glow disc, alpha
uniform mat4 uVP;
out vec2 vParam;
void main() {
  vParam = aParam;
  gl_Position = uVP * vec4(aPos, 1.0);
}
`;

export const THREAD_FRAG = /* glsl */ `#version 300 es
precision highp float;
in vec2 vParam;
out vec4 fragColor;
uniform vec3 uAccent;
uniform float uTime;
void main() {
  float a;
  if (vParam.x >= 2.0) {
    // A node's glow: a soft disc.
    float d = vParam.x - 2.0;
    a = pow(max(0.0, 1.0 - d), 2.2) * 0.9;
  } else {
    // A thread: a pulse travelling along it.
    float pulse = 0.55 + 0.45 * sin(vParam.x * 12.0 - uTime * 3.0);
    a = 0.45 + 0.55 * pulse;
  }
  a *= vParam.y;
  fragColor = vec4(uAccent * a, a);
}
`;
