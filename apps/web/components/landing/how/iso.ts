/**
 * Isometric (30°) projection for the "how it reads a page" scene, in SVG user units.
 *
 * World axes: +x runs right-and-down the screen, +y left-and-down (both toward the viewer),
 * +z straight up. A group given `wall(...)` draws in a sheet standing in the x–z plane with
 * local u along +x and v downward, so page content is authored in plain 2-D coordinates;
 * `floor(...)` does the same for the ground plane (u along +x, v along +y). Everything is
 * rendered on the server; nothing here runs in the browser.
 */
export const CX = 0.866; // cos 30°
export const SY = 0.5; // sin 30°

/** Where the world origin sits in the SVG viewBox. */
export const ORIGIN = { x: 330, y: 352 } as const;

export type Pt = readonly [number, number];

export function pt(x: number, y: number, z = 0): Pt {
  return [ORIGIN.x + CX * (x - y), ORIGIN.y + SY * (x + y) - z];
}

const f = (n: number) => n.toFixed(2).replace(/\.?0+$/, "");

/** A sheet standing in the x–z plane; its top-left corner at world (x, y, top). */
export function wall(x: number, y: number, top: number): string {
  const [e, g] = pt(x, y, top);
  return `matrix(${CX} ${SY} 0 1 ${f(e)} ${f(g)})`;
}

/** The ground plane; its local origin at world (x, y, 0). */
export function floor(x: number, y: number): string {
  const [e, g] = pt(x, y, 0);
  return `matrix(${CX} ${SY} ${-CX} ${SY} ${f(e)} ${f(g)})`;
}

/** An SVG points string from local coordinates. */
export function poly(...pts: Pt[]): string {
  return pts.map(([x, y]) => `${f(x)},${f(y)}`).join(" ");
}
