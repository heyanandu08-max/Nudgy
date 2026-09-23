import { useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { follow, type Vec } from "../lib/motion";
import { Companion } from "./Companion";
import { Pointer } from "./Pointer";
import { useOverlay, type CompanionMode, type Rect } from "./store";

/** Where the companion sits relative to the cursor (CSS px). */
const OFFSET = { x: 22, y: 22 };

interface PointPayload {
  rect: Rect;
  actionHint: string | null;
  highlight: boolean;
}

export function OverlayApp() {
  const { active, mode, target, setActive, setMode, pointAt, clearTarget } = useOverlay();
  const companion = useRef<HTMLDivElement>(null);
  const cursor = useRef<Vec>({ x: -100, y: -100 });
  const pos = useRef<Vec>({ x: -100, y: -100 });
  const [pointerFrom, setPointerFrom] = useState<Vec>({ x: 0, y: 0 });

  useEffect(() => {
    const subs = [
      listen<Vec>("cursor", (e) => {
        cursor.current = e.payload;
        setActive(true);
      }),
      listen("cursor-left", () => setActive(false)),
      listen<CompanionMode>("companion-state", (e) => setMode(e.payload)),
      listen<PointPayload>("point", (e) => {
        setPointerFrom({ ...pos.current });
        pointAt(e.payload);
      }),
    ];
    return () => subs.forEach((p) => p.then((off) => off()));
  }, [setActive, setMode, pointAt]);

  // Companion follows the cursor with a slight, frame-rate independent lag.
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = now - last;
      last = now;
      const goal = { x: cursor.current.x + OFFSET.x, y: cursor.current.y + OFFSET.y };
      pos.current = follow(pos.current, goal, dt);
      if (companion.current) {
        companion.current.style.transform = `translate(${pos.current.x}px, ${pos.current.y}px)`;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const shownMode: CompanionMode = target ? "pointing" : mode;

  return (
    <div className="overlay-root">
      <div ref={companion} className={`companion-anchor ${active ? "" : "companion-anchor--hidden"}`}>
        <Companion mode={shownMode} />
      </div>
      {target && <Pointer key={target.seq} target={target} from={pointerFrom} onDone={clearTarget} />}
    </div>
  );
}
