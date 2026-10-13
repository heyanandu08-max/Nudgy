import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import de from "./locales/de.json";
import en from "./locales/en.json";
import es from "./locales/es.json";
import fr from "./locales/fr.json";
import hi from "./locales/hi.json";
import pt from "./locales/pt.json";

export const resources = {
  en: { translation: en },
  es: { translation: es },
  pt: { translation: pt },
  fr: { translation: fr },
  de: { translation: de },
  hi: { translation: hi },
} as const;

/** The UI follows the "Language" setting; languages without a translation fall back to English. */
export function setLanguage(code: string | undefined): void {
  const lng = code && code in resources ? code : "en";
  if (i18n.language !== lng) void i18n.changeLanguage(lng);
  if (typeof document !== "undefined") document.documentElement.lang = lng;
}

i18n.use(initReactI18next).init({
  resources,
  lng: "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

// Every window (main, overlay, ask box) imports this module, so each keeps itself in sync.
if (isTauri()) {
  invoke<{ language: string }>("get_settings")
    .then((s) => setLanguage(s.language))
    .catch(() => {});
  void listen<{ language: string }>("settings-changed", (e) => setLanguage(e.payload.language));
}

export default i18n;
