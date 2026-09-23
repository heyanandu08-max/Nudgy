import { useTranslation } from "react-i18next";
import type { Health } from "./useHealth";

const DOT: Record<Health["state"], string> = {
  checking: "bg-amber-400",
  ok: "bg-emerald-500",
  down: "bg-red-500",
};

export function HealthBadge({ health, onRetry }: { health: Health; onRetry: () => void }) {
  const { t } = useTranslation();
  const text =
    health.state === "ok"
      ? t("health.ok", { version: health.version })
      : health.state === "down"
        ? t("health.down")
        : t("health.checking");

  return (
    <div className="flex items-center gap-2 text-sm" role="status" data-health={health.state}>
      <span className={`h-2.5 w-2.5 rounded-full ${DOT[health.state]}`} aria-hidden />
      <span className="font-medium">{t("health.label")}:</span>
      <span>{text}</span>
      {health.state === "down" && (
        <button type="button" onClick={onRetry} className="ml-1 underline underline-offset-2">
          {t("health.retry")}
        </button>
      )}
    </div>
  );
}
