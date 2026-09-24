/** Plays per-sentence audio clips strictly in `seq` order, even if they arrive out of order. */

export interface Clip {
  seq: number;
  mime: string;
  b64: string;
}

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

/** Browser implementation backed by an <audio> element. */
export function htmlAudioPlayer(): Player {
  let current: HTMLAudioElement | null = null;
  let finish: (() => void) | null = null;
  return {
    play(clip) {
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
      finish?.();
    },
  };
}
