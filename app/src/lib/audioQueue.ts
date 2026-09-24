/** Plays per-sentence audio clips strictly in `seq` order, even if they arrive out of order. */

export interface Clip {
  seq: number;
  mime: string;
  b64: string;
  /** The sentence this clip says (always sent; spoken locally for device voice). */
  text?: string;
}

/** Server TTS "device": no audio bytes, the OS voice reads `text` instead. */
export const DEVICE_SPEECH_MIME = "text/x-device-speech";

export interface Player {
  play(clip: Clip): Promise<void>; // resolves when the clip finished (or failed)
  stop(): void;
}

export class AudioQueue {
  private pending = new Map<number, Clip>();
  private next = 0;
  private playing = false;
  private generation = 0;

  constructor(
    private player: Player,
    private onPlayingChange: (playing: boolean) => void = () => {},
  ) {}

  /** Starts a new answer: drops anything queued or playing from the previous one. */
  reset(): void {
    this.generation++;
    this.pending.clear();
    this.next = 0;
    if (this.playing) {
      this.player.stop();
      this.setPlaying(false);
    }
  }

  push(clip: Clip): void {
    if (clip.seq < this.next) return;
    this.pending.set(clip.seq, clip);
    void this.drain();
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  private setPlaying(p: boolean) {
    if (this.playing !== p) {
      this.playing = p;
      this.onPlayingChange(p);
    }
  }

  private async drain(): Promise<void> {
    if (this.playing) return;
    const gen = this.generation;
    while (this.pending.has(this.next) && gen === this.generation) {
      const clip = this.pending.get(this.next)!;
      this.pending.delete(this.next);
      this.next++;
      this.setPlaying(true);
      await this.player.play(clip);
    }
    if (gen === this.generation) this.setPlaying(false);
  }
}

/** Device voices (Windows / macOS speech), picked by name; the OS default if unset/missing. */
export function deviceVoices(): SpeechSynthesisVoice[] {
  return typeof speechSynthesis === "undefined" ? [] : speechSynthesis.getVoices();
}

/** Longest a sentence may take before we stop waiting for the engine's end event. */
const speechTimeoutMs = (text: string) => 3000 + text.length * 120;

/** Browser implementation: <audio> for server clips, speechSynthesis for device voice. */
export function htmlAudioPlayer(): Player & { setVoice(name: string | null): void } {
  let current: HTMLAudioElement | null = null;
  let finish: (() => void) | null = null;
  let voiceName: string | null = null;

  const speak = (clip: Clip) =>
    new Promise<void>((resolve) => {
      const text = clip.text?.trim();
      if (!text || typeof speechSynthesis === "undefined") return resolve(); // captions only
      const u = new SpeechSynthesisUtterance(text);
      const voice = voiceName ? deviceVoices().find((v) => v.name === voiceName) : undefined;
      if (voice) {
        u.voice = voice;
        u.lang = voice.lang;
      }
      const timer = setTimeout(() => finish?.(), speechTimeoutMs(text));
      finish = () => {
        clearTimeout(timer);
        finish = null;
        resolve();
      };
      u.onend = () => finish?.();
      u.onerror = () => finish?.();
      speechSynthesis.speak(u);
    });

  return {
    setVoice(name) {
      voiceName = name;
    },
    play(clip) {
      if (clip.mime === DEVICE_SPEECH_MIME) return speak(clip);
      return new Promise<void>((resolve) => {
        const bytes = Uint8Array.from(atob(clip.b64), (c) => c.charCodeAt(0));
        const url = URL.createObjectURL(new Blob([bytes], { type: clip.mime }));
        const audio = new Audio(url);
        current = audio;
        finish = () => {
          URL.revokeObjectURL(url);
          current = null;
          finish = null;
          resolve();
        };
        audio.onended = finish;
        audio.onerror = finish;
        audio.play().catch(finish);
      });
    },
    stop() {
      current?.pause();
      if (typeof speechSynthesis !== "undefined") speechSynthesis.cancel();
      finish?.();
    },
  };
}
