import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, StatusDot } from "../../components/ui";
import { Card, Row, SettingsHeading } from "./parts";
import { TimingsCard } from "./Timings";
import { UpdateControl } from "./UpdateControl";
import { useHealth } from "./useHealth";
import { useSave } from "./useSave";

export function AboutSection() {
  const { t } = useTranslation();
  const { settings, update, error } = useSave();
  const [url, setUrl] = useState(settings.backendUrl);
  const { health, check } = useHealth(settings.backendUrl);
  useEffect(() => setUrl(settings.backendUrl), [settings.backendUrl]);

  const text = health.state === "ok" ? t("health.ok", { version: health.version }) : health.state === "down" ? t("health.down") : t("health.checking");
  return (
    <>
      <SettingsHeading before={t("settings.aboutTitle")} em={t("settings.aboutEm")} sub={t("settings.aboutSub")} />
      {error && <p className="mt-4 font-mono text-xs text-accent">{t("settings.saveFailed", { error })}</p>}
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
        <Row title={t("settings.version")}>
          <span className="font-mono text-xs text-ink-2">{__APP_VERSION__}</span>
        </Row>
        <Row title={t("settings.updates")}>
          <UpdateControl />
        </Row>
        <Row title={t("settings.intro")} help={t("settings.introHelp")}>
          <Button onClick={() => void update({ onboarded: false })}>{t("settings.introButton")}</Button>
        </Row>
      </Card>
      <TimingsCard />
    </>
  );
}
