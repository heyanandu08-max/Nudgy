import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";

/** Mirrors local_ai::Status. */
export type AiStatus =
  | { state: "unavailable" }
  | { state: "not_set_up"; download_bytes: number }
  | { state: "downloading"; file: string; done: number; total: number }
  | { state: "starting" }
  | { state: "ready" }
  | { state: "failed"; message: string };

export function useAiStatus(): AiStatus {
  const [status, setStatus] = useState<AiStatus>({ state: "unavailable" });
  useEffect(() => {
    if (!isTauri()) return;
    invoke<AiStatus>("ai_status")
      .then(setStatus)
      .catch(() => {});
    const off = listen<AiStatus>("ai-status", (e) => setStatus(e.payload));
    return () => void off.then((f) => f());
  }, []);
  return status;
}

const gb = (bytes: number) => (bytes / 1e9).toFixed(1);

/** Home card: offers the free built-in AI (one-time download), then shows its progress. */
export function AiSetupCard({ status }: { status: AiStatus }) {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  if (status.state === "unavailable" || status.state === "ready") return null;
  const setup = () => {
    setError(null);
    invoke("ai_setup").catch((e) => setError(String(e)));
  };
  const pct = status.state === "downloading" && status.total ? Math.round((status.done / status.total) * 100) : 0;

  return (
    <section className="mt-7 rounded-card border-[1.5px] border-ink bg-white p-5">
      <p className="font-mono text-[11px] text-ink-3 uppercase">{t("ai.meta")}</p>
      <h2 className="mt-1 text-[17px] font-semibold">{t("ai.title")}</h2>
      {status.state === "not_set_up" && (
        <>
          <p className="mt-1.5 text-[13px] leading-[1.5] text-ink-2">{t("ai.body")}</p>
          <p className="mt-2 font-mono text-[11px] text-ink-3">{t("ai.needs", { size: gb(status.download_bytes) })}</p>
          <button type="button" onClick={setup} className="mt-4 rounded-btn bg-ink px-4 py-2 text-[13px] font-medium text-white hover:bg-black">
            {t("ai.setup")}
          </button>
        </>
      )}
      {status.state === "downloading" && (
        <>
          <p className="mt-1.5 text-[13px] text-ink-2">{t("ai.downloading")}</p>
          <div className="mt-3 h-1.5 overflow-hidden rounded bg-line" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={t("ai.title")}>
            <i className="block h-full bg-ink transition-[width]" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-2 font-mono text-[11px] text-ink-3">{t("ai.progress", { file: status.file, done: gb(status.done), total: gb(status.total), pct })}</p>
        </>
      )}
      {status.state === "starting" && <p className="mt-1.5 text-[13px] text-ink-2">{t("ai.starting")}</p>}
      {status.state === "failed" && (
        <>
          <p className="mt-1.5 text-[13px] text-accent-ink">{t("ai.failed", { error: status.message })}</p>
          <button type="button" onClick={setup} className="mt-3 rounded-btn border border-line-2 bg-white px-4 py-2 text-[13px] hover:border-ink-3">
            {t("ai.retry")}
          </button>
        </>
      )}
      {error && <p className="mt-2 font-mono text-[11px] text-accent-ink">{error}</p>}
    </section>
  );
}
