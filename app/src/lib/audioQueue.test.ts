import { describe, expect, it } from "vitest";
import { AudioQueue, type Clip, type Player } from "./audioQueue";

function fakePlayer() {
  const played: number[] = [];
  const resolvers: (() => void)[] = [];
  const player: Player = {
    play(clip: Clip) {
      played.push(clip.seq);
      return new Promise<void>((r) => resolvers.push(r));
    },
    stop() {
      resolvers.splice(0).forEach((r) => r());
    },
  };
  const finishOne = async () => {
    resolvers.shift()?.();
    await new Promise((r) => setTimeout(r, 0));
  };
  return { player, played, finishOne };
}

const clip = (seq: number): Clip => ({ seq, mime: "audio/mpeg", b64: "" });

describe("AudioQueue", () => {
  it("plays in seq order even when clips arrive out of order", async () => {
    const f = fakePlayer();
    const states: boolean[] = [];
    const q = new AudioQueue(f.player, (p) => states.push(p));
    q.push(clip(1));
    expect(f.played).toEqual([]); // waits for seq 0
    q.push(clip(0));
    expect(f.played).toEqual([0]);
    await f.finishOne();
    expect(f.played).toEqual([0, 1]);
    await f.finishOne();
    expect(q.isPlaying).toBe(false);
    expect(states).toEqual([true, false]);
  });

  it("reset drops the previous answer", async () => {
    const f = fakePlayer();
    const q = new AudioQueue(f.player);
    q.push(clip(0));
    q.push(clip(1));
    q.reset();
    await f.finishOne();
    expect(f.played).toEqual([0]);
    q.push(clip(0));
    expect(f.played).toEqual([0, 0]);
  });
});
