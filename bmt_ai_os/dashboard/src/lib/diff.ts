export interface DiffLine {
  type: "same" | "add" | "remove";
  content: string;
  oldLineNo?: number;
  newLineNo?: number;
}

export interface DiffStats {
  added: number;
  removed: number;
}

/**
 * Compute a unified diff between two strings using Myers' diff algorithm.
 * Returns an array of DiffLine objects with type, content, and line numbers.
 * Pure implementation — no external dependencies.
 */
export function computeDiff(original: string, modified: string): DiffLine[] {
  const aLines = original === "" ? [] : original.split("\n");
  const bLines = modified === "" ? [] : modified.split("\n");

  const n = aLines.length;
  const m = bLines.length;

  // Myers diff: find the shortest edit script
  // v[k] = furthest x reached on diagonal k
  const maxD = n + m;
  const v: number[] = new Array(2 * maxD + 1).fill(0);
  // trace[d] = snapshot of v after processing depth d
  const trace: number[][] = [];

  outer: for (let d = 0; d <= maxD; d++) {
    trace.push(v.slice());
    for (let k = -d; k <= d; k += 2) {
      const ki = k + maxD; // offset index into v
      let x: number;
      if (k === -d || (k !== d && v[ki - 1] < v[ki + 1])) {
        x = v[ki + 1]; // move down (insert from b)
      } else {
        x = v[ki - 1] + 1; // move right (delete from a)
      }
      let y = x - k;
      // follow diagonal (equal elements)
      while (x < n && y < m && aLines[x] === bLines[y]) {
        x++;
        y++;
      }
      v[ki] = x;
      if (x >= n && y >= m) break outer;
    }
  }

  // Backtrack through trace to recover the edit path
  type Move = { x: number; y: number; px: number; py: number };
  const path: Move[] = [];
  let x = n;
  let y = m;

  for (let d = trace.length - 1; d >= 1; d--) {
    const vd = trace[d];
    const k = x - y;
    const ki = k + maxD;

    let pk: number;
    if (k === -d || (k !== d && vd[ki - 1] < vd[ki + 1])) {
      pk = k + 1; // came from down
    } else {
      pk = k - 1; // came from right
    }

    const px = vd[pk + maxD];
    const py = px - pk;

    // walk back along the diagonal (equal lines)
    while (x > px && y > py) {
      path.push({ x, y, px: x - 1, py: y - 1 });
      x--;
      y--;
    }
    path.push({ x, y, px, py });
    x = px;
    y = py;
  }
  // walk remaining diagonal at d=0
  while (x > 0 && y > 0) {
    path.push({ x, y, px: x - 1, py: y - 1 });
    x--;
    y--;
  }

  path.reverse();

  // Convert edit path into DiffLine[]
  const result: DiffLine[] = [];
  let oldNo = 1;
  let newNo = 1;
  let cx = 0; // current position in a
  let cy = 0; // current position in b

  for (const move of path) {
    // diagonal (equal) segment before this move
    while (cx < move.px && cy < move.py) {
      result.push({
        type: "same",
        content: aLines[cx],
        oldLineNo: oldNo++,
        newLineNo: newNo++,
      });
      cx++;
      cy++;
    }

    // the move itself
    const dx = move.x - move.px;
    const dy = move.y - move.py;

    if (dx === 1 && dy === 0) {
      // delete from a
      result.push({
        type: "remove",
        content: aLines[cx],
        oldLineNo: oldNo++,
      });
      cx++;
    } else if (dx === 0 && dy === 1) {
      // insert from b
      result.push({
        type: "add",
        content: bLines[cy],
        newLineNo: newNo++,
      });
      cy++;
    }
  }

  // remaining equal lines
  while (cx < n) {
    result.push({
      type: "same",
      content: aLines[cx],
      oldLineNo: oldNo++,
      newLineNo: newNo++,
    });
    cx++;
    cy++;
  }

  return result;
}

export function diffStats(lines: DiffLine[]): DiffStats {
  let added = 0;
  let removed = 0;
  for (const l of lines) {
    if (l.type === "add") added++;
    else if (l.type === "remove") removed++;
  }
  return { added, removed };
}
