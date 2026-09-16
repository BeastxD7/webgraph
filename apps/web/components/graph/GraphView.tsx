"use client";

import { SigmaContainer, useLoadGraph, useRegisterEvents, useSetSettings, useSigma } from "@react-sigma/core";
import { MultiDirectedGraph } from "graphology";
import { inferSettings } from "graphology-layout-forceatlas2";
import FA2Layout from "graphology-layout-forceatlas2/worker";
import { useEffect, useMemo, useRef } from "react";
import { drawDiscNodeLabel } from "sigma/rendering";
import type { Settings } from "sigma/settings";
import type { EdgeDisplayData, NodeDisplayData } from "sigma/types";

import { type KGGraph, typeColor } from "@/lib/kg";

import { type NodeRole, pathStore } from "./pathStore";

import "@react-sigma/core/lib/style.css";

/**
 * The graph, drawn by sigma (WebGL) and laid out by ForceAtlas2 in a worker.
 *
 * Node colour is the entity's type, node size its evidence count, so the biggest things on
 * screen are the ones the site says most about. When a question runs, the path lights in
 * real time: seeds turn amber as the seed event lands, each hop's edges brighten and carry a
 * particle from source to target (overlay canvas, ~350 ms), evidence nodes pulse, and the
 * answer's nodes go green while the camera moves to them. Everything off the path dims to
 * a ghost so the path reads even on a 1,500-node graph. Reducers read `pathStore` on each
 * refresh; no React render sits between a stream event and a frame.
 *
 * Loaded with `dynamic(..., { ssr: false })` by `GraphViewLoader`: sigma touches `window`
 * and WebGL at import, which the server has neither of.
 */

const PARTICLE_MS = 350;
const PARTICLE_TTL = 700;

interface Palette {
  ink: string;
  faint: string;
  ghostNode: string;
  ghostEdge: string;
  edge: string;
  seed: string;
  hop: string;
  evidence: string;
  answer: string;
  labelBg: string;
  rule: string;
}

function readPalette(dark: boolean): Palette {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  return {
    ink: v("--ink", dark ? "#e7ebe6" : "#0f1a14"),
    faint: v("--faint", dark ? "#7c877f" : "#6b7a70"),
    // Opaque, not rgba: the WebGL node program ignores alpha, so a translucent ghost paints
    // as solid white on the dark ground. These are the ground mixed toward the ink.
    ghostNode: dark ? "#2a332e" : "#dde1da",
    ghostEdge: dark ? "#1d2521" : "#e9ebe6",
    edge: dark ? "#3d4741" : "#c3c9c0",
    seed: v("--warn", dark ? "#e0b04a" : "#8a5a0b"),
    hop: dark ? "#3987e5" : "#2a78d6",
    evidence: dark ? "#9085e9" : "#4a3aa7",
    answer: v("--accent", dark ? "#7fc063" : "#3f8527"),
    labelBg: v("--surface", dark ? "#151b17" : "#ffffff"),
    rule: v("--rule-strong", dark ? "rgba(231,235,230,0.22)" : "rgba(15,26,20,0.24)"),
  };
}

/**
 * Sigma's stock hover box is white with a black shadow, which is a hole in the dark theme.
 * Same geometry as `drawDiscNodeHover`, painted with the page's own surface and rule.
 */
function hoverDrawer(palette: Palette): Settings["defaultDrawNodeHover"] {
  return (context, data, settings) => {
    const size = settings.labelSize;
    context.font = `${settings.labelWeight} ${size}px ${settings.labelFont}`;
    context.fillStyle = palette.labelBg;
    context.strokeStyle = palette.rule;
    context.lineWidth = 1;
    const PADDING = 3;
    if (typeof data.label === "string") {
      const textWidth = context.measureText(data.label).width;
      const boxWidth = Math.round(textWidth + 6);
      const boxHeight = Math.round(size + 2 * PADDING);
      const radius = Math.max(data.size, size / 2) + PADDING;
      const angle = Math.asin(boxHeight / 2 / radius);
      const dx = Math.sqrt(Math.abs(radius ** 2 - (boxHeight / 2) ** 2));
      context.beginPath();
      context.moveTo(data.x + dx, data.y + boxHeight / 2);
      context.lineTo(data.x + radius + boxWidth, data.y + boxHeight / 2);
      context.lineTo(data.x + radius + boxWidth, data.y - boxHeight / 2);
      context.lineTo(data.x + dx, data.y - boxHeight / 2);
      context.arc(data.x, data.y, radius, angle, -angle);
      context.closePath();
      context.fill();
      context.stroke();
    } else {
      context.beginPath();
      context.arc(data.x, data.y, data.size + PADDING, 0, Math.PI * 2);
      context.closePath();
      context.fill();
      context.stroke();
    }
    drawDiscNodeLabel(context, data, settings);
  };
}

function nodeSize(evidence: number): number {
  return Math.min(16, 3 + Math.sqrt(Math.max(1, evidence)) * 2);
}

function buildGraph(data: KGGraph, dark: boolean): MultiDirectedGraph {
  const graph = new MultiDirectedGraph();
  const n = data.nodes.length || 1;
  const spread = 40 + Math.sqrt(n) * 12;
  data.nodes.forEach((node, index) => {
    // Deterministic pseudo-random start (golden-angle spiral): the same graph lays out the
    // same way on every load, and no two nodes begin on top of each other.
    const angle = index * 2.399963;
    const radius = spread * Math.sqrt((index + 0.5) / n);
    graph.addNode(node.id, {
      label: node.name,
      kgType: node.type,
      evidence: node.evidence,
      generic: node.generic,
      size: nodeSize(node.evidence),
      color: typeColor(node.type, dark),
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    });
  });
  for (const edge of data.edges) {
    if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
    graph.addEdgeWithKey(edge.id, edge.source, edge.target, {
      label: edge.predicate,
      size: Math.min(4, 0.6 + Math.log2(1 + edge.weight)),
      weight: edge.weight,
    });
  }
  return graph;
}

/** Loads the graph, runs the layout for a bounded time, and recolours on theme change. */
function Loader({ data, dark }: { data: KGGraph; dark: boolean }) {
  const loadGraph = useLoadGraph();
  const sigma = useSigma();

  useEffect(() => {
    const graph = buildGraph(data, dark);
    loadGraph(graph);
    const inferred = inferSettings(graph);
    const large = graph.order > 300;
    const layout = new FA2Layout(graph, {
      settings: {
        ...inferred,
        gravity: 0.6,
        scalingRatio: Math.max(10, inferred.scalingRatio ?? 10),
        // Size-aware repulsion reads well on a small graph and packs a large one into a disc
        // before the budget runs out; the inferred slowDown (~log n) is too cautious for a
        // layout that has a few seconds, not a few minutes.
        adjustSizes: !large,
        slowDown: large ? 2 : 5,
        edgeWeightInfluence: 0.5,
      },
    });
    layout.start();
    // A few seconds of layout is enough to read; it settles visually and the worker stops
    // spending a core on a graph nobody is dragging.
    const budget = Math.min(8000, 1500 + graph.order * 4);
    const stop = window.setTimeout(() => layout.stop(), budget);
    return () => {
      window.clearTimeout(stop);
      layout.kill();
    };
    // Recolouring is handled below, so a theme flip does not restart the layout.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, loadGraph]);

  useEffect(() => {
    const graph = sigma.getGraph();
    graph.forEachNode((node, attributes) => {
      graph.setNodeAttribute(node, "color", typeColor(String(attributes.kgType), dark));
    });
    sigma.refresh({ skipIndexation: true });
  }, [dark, sigma]);

  return null;
}

/** Reducers, path subscription, the particle overlay and the camera moves. */
function PathLayer({
  dark,
  onSelect,
  selected,
  overlay,
}: {
  dark: boolean;
  onSelect: (id: string | null) => void;
  selected: string | null;
  overlay: React.RefObject<HTMLCanvasElement | null>;
}) {
  const sigma = useSigma();
  const setSettings = useSetSettings();
  const registerEvents = useRegisterEvents();
  const hovered = useRef<string | null>(null);
  const selectedRef = useRef<string | null>(null);
  const palette = useMemo(() => readPalette(dark), [dark]);
  const paletteRef = useRef<Palette | null>(null);

  useEffect(() => {
    registerEvents({
      clickNode: ({ node }) => onSelect(node),
      clickStage: () => onSelect(null),
      enterNode: ({ node }) => {
        hovered.current = node;
        sigma.refresh({ skipIndexation: true });
      },
      leaveNode: () => {
        hovered.current = null;
        sigma.refresh({ skipIndexation: true });
      },
    });
  }, [registerEvents, onSelect, sigma]);

  useEffect(() => {
    paletteRef.current = palette;
    const graph = sigma.getGraph();
    const roleColor: Record<NodeRole, string> = {
      seed: palette.seed,
      reached: palette.hop,
      evidence: palette.evidence,
      answer: palette.answer,
    };
    const nodeReducer: Settings["nodeReducer"] = (node, data) => {
      const state = pathStore.get();
      const out: Partial<NodeDisplayData> = { ...data };
      const role = state.nodes.get(node);
      const focus = hovered.current ?? selectedRef.current;
      if (focus) {
        if (node === focus) {
          out.highlighted = true;
          out.zIndex = 3;
          out.forceLabel = true;
        } else if (graph.areNeighbors(node, focus)) {
          out.zIndex = 2;
          out.forceLabel = true;
        } else if (!role) {
          out.color = palette.ghostNode;
          out.label = null;
        }
      }
      if (state.active) {
        if (role) {
          out.color = roleColor[role];
          out.zIndex = role === "answer" ? 4 : 2;
          out.forceLabel = role !== "reached";
          const bump = role === "answer" ? 1.5 : role === "seed" ? 1.3 : 1.1;
          out.size = (data.size as number) * bump * (state.evidence.has(node) ? 1.15 : 1);
        } else if (node !== focus) {
          out.color = palette.ghostNode;
          out.label = null;
        }
      }
      return out;
    };
    const edgeReducer: Settings["edgeReducer"] = (edge, data) => {
      const state = pathStore.get();
      const out: Partial<EdgeDisplayData> = { ...data, color: palette.edge };
      const hop = state.edges.get(edge);
      const focus = hovered.current ?? selectedRef.current;
      if (focus) {
        if (graph.hasExtremity(edge, focus)) {
          out.color = palette.ink;
          out.zIndex = 2;
          out.size = (data.size as number) * 1.4;
          out.forceLabel = true;
        } else if (hop === undefined) {
          out.color = palette.ghostEdge;
          out.hidden = state.active;
        }
      }
      if (state.active) {
        if (hop !== undefined) {
          out.color = hop === 1 ? palette.hop : palette.evidence;
          out.size = (data.size as number) * 1.6;
          out.zIndex = 3;
          out.hidden = false;
        } else if (!focus || !graph.hasExtremity(edge, focus)) {
          out.color = palette.ghostEdge;
        }
      }
      return out;
    };
    setSettings({
      nodeReducer,
      edgeReducer,
      defaultDrawNodeHover: hoverDrawer(palette),
      labelColor: { color: palette.ink },
      edgeLabelColor: { color: palette.faint },
      defaultEdgeColor: palette.edge,
      labelFont: "Manrope, ui-sans-serif, system-ui, sans-serif",
      labelSize: 12,
      labelWeight: "600",
      labelRenderedSizeThreshold: 9,
      labelDensity: 0.08,
      renderEdgeLabels: true,
      edgeLabelSize: 10,
      edgeLabelFont: "JetBrains Mono, ui-monospace, monospace",
      zIndex: true,
      minEdgeThickness: 0.8,
      hideEdgesOnMove: graph.size > 1500,
    });
    sigma.refresh({ skipIndexation: true });
  }, [palette, setSettings, sigma]);

  // Path store -> frames. A refresh per event is cheap with skipIndexation; the camera moves
  // once, when the answer lands.
  useEffect(() => {
    let raf = 0;
    const canvas = overlay.current;
    const ctx = canvas?.getContext("2d") ?? null;

    const drawParticles = () => {
      if (!canvas || !ctx) return;
      const { width, height } = sigma.getDimensions();
      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      const graph = sigma.getGraph();
      const now = performance.now();
      const pal = paletteRef.current ?? readPalette(false);
      for (const particle of pathStore.get().particles) {
        if (!graph.hasNode(particle.source) || !graph.hasNode(particle.target)) continue;
        const a = sigma.graphToViewport(graph.getNodeAttributes(particle.source) as { x: number; y: number });
        const b = sigma.graphToViewport(graph.getNodeAttributes(particle.target) as { x: number; y: number });
        const t = Math.min(1, (now - particle.start) / PARTICLE_MS);
        const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        const x = a.x + (b.x - a.x) * ease;
        const y = a.y + (b.y - a.y) * ease;
        const fade = t < 1 ? 1 : Math.max(0, 1 - (now - particle.start - PARTICLE_MS) / (PARTICLE_TTL - PARTICLE_MS));
        const color = particle.hop === 1 ? pal.hop : pal.evidence;
        ctx.globalAlpha = 0.85 * fade;
        ctx.shadowColor = color;
        ctx.shadowBlur = 12;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.fill();
        // A short trail behind the head.
        ctx.globalAlpha = 0.35 * fade;
        ctx.lineWidth = 2;
        ctx.strokeStyle = color;
        ctx.beginPath();
        const tail = Math.max(0, ease - 0.18);
        ctx.moveTo(a.x + (b.x - a.x) * tail, a.y + (b.y - a.y) * tail);
        ctx.lineTo(x, y);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      ctx.shadowBlur = 0;
    };

    const tick = () => {
      drawParticles();
      if (pathStore.prune(PARTICLE_TTL)) raf = window.requestAnimationFrame(tick);
      else {
        raf = 0;
        drawParticles(); // clears
      }
    };

    const unsubscribe = pathStore.subscribe((state) => {
      sigma.refresh({ skipIndexation: true });
      if (state.particles.length && !raf) raf = window.requestAnimationFrame(tick);
      if (!state.active && ctx && canvas) ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (state.focus.length) {
        // Frame the answer: the mean of its nodes in framed-graph space, a little closer.
        let sx = 0;
        let sy = 0;
        let count = 0;
        for (const id of state.focus) {
          const display = sigma.getNodeDisplayData(id);
          if (!display) continue;
          sx += display.x;
          sy += display.y;
          count += 1;
        }
        if (count) {
          // Pan to the answer; only zoom in when the reader had zoomed out past the whole graph.
          const camera = sigma.getCamera();
          void camera.animate({ x: sx / count, y: sy / count, ratio: Math.min(camera.ratio, 1) }, { duration: 600 });
        }
      }
    });
    // Keep the overlay aligned while the camera moves or the layout runs.
    const onRender = () => {
      if (pathStore.get().particles.length && !raf) raf = window.requestAnimationFrame(tick);
    };
    sigma.on("afterRender", onRender);
    return () => {
      unsubscribe();
      sigma.off("afterRender", onRender);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, [sigma, overlay]);

  useEffect(() => {
    selectedRef.current = selected;
    sigma.refresh({ skipIndexation: true });
  }, [selected, sigma]);

  return null;
}

export default function GraphView({
  data,
  dark,
  selected,
  onSelect,
  className = "",
}: {
  data: KGGraph;
  dark: boolean;
  selected: string | null;
  onSelect: (id: string | null) => void;
  className?: string;
}) {
  const overlay = useRef<HTMLCanvasElement | null>(null);
  const settings = useMemo<Partial<Settings>>(
    () => ({
      allowInvalidContainer: true,
      defaultEdgeType: "arrow",
      renderEdgeLabels: true,
      labelRenderedSizeThreshold: 9,
      zIndex: true,
    }),
    [],
  );

  return (
    <div className={`relative ${className}`}>
      <SigmaContainer
        style={{ width: "100%", height: "100%", background: "transparent" }}
        settings={settings}
        className="!bg-transparent"
      >
        <Loader data={data} dark={dark} />
        <PathLayer dark={dark} onSelect={onSelect} selected={selected} overlay={overlay} />
      </SigmaContainer>
      <canvas ref={overlay} aria-hidden className="pointer-events-none absolute inset-0" />
    </div>
  );
}
