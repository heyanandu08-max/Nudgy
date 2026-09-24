import { invoke } from "@tauri-apps/api/core";
import { emit } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import i18n from "../../i18n";
import { errorCode, errorKey } from "../../lib/errors";

/** Stop → clean via the backend → save → show the Walkthroughs tab with the result. */
export async function finishRecording(showTab: (tab: string) => void): Promise<void> {
  await invoke("speak", { text: i18n.t("walkthroughs.cleaning") }).catch(() => {});
  try {
    const w = await invoke<{ title: string; steps: unknown[] }>("recorder_finish");
    await invoke("speak", { text: i18n.t("walkthroughs.saved", { title: w.title, count: w.steps.length }) }).catch(() => {});
  } catch (e) {
    await invoke("speak", { text: i18n.t(errorKey(errorCode(e))) }).catch(() => {});
  }
  void emit("walkthroughs-changed");
  showTab("walkthroughs");
  const win = getCurrentWindow();
  await win.show().catch(() => {});
  await win.setFocus().catch(() => {});
}
