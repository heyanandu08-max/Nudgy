import { describe, expect, it } from "vitest";
import { arcControl, easeInOutCubic, follow, quadPoint } from "./motion";

describe("motion", () => {
  it("bezier starts and ends at the endpoints", () => {
    const a = { x: 10, y: 500 };
    const b = { x: 800, y: 60 };
    const c = arcControl(a, b);
    expect(quadPoint(a, c, b, 0)).toEqual(a);
    const end = quadPoint(a, c, b, 1);
    expect(end.x).toBeCloseTo(b.x);
    expect(end.y).toBeCloseTo(b.y);
  });

  it("arc always bows upwards", () => {
    for (const [a, b] of [
      [{ x: 0, y: 0 }, { x: 100, y: 0 }],
      [{ x: 100, y: 0 }, { x: 0, y: 0 }],
      [{ x: 0, y: 100 }, { x: 100, y: 300 }],
    ]) {
      const c = arcControl(a, b);
      expect(c.y).toBeLessThanOrEqual((a.y + b.y) / 2);
    }
  });

  it("easing is monotonic from 0 to 1", () => {
    expect(easeInOutCubic(0)).toBe(0);
    expect(easeInOutCubic(1)).toBe(1);
    let prev = 0;
    for (let t = 0.05; t <= 1; t += 0.05) {
      const v = easeInOutCubic(t);
      expect(v).toBeGreaterThanOrEqual(prev);
      prev = v;
    }
  });

  it("follow converges and is frame-rate independent", () => {
    const target = { x: 100, y: 100 };
    let a = { x: 0, y: 0 };
    for (let i = 0; i < 4; i++) a = follow(a, target, 16);
    const b = follow({ x: 0, y: 0 }, target, 64);
    expect(a.x).toBeCloseTo(b.x, 5);
  });
});
