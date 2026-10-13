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
    "empty_recording",
    "bad_link",
    "not_found",
    "input_permission",
    "auth_expired",
    "no_seats",
    "billing_error",
    "config",
    "no_team",
    "no_screen_permission",
  ];
  if (exact.includes(code)) return `errors.${code}`;
  for (const prefix of ["stt", "llm", "tts"]) {
    if (code.startsWith(prefix)) return `errors.${prefix}`;
  }
  return "errors.generic";
}

/** Tauri command errors arrive as `{code, message}` objects or plain strings. */
export function errorCode(e: unknown): string | undefined {
  if (e && typeof e === "object" && "code" in e) return String((e as { code: unknown }).code);
  return undefined;
}
