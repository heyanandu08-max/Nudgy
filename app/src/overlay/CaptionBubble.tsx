import { useTranslation } from "react-i18next";
import type { Caption } from "./store";

/** Black caption bubble: small mono "NUDGY" header, then what Nudgy says. */
export function CaptionBubble({ caption }: { caption: Caption }) {
  const { t } = useTranslation();
  const notice = caption.noticeKey ? t(caption.noticeKey, { defaultValue: caption.noticeFallback ?? "" }) : null;
  const body = caption.speech || (!notice ? caption.transcript : "");
  if (!body && !notice) return null;
  return (
    <div className="bubble" role="status" aria-live="polite">
      <small>{t("caption.label")}</small>
      {body && <p className={caption.speech ? "" : "bubble__heard"}>{body}</p>}
      {notice && <p className="bubble__notice">{notice}</p>}
    </div>
  );
}
