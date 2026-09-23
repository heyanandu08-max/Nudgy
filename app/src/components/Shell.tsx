import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export interface Tab {
  id: string;
  labelKey: string;
  render: () => ReactNode;
}

export function Shell({ tabs, active, onChange }: { tabs: Tab[]; active: string; onChange: (id: string) => void }) {
  const { t } = useTranslation();
  const current = tabs.find((x) => x.id === active) ?? tabs[0];
  return (
    <div className="flex h-full flex-col">
      <nav className="flex gap-1 border-b border-slate-200 px-4 pt-3 dark:border-slate-700" role="tablist">
        <span className="mr-3 self-center font-semibold text-nudgy-600">{t("app.name")}</span>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={tab.id === current.id}
            onClick={() => onChange(tab.id)}
            className={`rounded-t-md px-3 py-2 text-sm ${
              tab.id === current.id
                ? "border-b-2 border-nudgy-500 font-medium"
                : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
            }`}
          >
            {t(tab.labelKey)}
          </button>
        ))}
      </nav>
      <main className="flex-1 overflow-auto">{current.render()}</main>
    </div>
  );
}
