import { useCallback, useEffect, useState } from "react";
import { fetchHealth } from "../../lib/api";

export type Health = { state: "checking" } | { state: "ok"; version: string } | { state: "down" };

const POLL_MS = 15_000;

export function useHealth(backendUrl: string) {
  const [health, setHealth] = useState<Health>({ state: "checking" });

  const check = useCallback(async () => {
    setHealth({ state: "checking" });
    try {
      const h = await fetchHealth(backendUrl);
      setHealth(h.status === "ok" ? { state: "ok", version: h.version } : { state: "down" });
    } catch {
      setHealth({ state: "down" });
    }
  }, [backendUrl]);

  useEffect(() => {
    check();
    const id = setInterval(check, POLL_MS);
    return () => clearInterval(id);
  }, [check]);

  return { health, check };
}
