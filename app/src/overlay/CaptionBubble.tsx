import { useTranslation } from "react-i18next";
import type { Caption } from "./store";

export function CaptionBubble({ caption }: { caption: Caption }) {
  const { t } = useTranslation();
  const notice = caption.noticeKey ? t(caption.noticeKey, { defaultValue: caption.noticeFallback ?? "" }) : null;
  return (
    <div className="caption" role="status" aria-live="polite">
      {caption.transcript && (
        <p className="caption__you">
          <span className="caption__label">{t("caption.you")}:</span> {caption.transcript}
        </p>
      )}
      {caption.speech && <p className="caption__speech">{caption.speech}</p>}
      {notice && <p className="caption__notice">{notice}</p>}
    </div>
  );
}
