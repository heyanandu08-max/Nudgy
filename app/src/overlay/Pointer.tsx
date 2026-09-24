import { useEffect, useRef, useState } from "react";
import type { CursorColor, CursorSize } from "../lib/settings";
import { arcControl, easeInOutCubic, quadPoint, type Vec } from "../lib/motion";
import { NudgyCursor } from "./NudgyCursor";
import type { PointTarget } from "./store";

const FLIGHT_MS = 520;
const LINGER_MS = 6000;

/**
 * The Nudgy cursor flies from where it was to the target on a gentle arc, leaving a dashed
 * trail, then a black ring outlines the target's real box.
 */
export function Pointer({ target, from, color, size, onDone }: { target: PointTarget; from: Vec; color: CursorColor; size: CursorSize; onDone: () => void }) {
  const cursor = useRef<HTMLDivElement>(null);
  const [arrived, setArrived] = useState(false);
  const fromRef = useRef(from);
  const r = target.rect;
  const to = { x: r.x + r.w / 2, y: r.y + r.h / 2 };

  useEffect(() => {
    setArrived(false);
    const a = fromRef.current;
    const c = arcControl(a, to, 0.18);
    const start = performance.now();
    let raf = 0;
    let linger: ReturnType<typeof setTimeout> | undefined;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / FLIGHT_MS);
      const p = quadPoint(a, c, to, easeInOutCubic(t));
      if (cursor.current) cursor.current.style.transform = `translate(${p.x}px, ${p.y}px)`;
      if (t < 1) raf = requestAnimationFrame(tick);
      else {
        setArrived(true);
        linger = setTimeout(onDone, LINGER_MS);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      if (linger) clearTimeout(linger);
    };
    // Re-run only for a new request.
  }, [target.seq]);

  const a = fromRef.current;
  const pad = 6;
  return (
    <>
      <svg className="trail" aria-hidden>
        <line x1={a.x} y1={a.y} x2={to.x} y2={to.y} />
      </svg>
      {target.highlight && arrived && (
        <div className="ring" style={{ left: r.x - pad, top: r.y - pad, width: r.w + pad * 2, height: r.h + pad * 2 }} aria-hidden />
      )}
      <div ref={cursor} className={`flying ${arrived ? "flying--arrived" : ""}`} aria-hidden>
        <NudgyCursor color={color} size={size} />
      </div>
    </>
  );
}
