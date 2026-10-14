import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { useTranslation } from "react-i18next";

export type LegalPage = "privacy" | "terms" | "cookies" | "delete-account" | "licenses";

/** Mirrors GET /v1/legal. */
export interface LegalInfo {
  company: string;
  address: string;
  contact_email: string;
  terms_version: string;
}

export const openLegal = (page: LegalPage) => void invoke("open_legal", { page }).catch(() => {});

/** A link-styled button that opens a legal page in the browser. */
export function LegalLink({ page, children }: { page: LegalPage; children?: React.ReactNode }) {
  const { t } = useTranslation();
  return (
    <button type="button" onClick={() => openLegal(page)} className="underline underline-offset-2 hover:text-ink">
      {children ?? t(`legal.pages.${page}`)}
    </button>
  );
}

export function useLegalInfo(): LegalInfo | null {
  const [info, setInfo] = useState<LegalInfo | null>(null);
  useEffect(() => {
    if (isTauri())
      invoke<LegalInfo>("legal_info")
        .then(setInfo)
        .catch(() => setInfo(null));
  }, []);
  return info;
}
