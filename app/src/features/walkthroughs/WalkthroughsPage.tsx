import { useCallback, useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { errorCode, errorKey } from "../../lib/errors";
import { hideMainWindow, playWalkthrough } from "../tutor/host";

interface Row {
  id: string;
  title: string;
  app: string;
  steps: number;
  share_url: string | null;
  created_at: number;
}

interface Step {
  instruction: string;
  note: string | null;
  screenshot: string | null;
}

interface Doc {
  id: string;
  title: string;
  steps: Step[];
}

export function WalkthroughsPage() {
  const { t, i18n } = useTranslation();
  const [rows, setRows] = useState<Row[]>([]);
  const [link, setLink] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [withShots, setWithShots] = useState(false);
  const [toTeam, setToTeam] = useState(false);
  const [open, setOpen] = useState<Doc | null>(null);

  const refresh = useCallback(() => {
    if (isTauri()) invoke<Row[]>("walkthrough_list").then(setRows).catch(() => setRows([]));
  }, []);

  useEffect(() => {
    refresh();
    if (!isTauri()) return;
    const off = listen("walkthroughs-changed", refresh);
    return () => void off.then((f) => f());
  }, [refresh]);

  const fail = (e: unknown) => setStatus(t(errorKey(errorCode(e)), { defaultValue: String(e) }));

  const record = async () => {
    setStatus(null);
    hideMainWindow();
    await invoke("recorder_start").catch(fail);
  };

  const importFile = async () => {
    try {
      const w = await invoke<Doc | null>("walkthrough_import_file");
      if (w) setStatus(t("walkthroughs.imported", { title: w.title }));
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  const importLink = async () => {
    try {
      const w = await invoke<Doc>("walkthrough_fetch", { link });
      setLink("");
      setStatus(t("walkthroughs.imported", { title: w.title }));
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  const share = async (r: Row) => {
    try {
      const url = await invoke<string>("walkthrough_share", { id: r.id, includeScreenshots: withShots, team: toTeam });
      await navigator.clipboard?.writeText(url).catch(() => {});
      setStatus(t("walkthroughs.shared", { url }));
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  const exportFile = async (r: Row) => {
    try {
      if (await invoke<boolean>("walkthrough_export", { id: r.id, includeScreenshots: withShots })) {
        setStatus(t("walkthroughs.exported"));
      }
    } catch (e) {
      fail(e);
    }
  };

  const remove = async (r: Row) => {
    if (!window.confirm(t("walkthroughs.confirmDelete", { title: r.title }))) return;
    await invoke("walkthrough_delete", { id: r.id }).catch(fail);
    if (open?.id === r.id) setOpen(null);
    refresh();
  };

  const toggle = async (r: Row) => {
    if (open?.id === r.id) return setOpen(null);
    setOpen(await invoke<Doc>("walkthrough_get", { id: r.id }).catch(() => null));
  };

  const date = (s: number) => new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" }).format(new Date(s * 1000));
  const btn = "rounded-md border border-slate-300 px-3 py-1 text-sm hover:border-nudgy-500 dark:border-slate-600";

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-6">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold">{t("walkthroughs.title")}</h1>
        <p className="text-sm text-slate-500">{t("walkthroughs.help")}</p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={record} className="rounded-md bg-nudgy-500 px-4 py-2 text-sm font-medium text-white hover:bg-nudgy-600">
          ● {t("walkthroughs.record")}
        </button>
        <button type="button" onClick={importFile} className={btn}>
          {t("walkthroughs.importFile")}
        </button>
        <form
          className="flex flex-1 gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void importLink();
          }}
        >
          <input
            className="min-w-0 flex-1 rounded-md border border-slate-300 bg-transparent px-3 py-1 text-sm dark:border-slate-600"
            placeholder={t("walkthroughs.linkPlaceholder")}
            value={link}
            onChange={(e) => setLink(e.target.value)}
          />
          <button type="submit" disabled={!link.trim()} className={`${btn} disabled:opacity-50`}>
            {t("walkthroughs.importLink")}
          </button>
        </form>
      </div>

      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={withShots} onChange={(e) => setWithShots(e.target.checked)} />
        <span>
          {t("walkthroughs.includeScreenshots")}
          <span className="block text-xs text-slate-500">{t("walkthroughs.screenshotsHelp")}</span>
        </span>
      </label>

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={toTeam} onChange={(e) => setToTeam(e.target.checked)} />
        {t("walkthroughs.shareTeam")}
      </label>

      {status && (
        <p role="status" className="break-all rounded-md bg-nudgy-50 px-3 py-2 text-sm text-nudgy-600">
          {status}
        </p>
      )}

      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">{t("walkthroughs.empty")}</p>
      ) : (
        <ul className="space-y-3">
          {rows.map((r) => (
            <li key={r.id} className="rounded-xl border border-slate-200 p-4 dark:border-slate-700">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <p className="font-medium">{r.title}</p>
                  <p className="text-xs text-slate-500">
                    {[r.app, t("walkthroughs.steps", { count: r.steps }), date(r.created_at)].filter(Boolean).join(" · ")}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => void playWalkthrough(r.id)} className="rounded-md bg-nudgy-500 px-3 py-1 text-sm text-white">
                    ▶ {t("walkthroughs.play")}
                  </button>
                  <button type="button" onClick={() => void exportFile(r)} className={btn}>
                    {t("walkthroughs.export")}
                  </button>
                  <button type="button" onClick={() => void share(r)} className={btn}>
                    {t("walkthroughs.share")}
                  </button>
                  <button type="button" onClick={() => void remove(r)} className={`${btn} text-red-600`}>
                    {t("walkthroughs.delete")}
                  </button>
                </div>
              </div>
              {r.share_url && <p className="mt-1 break-all text-xs text-slate-500">{r.share_url}</p>}
              <button type="button" onClick={() => void toggle(r)} className="mt-2 text-xs underline underline-offset-2">
                {open?.id === r.id ? t("walkthroughs.hideSteps") : t("walkthroughs.showSteps")}
              </button>
              {open?.id === r.id && (
                <ol className="mt-3 space-y-3">
                  {open.steps.map((s, i) => (
                    <li key={i} className="flex gap-3 text-sm">
                      <span className="w-5 shrink-0 text-right text-slate-500">{i + 1}.</span>
                      <div className="min-w-0 flex-1">
                        <p>{s.instruction}</p>
                        {s.note && <p className="text-xs text-slate-500">“{s.note}”</p>}
                        {s.screenshot && <img src={s.screenshot} alt="" className="mt-2 max-h-40 rounded border border-slate-200" />}
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
