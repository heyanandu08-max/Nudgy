import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Segmented, Toggle } from "../../components/ui";
import {
  FALLBACK_CONFIG,
  fetchClientConfig,
  type ClientConfig,
} from "../../lib/api";
import type {
  CursorColor,
  CursorSize,
  ResponseLength,
} from "../../lib/settings";
import { Card, Row, SettingsHeading } from "./parts";
import { useSave } from "./useSave";

/** Blocklist chips shown before "+N more". */
const CHIPS = 3;
const SWATCHES: Record<CursorColor, string> = {
  black: "#0A0A0A",
  white: "#FFFFFF",
  red: "#FF4A1C",
  blue: "#2563EB",
};

export function CursorSection() {
  const { t } = useTranslation();
  const { settings, update, error } = useSave();
  const [config, setConfig] = useState<ClientConfig>(FALLBACK_CONFIG);
  const [adding, setAdding] = useState("");
  const [allBlocked, setAllBlocked] = useState(false);

  useEffect(() => {
    fetchClientConfig(settings.backendUrl)
      .then(setConfig)
      .catch(() => setConfig(FALLBACK_CONFIG));
  }, [settings.backendUrl]);

  const addApp = () => {
    const name = adding.trim();
    if (
      name &&
      !settings.blocklist.some((b) => b.toLowerCase() === name.toLowerCase())
    ) {
      void update({ blocklist: [...settings.blocklist, name] });
    }
    setAdding("");
  };

  return (
    <>
      <SettingsHeading
        before={t("settings.cursorTitle")}
        em={t("settings.cursorTitleEm")}
        sub={t("settings.cursorSub")}
      />
      {settings.paused && (
        <p className="mt-4 text-[13px] text-ink-2">{t("settings.paused")}</p>
      )}
      {error && (
        <p className="mt-4 font-mono text-xs text-accent">
          {t("settings.saveFailed", { error })}
        </p>
      )}
      <Card>
        <Row
          title={t("settings.cursorColor")}
          help={t("settings.cursorColorHelp")}
        >
          <div
            role="radiogroup"
            aria-label={t("settings.cursorColor")}
            className="flex gap-2"
          >
            {(Object.keys(SWATCHES) as CursorColor[]).map((c) => (
              <button
                key={c}
                type="button"
                role="radio"
                aria-checked={settings.cursorColor === c}
                aria-label={t(`settings.colors.${c}`)}
                onClick={() => void update({ cursorColor: c })}
                className={`h-7 w-7 rounded-full border border-line-2 ${settings.cursorColor === c ? "outline-2 outline-offset-2 outline-ink" : ""}`}
                style={{ background: SWATCHES[c] }}
              />
            ))}
          </div>
        </Row>
        <Row
          title={t("settings.cursorSize")}
          help={t("settings.cursorSizeHelp")}
        >
          <Segmented<CursorSize>
            label={t("settings.cursorSize")}
            value={settings.cursorSize}
            onChange={(v) => void update({ cursorSize: v })}
            options={[
              { value: "s", label: "S" },
              { value: "m", label: "M" },
              { value: "l", label: "L" },
            ]}
          />
        </Row>
        <Row
          title={t("settings.voice")}
          help={t("settings.voiceHelp")}
          htmlFor="voice"
        >
          <span className="relative inline-flex items-center">
            <select
              id="voice"
              className="appearance-none rounded-[9px] border border-line-2 bg-white py-[7px] pr-8 pl-3 text-[12.5px] disabled:opacity-50"
              disabled={!settings.voiceEnabled}
              value={settings.voiceId ?? ""}
              onChange={(e) => void update({ voiceId: e.target.value || null })}
            >
              <option value="">{t("settings.voiceDefault")}</option>
              {config.voices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
            <svg
              aria-hidden
              width="10"
              height="6"
              viewBox="0 0 10 6"
              className="pointer-events-none absolute right-3 fill-ink"
            >
              <path d="M0 0h10L5 6z" />
            </svg>
          </span>
        </Row>
        <Row title={t("settings.speak")} help={t("settings.speakHelp")}>
          <Toggle
            label={t("settings.speak")}
            checked={settings.voiceEnabled}
            onChange={(v) => void update({ voiceEnabled: v })}
          />
        </Row>
        <Row title={t("settings.length")} help={t("settings.lengthHelp")}>
          <Segmented<ResponseLength>
            label={t("settings.length")}
            value={settings.responseLength}
            onChange={(v) => void update({ responseLength: v })}
            options={[
              { value: "brief", label: t("settings.short") },
              { value: "detailed", label: t("settings.detailed") },
            ]}
          />
        </Row>
      </Card>
      <Card>
        <Row title={t("settings.blocklist")} help={t("settings.blocklistHelp")}>
          {(allBlocked
            ? settings.blocklist
            : settings.blocklist.slice(0, CHIPS)
          ).map((b) => (
            <button
              key={b}
              type="button"
              onClick={() =>
                void update({
                  blocklist: settings.blocklist.filter((x) => x !== b),
                })
              }
              aria-label={t("settings.remove", { app: b })}
              className="rounded-full border border-line-2 bg-paper px-2.5 py-0.5 font-mono text-[11px] text-ink-2 hover:border-ink-3 hover:line-through"
            >
              {b}
            </button>
          ))}
          {!allBlocked && settings.blocklist.length > CHIPS && (
            <button
              type="button"
              onClick={() => setAllBlocked(true)}
              className="rounded-full px-1.5 py-0.5 font-mono text-[11px] text-ink-3 hover:text-ink"
            >
              {t("settings.more", { count: settings.blocklist.length - CHIPS })}
            </button>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              addApp();
            }}
          >
            <input
              aria-label={t("settings.addPlaceholder")}
              placeholder={t("settings.add")}
              value={adding}
              onChange={(e) => setAdding(e.target.value)}
              onBlur={addApp}
              className="w-28 rounded-full border border-line-2 bg-paper px-2.5 py-0.5 font-mono text-[11px] placeholder:text-ink-2 focus:w-40"
            />
          </form>
        </Row>
        <Row title={t("settings.hideIdle")} help={t("settings.hideIdleHelp")}>
          <Toggle
            label={t("settings.hideIdle")}
            checked={settings.hideCursorIdle}
            onChange={(v) => void update({ hideCursorIdle: v })}
          />
        </Row>
      </Card>
    </>
  );
}
