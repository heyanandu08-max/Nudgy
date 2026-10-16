import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { useTranslation } from "react-i18next";
import { Button, StatusDot } from "../../components/ui";
import { Card, Row, SettingsHeading } from "./parts";
import { TimingsCard } from "./Timings";
import { UpdateControl } from "./UpdateControl";
import { useHealth } from "./useHealth";
import { LegalLink, useLegalInfo, type LegalPage } from "../legal/LegalLinks";
import { useAiStatus } from "../ai/AiSetupCard";
import { useSave } from "./useSave";

export function AboutSection() {
  const { t } = useTranslation();
  const { settings, update, error } = useSave();
  const [url, setUrl] = useState(settings.backendUrl);
  const { health, check } = useHealth(settings.backendUrl);
  const legal = useLegalInfo();
  const ai = useAiStatus();
  // Set when this install bundles the server (the all-in-one installer): where its keys go.
  const [serverEnv, setServerEnv] = useState<string | null>(null);
  const [serverNote, setServerNote] = useState<string | null>(null);
  useEffect(() => {
    if (isTauri())
      invoke<string | null>("local_server_info")
        .then(setServerEnv)
        .catch(() => setServerEnv(null));
  }, []);
  const serverAction = (cmd: string, done: string) =>
    invoke(cmd)
      .then(() => setServerNote(done))
      .catch((e) => setServerNote(String(e)));
  const pages: LegalPage[] = ["privacy", "terms", "cookies", "licenses", "delete-account"];
  useEffect(() => setUrl(settings.backendUrl), [settings.backendUrl]);

  const text = health.state === "ok" ? t("health.ok", { version: health.version }) : health.state === "down" ? t("health.down") : t("health.checking");
  return (
    <>
      <SettingsHeading before={t("settings.aboutTitle")} em={t("settings.aboutEm")} sub={t("settings.aboutSub")} />
      {error && <p className="mt-4 font-mono text-xs text-accent-ink">{t("settings.saveFailed", { error })}</p>}
      <Card>
        <Row title={t("settings.server")} help={t("settings.serverHelp")} htmlFor="server">
          <input
            id="server"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onBlur={() => url !== settings.backendUrl && void update({ backendUrl: url })}
            className="w-64 rounded-[9px] border border-line-2 bg-white px-3 py-[7px] font-mono text-xs"
          />
        </Row>
        <Row title={t("settings.serverStatus")}>
          <StatusDot tone={health.state === "ok" ? "good" : health.state === "down" ? "bad" : "wait"} />
          <span className="font-mono text-xs text-ink-2" role="status">
            {text}
          </span>
          {health.state === "down" && <Button onClick={check}>{t("health.retry")}</Button>}
        </Row>
        {ai.state !== "unavailable" && (
          <Row title={t("ai.settingTitle")} help={t("ai.settingHelp")}>
            <span className="font-mono text-xs text-ink-2" role="status">
              {t(`ai.state.${ai.state}`)}
            </span>
          </Row>
        )}
        {serverEnv && (
          <Row title={t("settings.localServer")} help={t("settings.localServerHelp")}>
            <Button onClick={() => serverAction("local_server_open_settings", t("settings.localServerOpened"))}>{t("settings.localServerOpen")}</Button>
            <Button onClick={() => serverAction("local_server_restart", t("settings.localServerRestarted"))}>{t("settings.localServerRestart")}</Button>
            {serverNote && (
              <span className="font-mono text-[11px] text-ink-3" role="status">
                {serverNote}
              </span>
            )}
          </Row>
        )}
        <Row title={t("settings.version")}>
          <span className="font-mono text-xs text-ink-2">{__APP_VERSION__}</span>
        </Row>
        <Row title={t("settings.updates")}>
          <UpdateControl />
        </Row>
        <Row title={t("legal.title")} help={legal ? [legal.company, legal.address].filter(Boolean).join(" · ") : undefined}>
          <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-2">
            {pages.map((p) => (
              <LegalLink key={p} page={p} />
            ))}
            {legal?.contact_email && (
              <a className="underline underline-offset-2 hover:text-ink" href={`mailto:${legal.contact_email}`}>
                {legal.contact_email}
              </a>
            )}
          </span>
        </Row>
        <Row title={t("settings.intro")} help={t("settings.introHelp")}>
          <Button onClick={() => void update({ onboarded: false })}>{t("settings.introButton")}</Button>
        </Row>
      </Card>
      <TimingsCard />
    </>
  );
}
