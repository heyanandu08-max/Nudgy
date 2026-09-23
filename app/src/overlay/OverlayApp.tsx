import { useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { emit } from "@tauri-apps/api/event";
import type { TutorView } from "../features/tutor/types";
import { AudioQueue, htmlAudioPlayer, type Clip } from "../lib/audioQueue";
import { errorKey } from "../lib/errors";
import { follow, type Vec } from "../lib/motion";
import type { Settings } from "../lib/settings";
import { CaptionBubble } from "./CaptionBubble";
import { LessonPanel } from "./LessonPanel";
import { RecorderBar } from "./RecorderBar";
import { ReviewNudge, type Nudge } from "./ReviewNudge";
import { Companion } from "./Companion";
import { Pointer } from "./Pointer";
import { useOverlay, type CompanionMode, type Rect } from "./store";

const ACTIVE_PHASES = ["planning", "instructing", "waiting", "verifying"];
/** Cursor positions are re-sent every 500 ms, so one second always includes one. */
const CLAIM_WINDOW_MS = 1000;

/** Where the companion sits relative to the cursor (CSS px). */
const OFFSET = { x: 22, y: 22 };
/** Caption lingers this long after the answer finished (and audio stopped). */
const CAPTION_LINGER_MS = 6000;
/** Flip the caption to the left of the companion when this close to the right edge. */
const CAPTION_FLIP_PX = 360;
/** …and above it when this close to the bottom edge. */
const CAPTION_FLIP_Y_PX = 200;

interface PointPayload {
  rect: Rect;
  actionHint: string | null;
  highlight: boolean;
}

export function OverlayApp() {
  const s = useOverlay();
  const companion = useRef<HTMLDivElement>(null);
  const cursor = useRef<Vec>({ x: -100, y: -100 });
  const pos = useRef<Vec>({ x: -100, y: -100 });
  const [pointerFrom, setPointerFrom] = useState<Vec>({ x: 0, y: 0 });
  const audio = useRef<AudioQueue | null>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const answerDone = useRef(false);
  const [lesson, setLesson] = useState<TutorView | null>(null);
  /** Whether this monitor shows the lesson panel (the one under the cursor at start). */
  const [ownsLesson, setOwnsLesson] = useState(false);
  const lessonRef = useRef<TutorView | null>(null);
  /** A lesson started before this overlay heard where the cursor is: claim on first sight. */
  const claimUntil = useRef(0);
  const [nudge, setNudge] = useState<Nudge | null>(null);
  const [recording, setRecording] = useState<{ recording: boolean; steps: number }>({ recording: false, steps: 0 });

  useEffect(() => {
    const st = useOverlay.getState;
    const scheduleHide = () => {
      clearTimeout(hideTimer.current);
      if (!answerDone.current || audio.current?.isPlaying) return;
      st().finishCaption();
      if (st().mode === "talking" || st().mode === "thinking") st().setMode("idle");
      hideTimer.current = setTimeout(() => st().clearCaption(), CAPTION_LINGER_MS);
    };
    audio.current = new AudioQueue(htmlAudioPlayer(), (playing) => {
      if (playing) st().setMode("talking");
      else scheduleHide();
    });

    const subs = [
      listen<Vec>("cursor", (e) => {
        cursor.current = e.payload;
        st().setActive(true);
        if (claimUntil.current > Date.now()) {
          claimUntil.current = 0;
          setOwnsLesson(true);
        }
      }),
      listen("cursor-left", () => st().setActive(false)),
      listen<CompanionMode>("companion-state", (e) => {
        st().setMode(e.payload);
        if (e.payload === "listening") {
          clearTimeout(hideTimer.current);
          audio.current?.reset();
          st().clearCaption();
        }
      }),
      listen<PointPayload>("point", (e) => {
        setPointerFrom({ ...pos.current });
        st().pointAt(e.payload);
      }),
      listen<{ text: string }>("ask-transcript", (e) => {
        answerDone.current = false;
        clearTimeout(hideTimer.current);
        audio.current?.reset();
        st().startCaption(e.payload.text);
      }),
      listen<{ delta: string }>("ask-speech", (e) => {
        st().appendSpeech(e.payload.delta);
        if (st().mode === "thinking") st().setMode("talking");
      }),
      listen<Clip>("ask-audio", (e) => audio.current?.push(e.payload)),
      listen("ask-done", () => {
        answerDone.current = true;
        scheduleHide();
      }),
      listen<{ code?: string; message?: string; fatal?: boolean }>("ask-error", (e) => {
        st().setNotice(errorKey(e.payload.code), e.payload.message ?? null);
        if (e.payload.fatal !== false) {
          answerDone.current = true;
          scheduleHide();
        }
      }),
      listen("ask-notice", () => st().setNotice("caption.withheld")),
      listen<Settings>("settings-changed", (e) => st().setPaused(e.payload.paused)),
      listen<{ text: string; clips: Clip[] }>("lesson-say", (e) => {
        answerDone.current = false;
        clearTimeout(hideTimer.current);
        audio.current?.reset();
        st().startCaption("");
        st().appendSpeech(e.payload.text);
        e.payload.clips.forEach((c) => audio.current?.push(c));
        answerDone.current = true;
        if (!e.payload.clips.length) scheduleHide();
      }),
      listen<Nudge>("review-nudge", (e) => setNudge(e.payload)),
      listen<{ recording: boolean; steps: number }>("recorder-state", (e) => setRecording(e.payload)),
      listen<TutorView>("lesson-state", (e) => {
        const v = e.payload;
        const wasActive = !!lessonRef.current && ACTIVE_PHASES.includes(lessonRef.current.phase);
        lessonRef.current = v;
        setLesson(v);
        // Claim the panel when a lesson (or review) starts, or on reload mid-lesson.
        if (!wasActive && ACTIVE_PHASES.includes(v.phase)) {
          setOwnsLesson(st().active);
          if (!st().active) claimUntil.current = Date.now() + CLAIM_WINDOW_MS;
        }
        if (v.phase === "idle") setOwnsLesson(false);
      }),
    ];
    void emit("lesson-state-request");
    return () => {
      subs.forEach((p) => p.then((off) => off()));
      audio.current?.reset();
      clearTimeout(hideTimer.current);
    };
  }, []);

  // Companion follows the cursor with a slight, frame-rate independent lag.
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = now - last;
      last = now;
      const goal = { x: cursor.current.x + OFFSET.x, y: cursor.current.y + OFFSET.y };
      pos.current = follow(pos.current, goal, dt);
      const el = companion.current;
      if (el) {
        el.style.transform = `translate(${pos.current.x}px, ${pos.current.y}px)`;
        el.dataset.flip = pos.current.x > window.innerWidth - CAPTION_FLIP_PX ? "left" : "right";
        el.dataset.flipY = pos.current.y > window.innerHeight - CAPTION_FLIP_Y_PX ? "up" : "down";
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const showPanel = ownsLesson && !!lesson && lesson.phase !== "idle" && !s.paused;
  useEffect(() => {
    if (lesson?.phase !== "finished" && lesson?.phase !== "failed") return;
    const id = setTimeout(() => setOwnsLesson(false), CAPTION_LINGER_MS);
    return () => clearTimeout(id);
  }, [lesson?.phase]);

  const shownMode: CompanionMode = s.target ? "pointing" : s.mode;
  const visible = s.active && !s.paused;

  return (
    <div className="overlay-root">
      <div ref={companion} className={`companion-anchor ${visible ? "" : "companion-anchor--hidden"}`}>
        <Companion mode={shownMode} />
        {s.caption && <CaptionBubble caption={s.caption} />}
      </div>
      {showPanel && lesson && <LessonPanel view={lesson} />}
      {recording.recording && s.active && <RecorderBar steps={recording.steps} />}
      {nudge && !s.paused && !showPanel && <ReviewNudge nudge={nudge} onClose={() => setNudge(null)} />}
      {s.target && !s.paused && (
        <Pointer key={s.target.seq} target={s.target} from={pointerFrom} onDone={s.clearTarget} />
      )}
    </div>
  );
}
