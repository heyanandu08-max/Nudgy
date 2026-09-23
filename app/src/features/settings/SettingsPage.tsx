import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FALLBACK_CONFIG, fetchClientConfig, type ClientConfig } from "../../lib/api";
import type { ResponseLength, Settings } from "../../lib/settings";
import { useSettings } from "../../stores/settings";
import { HealthBadge } from "./HealthBadge";
import { useHealth } from "./useHealth";

const input =
  "w-full rounded-md border border-slate-300 bg-transparent px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-nudgy-500 dark:border-slate-600";

function Field({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {help && <span className="block text-xs text-slate-500">{help}</span>}
    </label>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  const { settings, save } = useSettings();
  const [draft, setDraft] = useState<Settings>(settings);
  const [status, setStatus] = useState<{ kind: "idle" | "saved" } | { kind: "error"; error: string }>({
    kind: "idle",
  });
  const [config, setConfig] = useState<ClientConfig>(FALLBACK_CONFIG);
  const { health, check } = useHealth(settings.backendUrl);

  useEffect(() => setDraft(settings), [settings]);

  useEffect(() => {
    if (health.state !== "ok") return;
    fetchClientConfig(settings.backendUrl)
      .then(setConfig)
      .catch(() => setConfig(FALLBACK_CONFIG));
  }, [health.state, settings.backendUrl]);

  const update = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setStatus({ kind: "idle" });
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await save(draft);
      setStatus({ kind: "saved" });
    } catch (err) {
      setStatus({ kind: "error", error: String(err) });
    }
  };

  return (
    <form onSubmit={onSubmit} className="mx-auto max-w-2xl space-y-5 p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t("settings.title")}</h1>
        <HealthBadge health={health} onRetry={check} />
      </header>

      {settings.paused && (
        <p className="rounded-md bg-nudgy-50 px-3 py-2 text-sm text-nudgy-600">{t("settings.paused")}</p>
      )}

      <Field label={t("settings.backendUrl")} help={t("settings.backendUrlHelp")}>
        <input
          className={input}
          type="url"
          required
          value={draft.backendUrl}
          onChange={(e) => update("backendUrl", e.target.value)}
        />
      </Field>

      <label className="flex items-center gap-2 text-sm font-medium">
        <input
          type="checkbox"
          checked={draft.voiceEnabled}
          onChange={(e) => update("voiceEnabled", e.target.checked)}
        />
        {t("settings.voiceEnabled")}
      </label>

      <Field label={t("settings.voice")} help={config.voices.length ? undefined : t("settings.voiceUnavailable")}>
        <select
          className={input}
          disabled={!draft.voiceEnabled || config.voices.length === 0}
          value={draft.voiceId ?? ""}
          onChange={(e) => update("voiceId", e.target.value || null)}
        >
          <option value="">—</option>
          {config.voices.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>
      </Field>

      <Field label={t("settings.hotkey")} help={t("settings.hotkeyHelp")}>
        <input
          className={input}
          required
          value={draft.hotkey}
          onChange={(e) => update("hotkey", e.target.value)}
        />
      </Field>

      <Field label={t("settings.responseLength")}>
        <select
          className={input}
          value={draft.responseLength}
          onChange={(e) => update("responseLength", e.target.value as ResponseLength)}
        >
          <option value="brief">{t("settings.responseLengthBrief")}</option>
          <option value="detailed">{t("settings.responseLengthDetailed")}</option>
        </select>
      </Field>

      <Field label={t("settings.language")}>
        <select className={input} value={draft.language} onChange={(e) => update("language", e.target.value)}>
          {config.languages.map((l) => (
            <option key={l.code} value={l.code}>
              {l.name}
            </option>
          ))}
        </select>
      </Field>

      <div className="flex items-center gap-3">
        <button
          type="submit"
          className="rounded-md bg-nudgy-500 px-4 py-2 text-sm font-medium text-white hover:bg-nudgy-600"
        >
          {t("settings.save")}
        </button>
        {status.kind === "saved" && <span className="text-sm text-emerald-600">{t("settings.saved")}</span>}
        {status.kind === "error" && (
          <span className="text-sm text-red-600">{t("settings.saveFailed", { error: status.error })}</span>
        )}
      </div>
    </form>
  );
}
