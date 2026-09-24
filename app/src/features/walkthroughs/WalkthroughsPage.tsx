import { useCallback, useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { errorCode, errorKey } from "../../lib/errors";
import { AppBadge } from "../../components/ui";
import { startRecording } from "../home/HomePage";
import { playWalkthrough } from "../tutor/host";

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
    await startRecording().catch(fail);
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
  const btn = "rounded-btn border border-line-2 bg-white px-3 py-1.5 text-[13px] hover:border-ink-3";

  return (
    <div className="space-y-5 px-14 pt-11 pb-10">
      <header>
        <h1 className="text-[40px] leading-[1.1] font-semibold tracking-[-.02em]">
          {t("walkthroughs.titleBefore")}
          <em className="font-serif font-medium">{t("walkthroughs.titleEm")}</em>
        </h1>
        <p className="mt-2 text-[13px] text-ink-2">{t("walkthroughs.help")}</p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={record} className="inline-flex items-center gap-2 rounded-btn bg-ink px-4 py-2 text-[13px] font-medium text-white hover:bg-black">
          <span aria-hidden className="h-2 w-2 rounded-full bg-accent" /> {t("walkthroughs.record")}
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
            className="min-w-0 flex-1 rounded-btn border border-line-2 bg-transparent px-3 py-1 text-sm"
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
          <span className="block text-xs text-ink-3">{t("walkthroughs.screenshotsHelp")}</span>
        </span>
      </label>

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={toTeam} onChange={(e) => setToTeam(e.target.checked)} />
        {t("walkthroughs.shareTeam")}
      </label>

      {status && (
        <p role="status" className="break-all rounded-btn border border-line bg-paper px-3 py-2 font-mono text-xs text-ink-2">
          {status}
        </p>
      )}

      {rows.length === 0 ? (
        <p className="rounded-card border border-dashed border-line-2 bg-paper p-4 text-[13px] text-ink-2">{t("walkthroughs.empty")}</p>
      ) : (
        <ul className="overflow-hidden rounded-card border border-line-2 bg-white">
          {rows.map((r) => (
            <li key={r.id} className="border-b border-line px-4 py-3.5 last:border-b-0">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <AppBadge app={r.app || "?"} />
                <div className="mr-auto min-w-0">
                  <p className="text-[13.5px] font-medium">{r.title}</p>
                  <p className="mt-0.5 font-mono text-[11px] text-ink-3">
                    {[r.app, t("walkthroughs.steps", { count: r.steps }), date(r.created_at)].filter(Boolean).join(" · ")}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => void playWalkthrough(r.id)} className="rounded-btn bg-ink px-3 py-1.5 text-[13px] font-medium text-white hover:bg-black">
                    {t("walkthroughs.play")}
                  </button>
                  <button type="button" onClick={() => void exportFile(r)} className={btn}>
                    {t("walkthroughs.export")}
                  </button>
                  <button type="button" onClick={() => void share(r)} className={btn}>
                    {t("walkthroughs.share")}
                  </button>
                  <button type="button" onClick={() => void remove(r)} className={`${btn} text-accent`}>
                    {t("walkthroughs.delete")}
                  </button>
                </div>
              </div>
              {r.share_url && <p className="mt-1 break-all text-xs text-ink-3">{r.share_url}</p>}
              <button type="button" onClick={() => void toggle(r)} className="mt-2 text-xs underline underline-offset-2">
                {open?.id === r.id ? t("walkthroughs.hideSteps") : t("walkthroughs.showSteps")}
              </button>
              {open?.id === r.id && (
                <ol className="mt-3 space-y-3">
                  {open.steps.map((s, i) => (
                    <li key={i} className="flex gap-3 text-sm">
                      <span className="w-5 shrink-0 text-right text-ink-3">{i + 1}.</span>
                      <div className="min-w-0 flex-1">
                        <p>{s.instruction}</p>
                        {s.note && <p className="text-xs text-ink-3">“{s.note}”</p>}
                        {s.screenshot && <img src={s.screenshot} alt="" className="mt-2 max-h-40 rounded border border-line-2" />}
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
