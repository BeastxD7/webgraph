/**
 * What the still and the live Earth share: the camera and where the planet sits.
 *
 * The planet has radius 1. The camera looks down +z from `distance` away, with the planet's
 * centre `drop` radians below the line of sight, so the limb curves across the lower third
 * and the sun, drawn just above it, rises from behind. `tilt` leans the axis toward the
 * camera so the northern hemisphere and its city lights face us.
 */
export const CAM = { fovDeg: 38, distance: 2.7, drop: (27 * Math.PI) / 180, near: 0.05, far: 40 } as const;
export const EARTH = {
  /** The axis leans away from the camera at rest: the far north at the limb, the temperate belt across the disc. */
  tilt: (-30 * Math.PI) / 180,
  /** One turn in this many seconds when nothing is asked of it. */
  turnSeconds: 300,
  /** Where the sun disc is drawn, as azimuth and elevation from the line of sight, radians:
   *  just behind the limb, so it rises from it, half hidden. */
  sunAz: (18 * Math.PI) / 180,
  sunEl: (-5.7 * Math.PI) / 180,
  /** Where the light comes from, so the crescent under the sun is lit. */
  light: [0.78, 0.32, 0.28] as const,
  /** The day scene (the light theme): the sun high behind the viewer, to the right. */
  dayLight: [0.5, 0.55, -0.68] as const,
} as const;

/** The planet's centre for a camera at the origin looking down +z. */
export function planetCentre(distance: number = CAM.distance): [number, number, number] {
  return [0, -Math.sin(CAM.drop) * distance, Math.cos(CAM.drop) * distance];
}
