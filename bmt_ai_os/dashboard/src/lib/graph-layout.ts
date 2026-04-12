// ---------------------------------------------------------------------------
// Force-directed graph layout
// Mutates node x/y in place.  No external dependencies.
// ---------------------------------------------------------------------------

export interface LayoutNode {
  id: string;
  x: number;
  y: number;
}

export interface LayoutEdge {
  source: string;
  target: string;
}

/**
 * Place nodes in an initial circle so the layout starts with no overlap.
 */
function initCircle(nodes: LayoutNode[], radius = 200): void {
  const count = nodes.length;
  if (count === 0) return;
  if (count === 1) {
    nodes[0].x = 0;
    nodes[0].y = 0;
    return;
  }
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / count;
    n.x = radius * Math.cos(angle);
    n.y = radius * Math.sin(angle);
  });
}

/**
 * Run a force-directed layout.
 *
 * Forces applied each iteration:
 *  - Repulsion: inverse-square law between all node pairs
 *  - Attraction: spring force along each edge (pulls endpoints together)
 *  - Centering: weak pull toward origin
 *
 * @param nodes   Array of nodes — x/y are mutated in place.
 * @param edges   Adjacency list.
 * @param iterations  Number of simulation steps (default 150).
 * @param width   Canvas width used to set initial spread (default 800).
 * @param height  Canvas height (default 600).
 */
export function forceLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  iterations = 150,
  width = 800,
  height = 600,
): void {
  if (nodes.length === 0) return;

  // Place nodes in a circle scaled to the canvas
  const initRadius = Math.min(width, height) * 0.35;
  initCircle(nodes, initRadius);

  // Build adjacency set for fast lookup
  const adjacent = new Set<string>();
  for (const e of edges) {
    adjacent.add(`${e.source}:${e.target}`);
    adjacent.add(`${e.target}:${e.source}`);
  }

  // Tuning constants
  const repulsion = 4000;
  const springLength = 120;
  const springK = 0.05;
  const centeringK = 0.005;
  const damping = 0.85;
  const maxDisplace = 30;

  // Velocity vectors (start at rest)
  const vx = new Float64Array(nodes.length);
  const vy = new Float64Array(nodes.length);

  for (let iter = 0; iter < iterations; iter++) {
    const fx = new Float64Array(nodes.length);
    const fy = new Float64Array(nodes.length);

    // --- Repulsion (all pairs) ---
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const distSq = dx * dx + dy * dy + 0.01; // avoid div-by-zero
        const force = repulsion / distSq;
        const dist = Math.sqrt(distSq);
        const nx = dx / dist;
        const ny = dy / dist;
        fx[i] += force * nx;
        fy[i] += force * ny;
        fx[j] -= force * nx;
        fy[j] -= force * ny;
      }
    }

    // --- Attraction along edges ---
    for (const edge of edges) {
      const si = nodes.findIndex((n) => n.id === edge.source);
      const ti = nodes.findIndex((n) => n.id === edge.target);
      if (si === -1 || ti === -1) continue;
      const dx = nodes[ti].x - nodes[si].x;
      const dy = nodes[ti].y - nodes[si].y;
      const dist = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const displacement = dist - springLength;
      const force = springK * displacement;
      fx[si] += force * (dx / dist);
      fy[si] += force * (dy / dist);
      fx[ti] -= force * (dx / dist);
      fy[ti] -= force * (dy / dist);
    }

    // --- Centering ---
    for (let i = 0; i < nodes.length; i++) {
      fx[i] -= centeringK * nodes[i].x;
      fy[i] -= centeringK * nodes[i].y;
    }

    // --- Integrate with damping ---
    for (let i = 0; i < nodes.length; i++) {
      vx[i] = (vx[i] + fx[i]) * damping;
      vy[i] = (vy[i] + fy[i]) * damping;

      // Clamp displacement per step
      const speed = Math.sqrt(vx[i] * vx[i] + vy[i] * vy[i]);
      if (speed > maxDisplace) {
        vx[i] *= maxDisplace / speed;
        vy[i] *= maxDisplace / speed;
      }

      nodes[i].x += vx[i];
      nodes[i].y += vy[i];
    }
  }

  // --- Translate so centroid is at (width/2, height/2) ---
  let cx = 0;
  let cy = 0;
  for (const n of nodes) {
    cx += n.x;
    cy += n.y;
  }
  cx /= nodes.length;
  cy /= nodes.length;
  for (const n of nodes) {
    n.x += width / 2 - cx;
    n.y += height / 2 - cy;
  }
}
