export interface Vec {
  x: number;
  y: number;
}

export const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

/**
 * Control point for a quadratic Bézier "flight" from `a` to `b`: the midpoint lifted
 * perpendicular to the path (always bowing upwards on screen) by 30% of the distance.
 */
export function arcControl(a: Vec, b: Vec, bow = 0.3): Vec {
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy);
  if (len === 0) return { x: mx, y: my };
  let nx = -dy / len;
  let ny = dx / len;
  if (ny > 0) {
    nx = -nx;
    ny = -ny;
  }
  return { x: mx + nx * len * bow, y: my + ny * len * bow };
}

export function quadPoint(a: Vec, c: Vec, b: Vec, t: number): Vec {
  const u = 1 - t;
  return { x: u * u * a.x + 2 * u * t * c.x + t * t * b.x, y: u * u * a.y + 2 * u * t * c.y + t * t * b.y };
}

/** Tangent angle (radians) of the quadratic curve at `t`. */
export function quadAngle(a: Vec, c: Vec, b: Vec, t: number): number {
  const dx = 2 * (1 - t) * (c.x - a.x) + 2 * t * (b.x - c.x);
  const dy = 2 * (1 - t) * (c.y - a.y) + 2 * t * (b.y - c.y);
  return Math.atan2(dy, dx);
}

/** Frame-rate independent exponential smoothing toward a target. */
export function follow(current: Vec, target: Vec, dtMs: number, halfLifeMs = 70): Vec {
  const k = 1 - 2 ** (-dtMs / halfLifeMs);
  return { x: current.x + (target.x - current.x) * k, y: current.y + (target.y - current.y) * k };
}
