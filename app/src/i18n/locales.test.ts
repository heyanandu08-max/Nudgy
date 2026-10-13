import { describe, expect, it } from "vitest";
import { resources } from "./index";

type Tree = { [k: string]: unknown };

/** Leaf paths; plural forms (_one/_other) count as one key. */
function keys(node: unknown, prefix = ""): string[] {
  if (Array.isArray(node)) {
    // Arrays of objects (home chips) must keep their shape; string arrays (praise) may differ in length.
    return node.every((x) => typeof x === "string") ? [prefix] : node.flatMap((x, i) => keys(x, `${prefix}[${i}]`));
  }
  if (node && typeof node === "object") {
    return Object.entries(node as Tree).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
  }
  return [prefix.replace(/_(zero|one|two|few|many|other)$/, "")];
}

function strings(node: unknown): string[] {
  if (typeof node === "string") return [node];
  if (Array.isArray(node)) return node.flatMap(strings);
  if (node && typeof node === "object") return Object.values(node as Tree).flatMap(strings);
  return [];
}

const placeholders = (s: string) => [...s.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort();

const en = resources.en.translation;
const enKeys = new Set(keys(en));

describe.each(Object.entries(resources).filter(([code]) => code !== "en"))("%s translation", (_code, { translation }) => {
  it("has exactly the English keys", () => {
    expect(new Set(keys(translation))).toEqual(enKeys);
  });

  it("keeps every placeholder", () => {
    const flat = (node: unknown, prefix = ""): [string, string][] =>
      typeof node === "string"
        ? [[prefix, node]]
        : node && typeof node === "object"
          ? Object.entries(node as Tree).flatMap(([k, v]) => flat(v, prefix ? `${prefix}.${k}` : k))
          : [];
    const enFlat = new Map(flat(en));
    for (const [path, text] of flat(translation)) {
      const source = enFlat.get(path);
      if (source !== undefined) expect(placeholders(text), path).toEqual(placeholders(source));
    }
  });

  it("follows the copy rules (no exclamation marks)", () => {
    for (const s of strings(translation)) expect(s, s).not.toMatch(/[!¡]/);
  });
});
