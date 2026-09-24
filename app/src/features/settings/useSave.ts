import { useState } from "react";
import type { Settings } from "../../lib/settings";
import { useSettings } from "../../stores/settings";

/** Settings save as you change them; returns an error message if the last save failed. */
export function useSave() {
  const { settings, save } = useSettings();
  const [error, setError] = useState<string | null>(null);
  const update = async (patch: Partial<Settings>) => {
    try {
      await save({ ...settings, ...patch });
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };
  return { settings, update, error };
}
