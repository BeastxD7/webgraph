/**
 * GLSL ES 3.00 for the Earth. Programs:
 *   earth   -- one full-screen triangle: space (stars with a magnitude distribution, a faint
 *              Milky Way), the planet as an analytic sphere textured with NASA's Blue Marble,
 *              Black Marble and cloud map, lit by the sun with a soft terminator, ocean glint,
 *              cloud shadows and a Rayleigh-style rim; the sun disc. HDR linear out.
 *   bright  -- the bloom's source: what is brighter than a threshold, at half size.
 *   blur    -- a separable Gaussian, run twice.
 *   post    -- FXAA, bloom, the sun's rays, ACES tone mapping, grain, vignette.
 * Comments in the GLSL are short on purpose: they ship.
 */

const COMMON = /* glsl */ `
float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
vec2 grad2(vec2 i) {
  vec3 p = fract(i.xyx * vec3(0.1031, 0.1030, 0.0973));
  p += dot(p, p.yzx + 33.33);
  return fract((p.xx + p.yz) * p.zy) * 2.0 - 1.0;
}
float gnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  float a = dot(grad2(i), f);
  float b = dot(grad2(i + vec2(1, 0)), f - vec2(1, 0));
  float c = dot(grad2(i + vec2(0, 1)), f - vec2(0, 1));
  float d = dot(grad2(i + vec2(1, 1)), f - vec2(1, 1));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y) * 1.6;
}
float fbm(vec2 p, int oct) {
  float r = 0.0;
  float a = 1.0;
  for (int i = 0; i < 4; i++) {
    if (i >= oct) break;
    r += a * gnoise(p);
    a *= 0.5;
    p = p * 2.0 + 0.3;
  }
  return r;
}
`;

export const FULLSCREEN_VERT = /* glsl */ `#version 300 es
out vec2 vNdc;
void main() {
  vec2 p = vec2((gl_VertexID == 1) ? 3.0 : -1.0, (gl_VertexID == 2) ? 3.0 : -1.0);
  vNdc = p;
  gl_Position = vec4(p, 0.0, 1.0);
}
`;

export const EARTH_FRAG = /* glsl */ `#version 300 es
precision highp float;
in vec2 vNdc;
out vec4 fragColor;
uniform mat3 uCamRot;
uniform vec3 uEye;
uniform float uAspect, uTanHalf;
uniform float uTime;
uniform vec3 uCentre;        // the planet's centre; radius 1
uniform vec3 uSunL;          // the light's direction (toward the sun)
uniform vec3 uSunS;          // where the sun disc is drawn (toward it)
uniform float uRot, uTilt;   // longitude of rotation; the axis tilt toward the camera
uniform vec4 uMarker;        // lat, lon, strength, unused
uniform float uTheme;        // 0 the night scene, 1 the day scene; between them while the theme changes
uniform int uStarOct;
uniform sampler2D uDay, uNight, uClouds, uSpec;
${COMMON}

vec3 srgb(vec3 c) { return pow(c, vec3(2.2)); }

vec3 stars(vec3 dir) {
  vec3 a = abs(dir);
  vec2 sp = a.y > a.x && a.y > a.z ? dir.xz / dir.y : (a.x > a.z ? dir.yz / dir.x : dir.xy / dir.z);
  float face = a.y > a.x && a.y > a.z ? 1.0 : (a.x > a.z ? 2.0 : 3.0);
  vec3 col = vec3(0.0);
  for (int k = 0; k < 3; k++) {
    float sc = k == 0 ? 90.0 : k == 1 ? 200.0 : 420.0;
    vec2 q = sp * sc + float(k) * 17.0 + face * 31.0;
    vec2 cell = floor(q);
    float h = hash12(cell);
    vec2 off = vec2(hash12(cell + 1.3), hash12(cell + 2.7)) - 0.5;
    float d = length(fract(q) - 0.5 - off * 0.7) * sc;
    // A magnitude distribution: many faint, a few bright, by a steep power of the hash.
    float mag = pow(smoothstep(0.5, 1.0, h), 5.0);
    float thr = k == 0 ? 0.8 : k == 1 ? 0.72 : 0.64;
    float on = step(thr, h);
    float size = 0.4 + mag * 1.8;
    float star = on * exp(-d * d / (size * size)) * (0.12 + mag * 2.4);
    float sc2 = 1.0 - 0.03 * sin(uTime * (1.0 + h * 3.0) + h * 40.0);
    vec3 tint = mix(vec3(0.75, 0.85, 1.0), vec3(1.0, 0.9, 0.72), pow(hash12(cell + 5.1), 2.0));
    col += tint * star * sc2 * (k == 0 ? 1.0 : k == 1 ? 0.6 : 0.3);
  }
  vec3 mwN = normalize(vec3(0.55, 0.5, -0.67));
  float band = exp(-pow(dot(dir, mwN) * 3.5, 2.0));
  vec3 along = normalize(cross(mwN, vec3(0.0, 1.0, 0.0)));
  vec2 mwUv = vec2(dot(dir, along), dot(dir, mwN)) * 5.0;
  float neb = fbm(mwUv * 1.5, uStarOct) * 0.5 + 0.5;
  float dust = smoothstep(0.4, 0.7, fbm(mwUv * 3.0 + 9.0, 3) * 0.5 + 0.5);
  col += mix(vec3(0.5, 0.58, 0.8), vec3(0.9, 0.82, 0.75), neb) * band * (0.3 + 0.7 * neb) * (1.0 - dust * 0.5) * 0.045;
  return col;
}

void main() {
  vec3 dv = normalize(vec3(vNdc.x * uAspect * uTanHalf, vNdc.y * uTanHalf, 1.0));
  vec3 dir = uCamRot * dv;
  vec3 ro = uEye;
  vec3 oc = ro - uCentre;
  float b = dot(oc, dir);
  float cc = dot(oc, oc) - 1.0;
  float h = b * b - cc;
  float sdisc = max(dot(dir, uSunS), 0.0);

  vec3 col = vec3(0.0);
  float hit = 0.0;
  if (h < 0.0) {
    vec3 night = stars(dir) * 0.55;
    // The sun: a disc far brighter than anything, for the bloom to spread.
    night += vec3(1.0, 0.95, 0.85) * (smoothstep(0.999955, 0.999985, sdisc) * 30.0 + pow(sdisc, 3000.0) * 4.0 + pow(sdisc, 200.0) * 0.5);
    // Daylight: no stars read; the sky is the air's own light, brightest at the limb.
    vec3 toC = normalize(uCentre);
    float angR = asin(1.0 / length(uCentre));
    float above = acos(clamp(dot(dir, toC), -1.0, 1.0)) - angR;
    vec3 day = mix(vec3(0.8, 0.9, 1.0) * 1.1, vec3(0.38, 0.5, 0.72) * 0.5, smoothstep(0.0, 0.55, above));
    col = mix(night, day, uTheme);
  }
  // The atmosphere shell, for rays that miss the ground.
  float ha = b * b - (dot(oc, oc) - 1.07 * 1.07);
  if (h < 0.0 && ha > 0.0) {
    float t = -b;
    vec3 cp = ro + dir * t;
    float alt = length(cp - uCentre) - 1.0;
    vec3 n = normalize(cp - uCentre);
    float lit = smoothstep(-0.35, 0.25, dot(n, uSunL));
    float dens = exp(-max(alt, 0.0) / mix(0.02, 0.04, uTheme));
    float path = 2.0 * sqrt(ha);
    // Blue where the air scatters the sun sideways; warm and bright where it comes through toward us.
    float fwd = pow(sdisc, 14.0);
    vec3 rim = mix(vec3(0.25, 0.5, 1.0), vec3(1.0, 0.78, 0.55), fwd * 0.8);
    col += rim * dens * path * (0.08 + 0.9 * lit) * (3.2 + 5.0 * fwd) * (1.0 - 0.2 * uTheme);
    vec3 line = mix(vec3(0.55, 0.75, 1.0), vec3(1.0, 0.85, 0.6), fwd);
    col += line * exp(-max(alt, 0.0) / 0.004) * (0.15 + lit) * (1.4 + 1.2 * fwd) * (1.0 - 0.5 * uTheme);
  }

  if (h >= 0.0) {
    hit = 1.0;
    float t = -b - sqrt(h);
    vec3 p = ro + dir * t;
    vec3 n = normalize(p - uCentre);
    // The planet's frame: tilted toward the camera, turning about its axis.
    float ct = cos(uTilt), st = sin(uTilt);
    vec3 nl = vec3(n.x, n.y * ct - n.z * st, n.y * st + n.z * ct);
    float lat = asin(clamp(nl.y, -1.0, 1.0));
    float lon = atan(nl.x, nl.z) + uRot;
    vec2 uv = vec2(fract(lon / 6.2831853 + 0.5), 0.5 - lat / 3.1415926);
    vec3 dayT = srgb(texture(uDay, uv).rgb);
    float oceanT = texture(uSpec, uv).r;
    // By day the water reads as water: a little bluer and deeper than the map's grey-blue.
    dayT = mix(dayT, dayT * vec3(0.7, 1.0, 1.4) + vec3(0.0, 0.03, 0.08), oceanT * uTheme * 0.8);
    vec3 nightT = srgb(texture(uNight, uv).rgb);
    // Clouds drift a little faster than the ground turns -- real weather, unlike a
    // rotating planet, has no fixed longitude -- at their own slow, independent rate so the
    // deck visibly moves even while uRot sits still between one selected country and the
    // next. Its own uv, not a shift of the ground's: the shadow offset below stays relative
    // to the drifted deck, not the terrain under it.
    vec2 uvClouds = vec2(fract((lon + uTime * 0.012) / 6.2831853 + 0.5), uv.y);
    float cloud = texture(uClouds, uvClouds).r * (1.0 - 0.15 * uTheme);
    float ocean = oceanT;
    float ndl = dot(n, uSunL);
    float day = smoothstep(-0.05, 0.22, ndl);
    float ndv = max(dot(n, -dir), 0.0);
    // The clouds' shadow: the cloud map read a step toward the sun.
    vec3 tang = normalize(uSunL - n * ndl);
    vec3 nl2 = vec3(tang.x, tang.y * ct - tang.z * st, tang.y * st + tang.z * ct);
    vec2 duv = vec2(nl2.x, -nl2.y) * 0.004;
    float shadow = 1.0 - 0.55 * texture(uClouds, uvClouds + duv).r * day;
    vec3 sun = vec3(1.0, 0.96, 0.9);
    vec3 ground = dayT * max(ndl, 0.0) * sun * (1.3 + 0.9 * uTheme) * shadow;
    // The glint on the water.
    vec3 refl = reflect(-uSunL, n);
    float glint = pow(max(dot(refl, -dir), 0.0), 90.0) * ocean * (1.0 - cloud) * 1.6;
    ground += sun * glint * max(ndl, 0.0);
    vec3 cloudCol = vec3(0.95, 0.96, 1.0) * (0.02 + 1.2 * max(ndl, 0.0)) * cloud;
    vec3 c = ground * (1.0 - cloud) + cloudCol;
    // City lights on the night side, softened where cloud covers them.
    c += nightT * vec3(1.0, 0.82, 0.55) * (1.0 - day) * (1.0 - cloud * 0.7) * 7.0;
    c += dayT * 0.006;
    // Air over the ground: bluer toward the limb, only where the sun reaches.
    float fres = pow(1.0 - ndv, 3.0) * (1.0 - 0.6 * uTheme);
    c += mix(vec3(0.3, 0.55, 1.0), vec3(0.2, 0.42, 0.9), uTheme) * fres * (0.05 + 0.7 * day) * 1.3;
    c = mix(c, vec3(0.5, 0.7, 1.0) * (0.3 + 0.7 * day), fres * 0.4 * day);
    // The marker: a warm point and its halo at the site's country.
    if (uMarker.z > 0.001) {
      vec3 m = vec3(cos(uMarker.x) * sin(uMarker.y - uRot), sin(uMarker.x), cos(uMarker.x) * cos(uMarker.y - uRot));
      float ang = acos(clamp(dot(nl, m), -1.0, 1.0));
      float pulse = 0.85 + 0.15 * sin(uTime * 3.0);
      // At night a warm point and its halo; by day a green pin with a dark ring, so it reads on the bright ground.
      c += vec3(1.0, 0.85, 0.6) * (exp(-ang * ang * 6000.0) * 8.0 + exp(-ang * 45.0) * 0.7) * uMarker.z * pulse * (1.0 - uTheme);
      float pin = exp(-ang * ang * 5000.0);
      float ring = smoothstep(0.022, 0.026, ang) * (1.0 - smoothstep(0.032, 0.038, ang));
      float dim = exp(-ang * ang * 600.0) * 0.45;
      c = mix(c * (1.0 - dim * uMarker.z * uTheme), vec3(0.22, 0.7, 0.18) * (0.7 + 0.3 * pulse), (pin + ring * 0.85) * uMarker.z * uTheme);
    }
    col = c;
  }
  fragColor = vec4(col, hit);
}
`;

export const BRIGHT_FRAG = /* glsl */ `#version 300 es
precision highp float;
in vec2 vNdc;
out vec4 fragColor;
uniform sampler2D uColor;
uniform float uThreshold;
void main() {
  vec2 uv = vNdc * 0.5 + 0.5;
  vec3 c = texture(uColor, uv).rgb;
  float l = dot(c, vec3(0.3, 0.59, 0.11));
  fragColor = vec4(c * smoothstep(uThreshold, uThreshold * 2.5, l), 1.0);
}
`;

export const BLUR_FRAG = /* glsl */ `#version 300 es
precision highp float;
in vec2 vNdc;
out vec4 fragColor;
uniform sampler2D uColor;
uniform vec2 uStep;
void main() {
  vec2 uv = vNdc * 0.5 + 0.5;
  float w[5] = float[](0.227027, 0.1945946, 0.1216216, 0.054054, 0.016216);
  vec3 c = texture(uColor, uv).rgb * w[0];
  for (int i = 1; i < 5; i++) {
    c += texture(uColor, uv + uStep * float(i)).rgb * w[i];
    c += texture(uColor, uv - uStep * float(i)).rgb * w[i];
  }
  fragColor = vec4(c, 1.0);
}
`;

export const POST_FRAG = /* glsl */ `#version 300 es
precision highp float;
in vec2 vNdc;
out vec4 fragColor;
uniform sampler2D uColor;
uniform sampler2D uBloom;
uniform vec2 uTexel;
uniform vec2 uSunPx;          // the sun on screen, in ndc
uniform float uSunVis;        // 0..1, how much of the disc is above the limb
uniform float uAspect;
uniform float uExposure, uGrain, uVignette, uTime, uBloomK;
uniform int uFxaa;
float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }
vec3 aces(vec3 x) { return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0); }
float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
void main() {
  vec2 uv = vNdc * 0.5 + 0.5;
  vec4 c = texture(uColor, uv);
  if (uFxaa == 1) {
    vec3 nw = texture(uColor, uv + vec2(-1.0, -1.0) * uTexel).rgb;
    vec3 ne = texture(uColor, uv + vec2(1.0, -1.0) * uTexel).rgb;
    vec3 sw = texture(uColor, uv + vec2(-1.0, 1.0) * uTexel).rgb;
    vec3 se = texture(uColor, uv + vec2(1.0, 1.0) * uTexel).rgb;
    float lNW = luma(nw), lNE = luma(ne), lSW = luma(sw), lSE = luma(se), lM = luma(c.rgb);
    float lMin = min(lM, min(min(lNW, lNE), min(lSW, lSE)));
    float lMax = max(lM, max(max(lNW, lNE), max(lSW, lSE)));
    vec2 dir = vec2(-((lNW + lNE) - (lSW + lSE)), (lNW + lSW) - (lNE + lSE));
    float reduce = max((lNW + lNE + lSW + lSE) * 0.03125, 1.0 / 128.0);
    float rcp = 1.0 / (min(abs(dir.x), abs(dir.y)) + reduce);
    dir = clamp(dir * rcp, vec2(-8.0), vec2(8.0)) * uTexel;
    vec4 a = 0.5 * (texture(uColor, uv + dir * (1.0 / 3.0 - 0.5)) + texture(uColor, uv + dir * (2.0 / 3.0 - 0.5)));
    vec4 b2 = a * 0.5 + 0.25 * (texture(uColor, uv + dir * -0.5) + texture(uColor, uv + dir * 0.5));
    float lB = luma(b2.rgb);
    c = (lB < lMin || lB > lMax) ? a : b2;
  }
  vec3 rgb = c.rgb + texture(uBloom, uv).rgb * uBloomK;
  // The sun's rays: long soft spokes and a horizontal streak, in screen space; the planet
  // (alpha 1 where the ground was hit) stands in front of most of them.
  float occ = 1.0 - c.a * 0.85;
  vec2 d = (vNdc - uSunPx) * vec2(uAspect, 1.0);
  float r = length(d);
  float th = atan(d.y, d.x);
  float spokes = pow(abs(cos(th * 4.0 + 0.3)), 120.0) * 0.5 + pow(abs(cos(th * 7.0 + 1.1)), 220.0) * 0.35 + pow(abs(cos(th * 11.0 + 2.4)), 400.0) * 0.25;
  float rays = spokes * exp(-r * 3.5) * 0.7 + exp(-abs(d.y) * 80.0) * exp(-r * 2.4) * 0.3;
  float core = exp(-r * 70.0) * 7.0 + exp(-r * 24.0) * 0.55;
  float halo = exp(-r * 5.0) * 0.22;
  rgb += (vec3(1.0, 0.92, 0.78) * core + vec3(0.75, 0.85, 1.0) * rays + vec3(1.0, 0.85, 0.65) * halo) * uSunVis * occ;
  rgb = aces(rgb * uExposure);
  rgb = pow(rgb, vec3(1.0 / 2.2));
  float vig = 1.0 - uVignette * smoothstep(0.55, 1.5, length(vNdc * vec2(1.0, 1.15)));
  rgb *= vig;
  rgb += (hash12(gl_FragCoord.xy + fract(uTime) * 61.0) - 0.5) * uGrain;
  fragColor = vec4(rgb, 1.0);
}
`;
