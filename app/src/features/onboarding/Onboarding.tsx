import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import logo from "../../assets/logo.svg";
import { Button, Hotkey } from "../../components/ui";
import { useSave } from "../settings/useSave";

type Status = "granted" | "denied" | "unknown";
interface Permissions {
  screen: Status;
  accessibility: Status;
  microphone: Status;
  needs_walkthrough: boolean;
}
type Kind = "screen" | "accessibility" | "microphone";
const KINDS: Kind[] = ["screen", "accessibility", "microphone"];
/** Permission state is re-read this often while the step is open (the user flips it in System Settings). */
const POLL_MS = 1500;

/** First run: what Nudgy is → macOS permissions → ask a first question. */
export function Onboarding() {
  const { t } = useTranslation();
  const { settings, update } = useSave();
  const [step, setStep] = useState(0);
  const [perms, setPerms] = useState<Permissions | null>(null);
  const [asked, setAsked] = useState(false);

  useEffect(() => {
    if (!isTauri()) return;
    const read = () => void invoke<Permissions>("permissions").then(setPerms);
    read();
    const id = setInterval(read, POLL_MS);
    const off = listen("ask-done", () => setAsked(true));
    return () => {
      clearInterval(id);
      void off.then((f) => f());
    };
  }, []);

  const steps = perms?.needs_walkthrough ? ["welcome", "permissions", "try"] : ["welcome", "try"];
  const current = steps[Math.min(step, steps.length - 1)];
  const next = () => setStep((s) => s + 1);
  const finish = () => void update({ onboarded: true });
  const allGranted = !perms || KINDS.every((k) => perms[k] !== "denied");

  return (
    <div className="flex h-full min-w-[760px] flex-col bg-bg">
      <header className="flex items-center justify-between border-b border-line bg-paper px-4 py-3">
        <img src={logo} alt="Nudgy" className="h-6" />
        <span className="font-mono text-[11px] text-ink-3">{t("onboarding.progress", { n: step + 1, total: steps.length })}</span>
      </header>
      <main className="flex flex-1 items-center justify-center overflow-auto px-14 py-10">
        <div className="w-full max-w-[560px]">
          {current === "welcome" && (
            <>
              <h1 className="text-[36px] leading-[1.1] font-semibold tracking-[-.02em]">
                {t("onboarding.welcomeBefore")}
                <em className="font-serif font-medium">{t("onboarding.welcomeEm")}</em>
                {t("onboarding.welcomeAfter")}
              </h1>
              <p className="mt-4 text-[15px] leading-relaxed text-ink-2">{t("onboarding.welcomeBody")}</p>
              <p className="mt-3 text-[15px] leading-relaxed text-ink-2">{t("onboarding.welcomePrivacy")}</p>
              <div className="mt-8 flex gap-2">
                <Button variant="primary" onClick={next}>
                  {t("onboarding.start")} <span aria-hidden>→</span>
                </Button>
                <Button variant="ghost" onClick={finish}>
                  {t("onboarding.skip")}
                </Button>
              </div>
            </>
          )}

          {current === "permissions" && perms && (
            <>
              <h1 className="text-[30px] leading-[1.15] font-semibold tracking-[-.02em]">{t("onboarding.permsTitle")}</h1>
              <p className="mt-3 text-[14px] leading-relaxed text-ink-2">{t("onboarding.permsBody")}</p>
              <div className="mt-6 rounded-card border border-line-2 bg-white">
                {KINDS.map((k) => (
                  <div key={k} className="flex items-center gap-4 border-b border-line px-[18px] py-4 last:border-b-0">
                    <div className="min-w-0">
                      <p className="text-[13.5px] font-medium">{t(`onboarding.perm.${k}`)}</p>
                      <p className="mt-0.5 text-xs text-ink-3">{t(`onboarding.perm.${k}Why`)}</p>
                    </div>
                    <div className="ml-auto flex items-center gap-2">
                      {perms[k] === "granted" ? (
                        <span className="font-mono text-xs text-good">{t("onboarding.allowed")}</span>
                      ) : (
                        <Button onClick={() => void invoke("permission_request", { kind: k })}>
                          {perms[k] === "unknown" ? t("onboarding.check") : t("onboarding.allow")}
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-ink-3">{t("onboarding.permsRestart")}</p>
              <div className="mt-8">
                <Button variant={allGranted ? "primary" : "secondary"} onClick={next}>
                  {allGranted ? t("onboarding.continue") : t("onboarding.later")}
                </Button>
              </div>
            </>
          )}

          {current === "try" && (
            <>
              <h1 className="text-[30px] leading-[1.15] font-semibold tracking-[-.02em]">{t("onboarding.tryTitle")}</h1>
              <ol className="mt-6 space-y-4 text-[15px]">
                <li className="flex items-center gap-3">
                  <span className="font-mono text-xs text-ink-3">01</span>
                  <span>{t("onboarding.tryHold")}</span>
                  <Hotkey accelerator={settings.hotkey} />
                </li>
                <li className="flex items-center gap-3">
                  <span className="font-mono text-xs text-ink-3">02</span>
                  <span>{t("onboarding.tryAsk")}</span>
                </li>
                <li className="flex items-center gap-3">
                  <span className="font-mono text-xs text-ink-3">03</span>
                  <span>{t("onboarding.tryLet")}</span>
                </li>
              </ol>
              <p className="mt-4 text-[13px] text-ink-2">{t("onboarding.tryType")}</p>
              <p role="status" className={`mt-6 font-mono text-xs ${asked ? "text-good" : "text-ink-3"}`}>
                {asked ? t("onboarding.tryDone") : t("onboarding.tryWaiting")}
              </p>
              <div className="mt-8 flex gap-2">
                <Button variant={asked ? "primary" : "secondary"} onClick={finish}>
                  {asked ? t("onboarding.finish") : t("onboarding.finishLater")}
                </Button>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
