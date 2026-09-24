import { useTranslation } from "react-i18next";
import { SettingsHeading } from "./parts";

/** Filled in by Phase 8 (what is sent, to whom; delete my data). */
export function PrivacySection() {
  const { t } = useTranslation();
  return <SettingsHeading before={t("settings.sections.privacy")} em="" sub={t("home.footerPrivacy")} />;
}
