import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Hotkey } from "../../components/ui";
import { FALLBACK_CONFIG, fetchClientConfig, type ClientConfig } from "../../lib/api";
import { Card, Row, SettingsHeading } from "./parts";
import { useSave } from "./useSave";

/** KeyboardEvent → accelerator string understood by the global-shortcut plugin. */
export function acceleratorFrom(e: Pick<KeyboardEvent, "ctrlKey" | "altKey" | "shiftKey" | "metaKey" | "code" | "key">): string | null {
  const mods = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", e.metaKey && "Super"].filter(Boolean) as string[];
  let key: string | null = null;
  if (e.code === "Space") key = "Space";
  else if (/^Key[A-Z]$/.test(e.code)) key = e.code.slice(3);
  else if (/^Digit\d$/.test(e.code)) key = e.code.slice(5);
  else if (/^F\d{1,2}$/.test(e.code)) key = e.code;
  if (!key || mods.length === 0) return null; // a bare key would fire while typing
  return [...mods, key].join("+");
}

export function HotkeySection() {
  const { t } = useTranslation();
  const { settings, update, error } = useSave();
  const [recording, setRecording] = useState(false);
  const [config, setConfig] = useState<ClientConfig>(FALLBACK_CONFIG);

  useEffect(() => {
    fetchClientConfig(settings.backendUrl).then(setConfig).catch(() => setConfig(FALLBACK_CONFIG));
  }, [settings.backendUrl]);

  useEffect(() => {
    if (!recording) return;
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      if (e.key === "Escape") return setRecording(false);
      const acc = acceleratorFrom(e);
      if (acc) {
        setRecording(false);
        void update({ hotkey: acc });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [recording, update]);

  return (
    <>
      <SettingsHeading before={t("settings.hotkeyTitle")} em={t("settings.hotkeyTitleEm")} sub={t("settings.hotkeySub")} />
      {error && <p className="mt-4 font-mono text-xs text-accent">{t("settings.saveFailed", { error })}</p>}
      <Card>
        <Row title={t("settings.hotkey")} help={t("settings.hotkeyHelp")}>
          {recording ? <span className="font-mono text-xs text-ink-3">{t("settings.hotkeyRecording")}</span> : <Hotkey accelerator={settings.hotkey} />}
          <Button onClick={() => setRecording(!recording)}>{t("settings.hotkeyChange")}</Button>
        </Row>
        <Row title={t("settings.language")} help={t("settings.languageHelp")} htmlFor="language">
          <select
            id="language"
            className="rounded-[9px] border border-line-2 bg-white px-3 py-[7px] text-[12.5px]"
            value={settings.language}
            onChange={(e) => void update({ language: e.target.value })}
          >
            {config.languages.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name}
              </option>
            ))}
          </select>
        </Row>
      </Card>
    </>
  );
}
