import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useTranslation } from "react-i18next";
import { Button } from "../../components/ui";
import { errorCode } from "../../lib/errors";

type State = { kind: "idle" | "checking" | "current" | "installing" | "failed" | "disabled" } | { kind: "available"; version: string };

/** "Check for updates" → "Install 0.2.0 and restart". Signed updates only (see updates.rs). */
export function UpdateControl() {
  const { t } = useTranslation();
  const [state, setState] = useState<State>({ kind: "idle" });

  const check = async () => {
    setState({ kind: "checking" });
    try {
      const u = await invoke<{ version: string } | null>("update_check");
      setState(u ? { kind: "available", version: u.version } : { kind: "current" });
    } catch (e) {
      setState({ kind: errorCode(e) === "updates_disabled" ? "disabled" : "failed" });
    }
  };
  const install = async () => {
    setState({ kind: "installing" });
    try {
      await invoke("update_install");
    } catch {
      setState({ kind: "failed" });
    }
  };

  if (state.kind === "available")
    return (
      <Button variant="primary" onClick={() => void install()}>
        {t("settings.updateInstall", { version: state.version })}
      </Button>
    );
  return (
    <>
      {state.kind !== "idle" && state.kind !== "checking" && (
        <span role="status" className="font-mono text-xs text-ink-2">
          {t(`settings.update_${state.kind}`)}
        </span>
      )}
      <Button disabled={state.kind === "checking" || state.kind === "installing"} onClick={() => void check()}>
        {state.kind === "checking" ? t("settings.updateChecking") : t("settings.updateCheck")}
      </Button>
    </>
  );
}
