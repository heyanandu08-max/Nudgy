import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { Button } from "../../components/ui";
import { errorKey } from "../../lib/errors";
import { Card, Row, SettingsHeading } from "./parts";
import { useSave } from "./useSave";

type Pending = "export" | "local" | "account" | null;
type Result = { kind: "ok" | "err"; key: string } | null;

function host(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** What is sent where, and the export / delete controls. */
export function PrivacySection() {
  const { t } = useTranslation();
  const { settings } = useSave();
  const [signedIn, setSignedIn] = useState(false);
  const [confirm, setConfirm] = useState<"local" | "account" | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [result, setResult] = useState<Result>(null);

  useEffect(() => {
    const read = () => void invoke<unknown>("auth_state").then((s) => setSignedIn(!!s));
    read();
    const off = listen("auth-changed", read);
    return () => void off.then((f) => f());
  }, []);

  const run = async (what: Exclude<Pending, null>) => {
    setPending(what);
    setResult(null);
    try {
      if (what === "export") {
        const saved = await invoke<boolean>("privacy_export");
        if (saved) setResult({ kind: "ok", key: "privacy.exported" });
      } else {
        await invoke("privacy_delete", { account: what === "account" });
        setResult({ kind: "ok", key: what === "account" ? "privacy.accountDeleted" : "privacy.localDeleted" });
      }
    } catch (e) {
      setResult({ kind: "err", key: errorKey((e as { code?: string })?.code) });
    } finally {
      setPending(null);
      setConfirm(null);
    }
  };

  const flows: [string, string][] = [
    ["privacy.askTitle", "privacy.askBody"],
    ["privacy.lessonTitle", "privacy.lessonBody"],
    ["privacy.walkTitle", "privacy.walkBody"],
    ["privacy.neverTitle", "privacy.neverBody"],
  ];

  const confirmRow = (what: "local" | "account") => (
    <>
      <span className="text-xs text-ink-2">{t("privacy.sure")}</span>
      <Button variant="primary" disabled={pending !== null} onClick={() => void run(what)}>
        {pending === what ? t("privacy.deleting") : t("privacy.yesDelete")}
      </Button>
      <Button variant="ghost" onClick={() => setConfirm(null)}>
        {t("privacy.cancel")}
      </Button>
    </>
  );

  return (
    <>
      <SettingsHeading before={t("privacy.title")} em={t("privacy.titleEm")} sub={t("privacy.sub", { host: host(settings.backendUrl) })} />
      <Card>
        {flows.map(([title, body]) => (
          <div key={title} className="border-b border-line px-[18px] py-4 last:border-b-0">
            <p className="text-[13.5px] font-medium">{t(title)}</p>
            <p className="mt-1 max-w-[560px] text-xs leading-relaxed text-ink-2">{t(body, { host: host(settings.backendUrl) })}</p>
          </div>
        ))}
      </Card>
      <Card>
        <Row title={t("privacy.export")} help={t("privacy.exportHelp")}>
          <Button disabled={pending !== null} onClick={() => void run("export")}>
            {pending === "export" ? t("privacy.exporting") : t("privacy.exportButton")}
          </Button>
        </Row>
        <Row title={t("privacy.deleteLocal")} help={t("privacy.deleteLocalHelp")}>
          {confirm === "local" ? confirmRow("local") : <Button onClick={() => setConfirm("local")}>{t("privacy.deleteButton")}</Button>}
        </Row>
        {signedIn && (
          <Row title={t("privacy.deleteAccount")} help={t("privacy.deleteAccountHelp")}>
            {confirm === "account" ? confirmRow("account") : <Button onClick={() => setConfirm("account")}>{t("privacy.deleteButton")}</Button>}
          </Row>
        )}
      </Card>
      {result && (
        <p role="status" className={`mt-4 font-mono text-xs ${result.kind === "ok" ? "text-good" : "text-accent"}`}>
          {t(result.key)}
        </p>
      )}
    </>
  );
}
