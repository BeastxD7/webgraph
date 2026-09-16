export type FieldPreset = "hero" | "result";

export type MountOptions = {
  frame: HTMLElement;
  back: HTMLCanvasElement;
  front?: HTMLCanvasElement;
  preset: FieldPreset;
};

/** Placeholder until the renderer lands: leaves the still in place. */
export function mountField(_options: MountOptions): () => void {
  return () => {};
}
