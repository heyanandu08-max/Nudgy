/** Maps backend / client error codes to i18n keys under `errors.*`. */
export function errorKey(code: string | undefined): string {
  if (!code) return "errors.generic";
  const exact = [
    "no_speech",
    "no_microphone",
    "backend_unreachable",
    "backend_error",
    "auth_required",
    "limit_reached",
    "llm_refused",
    "internal",
  ];
  if (exact.includes(code)) return `errors.${code}`;
  for (const prefix of ["stt", "llm", "tts"]) {
    if (code.startsWith(prefix)) return `errors.${prefix}`;
  }
  return "errors.generic";
}
