import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";

/** The small text box opened by double-tapping the hotkey. */
export function AskBox() {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"ask" | "note">("ask");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.body.classList.add("ask-box");
    input.current?.focus();
    const off = listen<"ask" | "note">("ask-box-open", (e) => {
      setMode(e.payload ?? "ask");
      setText("");
      input.current?.focus();
    });
    return () => {
      off.then((f) => f());
    };
  }, []);

  const submit = async () => {
    const q = text.trim();
    setText("");
    if (mode === "note") {
      if (q) await invoke("recorder_note", { text: q });
      await invoke("cancel_text_ask"); // just hides the box
    } else {
      await invoke("ask_text", { text: q });
    }
  };

  return (
    <form
      className="flex h-full items-center gap-2 rounded-xl bg-slate-900 px-4 text-slate-50"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <span aria-hidden className="h-3 w-3 shrink-0 rounded-full bg-nudgy-500" />
      <input
        ref={input}
        aria-label={t("askBox.label")}
        className="w-full bg-transparent text-base outline-none placeholder:text-slate-400"
        placeholder={mode === "note" ? t("askBox.notePlaceholder") : t("askBox.placeholder")}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") void invoke("cancel_text_ask");
        }}
      />
    </form>
  );
}
