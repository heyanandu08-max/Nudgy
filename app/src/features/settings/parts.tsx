import type { ReactNode } from "react";

/** Screen heading: "Your *cursor*" + one-line subtitle. */
export function SettingsHeading({ before, em, sub }: { before: string; em: string; sub: string }) {
  return (
    <>
      <h2 className="text-2xl font-semibold tracking-[-.01em]">
        {before} <em className="font-serif font-medium">{em}</em>
      </h2>
      <p className="mt-1.5 text-[13px] text-ink-2">{sub}</p>
    </>
  );
}

export function Card({ children }: { children: ReactNode }) {
  return <div className="mt-5.5 rounded-card border border-line-2 bg-white">{children}</div>;
}

export function Row({ title, help, children, htmlFor }: { title: string; help?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex items-center gap-4 border-b border-line px-[18px] py-4 last:border-b-0">
      <div className="min-w-0">
        <label htmlFor={htmlFor} className="block text-[13.5px] font-medium">
          {title}
        </label>
        {help && <p className="mt-0.5 text-xs text-ink-3">{help}</p>}
      </div>
      <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5">{children}</div>
    </div>
  );
}
