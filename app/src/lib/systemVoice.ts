/** The computer's own voice (Web Speech API in the webview: Windows and macOS voices). Used
 *  when the server runs Nudgy's built-in AI, which sends text but no audio. */

export function systemVoiceAvailable(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/** Reads `text` aloud. `onEnd` runs when it finishes or is cancelled. */
export function speakText(text: string, lang: string, rate: number, onStart: () => void, onEnd: () => void): void {
  if (!systemVoiceAvailable() || !text.trim()) return onEnd();
  const synth = window.speechSynthesis;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang;
  u.rate = rate;
  // Prefer a voice for the user's language when the system has one.
  const voice = synth.getVoices().find((v) => v.lang.toLowerCase().startsWith(lang.toLowerCase()));
  if (voice) u.voice = voice;
  u.onstart = onStart;
  u.onend = onEnd;
  u.onerror = onEnd;
  synth.speak(u);
}

export function stopSpeaking(): void {
  if (systemVoiceAvailable()) window.speechSynthesis.cancel();
}
