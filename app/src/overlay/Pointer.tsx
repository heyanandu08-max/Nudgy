import { useEffect, useRef, useState } from "react";
import { arcControl, easeInOutCubic, quadAngle, quadPoint, type Vec } from "../lib/motion";
import type { PointTarget } from "./store";

const FLIGHT_MS = 700;
const LINGER_MS = 6000;

/**
 * Flies an arrow from `from` to the target's centre along an upward arc, then pulses a
 * highlight ring around the target's real bounding box.
 */
export function Pointer({ target, from, onDone }: { target: PointTarget; from: Vec; onDone: () => void }) {
  const arrow = useRef<HTMLDivElement>(null);
  const [arrived, setArrived] = useState(false);
  const fromRef = useRef(from);

  useEffect(() => {
    setArrived(false);
    const a = fromRef.current;
    const b = { x: target.rect.x + target.rect.w / 2, y: target.rect.y + target.rect.h / 2 };
    const c = arcControl(a, b);
    const start = performance.now();
    let raf = 0;
    let lingerTimer: ReturnType<typeof setTimeout> | undefined;

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / FLIGHT_MS);
      const e = easeInOutCubic(t);
      const p = quadPoint(a, c, b, e);
      const angle = quadAngle(a, c, b, Math.max(0.001, e));
      if (arrow.current) {
        arrow.current.style.transform = `translate(${p.x}px, ${p.y}px) rotate(${angle}rad)`;
      }
      if (t < 1) {
        raf = requestAnimationFrame(tick);
      } else {
        setArrived(true);
        lingerTimer = setTimeout(onDone, LINGER_MS);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      if (lingerTimer) clearTimeout(lingerTimer);
    };
    // Re-run only for a new request.
  }, [target.seq]);

  const pad = 6;
  const r = target.rect;
  return (
    <>
      <div ref={arrow} className={`pointer ${arrived ? "pointer--arrived" : ""}`} aria-hidden>
        <svg viewBox="0 0 32 32" width="28" height="28">
          <path d="M30 16 4 4l6 12-6 12z" fill="#f97316" stroke="#fff" strokeWidth="2" strokeLinejoin="round" />
        </svg>
      </div>
      {arrived && target.highlight && (
        <div
          className="highlight-ring"
          style={{ left: r.x - pad, top: r.y - pad, width: r.w + pad * 2, height: r.h + pad * 2 }}
          aria-hidden
        />
      )}
    </>
  );
}
