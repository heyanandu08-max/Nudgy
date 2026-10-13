import { useTranslation } from "react-i18next";

export function Footer() {
  const { t } = useTranslation();
  return (
    <footer className="flex shrink-0 justify-between border-t border-line bg-paper px-14 py-3.5 font-mono text-[11px] text-ink-3">
      <span>{t("home.footerPrivacy")}</span>
      <span>{t("app.version", { version: __APP_VERSION__ })}</span>
    </footer>
  );
}
