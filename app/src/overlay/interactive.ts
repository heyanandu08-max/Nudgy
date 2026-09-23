import { useEffect, type RefObject } from "react";
import { invoke } from "@tauri-apps/api/core";

/**
 * Several overlay widgets (lesson panel, review card) need to receive clicks. Each registers
 * its box here; the union is sent to Rust, which disables click-through only over them.
 */
const regions = new Map<string, DOMRect>();

function sync() {
  const rects = [...regions.values()].map((r) => ({ x: r.x, y: r.y, w: r.width, h: r.height }));
  void invoke("set_interactive_regions", { rects }).catch(() => {});
}

export function useInteractiveRegion(id: string, ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const report = () => {
      regions.set(id, el.getBoundingClientRect());
      sync();
    };
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    window.addEventListener("resize", report);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", report);
      regions.delete(id);
      sync();
    };
  }, [id, ref]);
}
