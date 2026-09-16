import { useSyncExternalStore } from "react";

import type { EvidenceItem, HopEdge, QueryEvent } from "@/lib/kg";

/**
 * What a query has lit up so far, kept outside React.
 *
 * The ask stream can deliver a hop with a hundred edges a few milliseconds after the seeds,
 * and sigma redraws on its own clock; routing every frame through React state would re-render
 * the whole page per event for nothing. The store is written by the stream handler and read
 * by sigma's reducers on the next refresh, and the React parts that *do* need it (the list
 * view, the legend's "lit" counts) subscribe through `usePath`.
 */

export type NodeRole = "seed" | "reached" | "evidence" | "answer";

export interface Particle {
  edge: string;
  source: string;
  target: string;
  /** performance.now() when it was fired; the tween runs ~350 ms. */
  start: number;
  hop: number;
}

export interface PathState {
  /** True while a question is in flight or answered: everything not on the path dims. */
  active: boolean;
  nodes: Map<string, NodeRole>;
  /** relation id -> hop number the edge was crossed on. */
  edges: Map<string, number>;
  /** Node ids named by the evidence that was chosen for the answer. */
  evidence: Set<string>;
  particles: Particle[];
  /** Nodes to bring the camera to when the answer lands. */
  focus: string[];
  version: number;
}

function blank(): PathState {
  return { active: false, nodes: new Map(), edges: new Map(), evidence: new Set(), particles: [], focus: [], version: 0 };
}

let state: PathState = blank();
const listeners = new Set<(state: PathState) => void>();

function emit(): void {
  state = { ...state, version: state.version + 1 };
  for (const listener of listeners) listener(state);
}

export const pathStore = {
  get: (): PathState => state,

  subscribe(listener: (state: PathState) => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },

  reset(): void {
    state = blank();
    emit();
  },

  begin(): void {
    state = { ...blank(), active: true };
    emit();
  },

  seeds(ids: string[]): void {
    for (const id of ids) state.nodes.set(id, "seed");
    emit();
  },

  hop(hop: number, edges: HopEdge[]): void {
    const now = performance.now();
    for (const edge of edges) {
      if (!state.nodes.has(edge.to_id)) state.nodes.set(edge.to_id, "reached");
      if (!state.edges.has(edge.relation_id)) state.edges.set(edge.relation_id, hop);
      state.particles.push({ edge: edge.relation_id, source: edge.from_id, target: edge.to_id, start: now, hop });
    }
    emit();
  },

  evidence(items: EvidenceItem[]): void {
    for (const item of items) {
      for (const id of item.entity_ids) {
        state.evidence.add(id);
        if (state.nodes.get(id) !== "seed") state.nodes.set(id, "evidence");
      }
    }
    emit();
  },

  answer(ids: string[]): void {
    for (const id of ids) state.nodes.set(id, "answer");
    state.focus = ids.length ? ids : [...state.nodes.keys()].slice(0, 12);
    emit();
  },

  /** Drop particles older than `ttl` ms; returns whether any remain (keep animating). */
  prune(ttl: number): boolean {
    const now = performance.now();
    const before = state.particles.length;
    state.particles = state.particles.filter((p) => now - p.start < ttl);
    return before > 0 && state.particles.length > 0;
  },

  /** Apply one query event; the panel calls this and nothing else. */
  apply(event: QueryEvent): void {
    switch (event.type) {
      case "seeds":
        pathStore.seeds(event.entities.map((e) => e.id));
        break;
      case "hop":
        pathStore.hop(event.hop, event.edges);
        break;
      case "evidence":
        pathStore.evidence(event.items);
        break;
      case "answer":
        pathStore.answer(event.path.answer_nodes);
        break;
      default:
        break;
    }
  },
};

export function usePath(): PathState {
  return useSyncExternalStore(
    (onChange) => pathStore.subscribe(() => onChange()),
    pathStore.get,
    pathStore.get,
  );
}
