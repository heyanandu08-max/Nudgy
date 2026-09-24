import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { Card } from "./parts";

type Stage = Record<string, number | null | undefined>;
interface Timings {
  client: Stage;
  server: Stage | null;
}

/** Target from the brief: first audio within 2.5 s of letting go of the hotkey. */
export const FIRST_AUDIO_TARGET_MS = 2500;

const CLIENT = ["capture_ms", "first_event_ms", "first_audio_ms", "total_ms"];
const SERVER = ["stt_ms", "llm_first_token_ms", "first_text_ms", "llm_ms", "first_audio_ms", "total_ms"];

/** Debug panel: per-stage timings of the last answer (Settings → About). */
export function TimingsCard() {
  const { t } = useTranslation();
  const [timings, setTimings] = useState<Timings | null>(null);

  useEffect(() => {
    if (!isTauri()) return;
    void invoke<Timings | null>("last_timings").then(setTimings);
    const off = listen<Timings>("ask-timings", (e) => setTimings(e.payload));
    return () => void off.then((f) => f());
  }, []);

  const firstAudio = timings?.client.first_audio_ms;
  const rows = (stage: Stage | null | undefined, keys: string[]) =>
    keys
      .filter((k) => typeof stage?.[k] === "number")
      .map((k) => (
        <div key={k} className="flex justify-between gap-4">
          <dt className="text-ink-3">{k.replace(/_ms$/, "")}</dt>
          <dd>{Math.round(stage![k] as number)} ms</dd>
        </div>
      ));

  return (
    <Card>
      <div className="px-[18px] py-4">
        <p className="text-[13.5px] font-medium">{t("settings.timings")}</p>
        {!timings ? (
          <p className="mt-1 text-xs text-ink-3">{t("settings.timingsNone")}</p>
        ) : (
          <>
            {typeof firstAudio === "number" && (
              <p className={`mt-1 font-mono text-xs ${firstAudio <= FIRST_AUDIO_TARGET_MS ? "text-good" : "text-accent"}`}>
                {t("settings.timingsFirstAudio", { ms: Math.round(firstAudio), target: FIRST_AUDIO_TARGET_MS })}
              </p>
            )}
            <div className="mt-3 grid grid-cols-2 gap-8 font-mono text-[11.5px]">
              <div>
                <p className="mb-1 text-ink-2">{t("settings.timingsApp")}</p>
                <dl className="space-y-0.5">{rows(timings.client, CLIENT)}</dl>
              </div>
              <div>
                <p className="mb-1 text-ink-2">{t("settings.timingsServer")}</p>
                <dl className="space-y-0.5">{rows(timings.server, SERVER)}</dl>
              </div>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
