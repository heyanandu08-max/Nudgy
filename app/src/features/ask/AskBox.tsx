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
      className="flex h-full items-center gap-3 rounded-card border-[1.5px] border-ink bg-white px-4 text-ink"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <span aria-hidden className="font-mono text-[11px] text-ink-3 uppercase">{mode === "note" ? "note" : "ask"}</span>
      <input
        ref={input}
        aria-label={t("askBox.label")}
        className="w-full bg-transparent text-base outline-none placeholder:text-ink-3"
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
