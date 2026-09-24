import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import type { TutorView } from "../features/tutor/types";
import { AudioQueue, htmlAudioPlayer, type Clip } from "../lib/audioQueue";
import { errorKey } from "../lib/errors";
import { follow, type Vec } from "../lib/motion";
import { DEFAULT_SETTINGS, type Settings } from "../lib/settings";
import { CaptionBubble } from "./CaptionBubble";
import { LessonCard } from "./LessonCard";
import { NudgyCursor, StateLabel, type CursorLabel } from "./NudgyCursor";
import { Pointer } from "./Pointer";
import { RecorderBar } from "./RecorderBar";
import { ReviewNudge, type Nudge } from "./ReviewNudge";
import { StatusPill, type PillState } from "./StatusPill";
import { useOverlay, type CompanionMode, type Rect } from "./store";

const ACTIVE_PHASES = ["planning", "waiting_app", "instructing", "waiting", "verifying"];
/** Cursor positions are re-sent every 500 ms, so one second always includes one. */
const CLAIM_WINDOW_MS = 1000;
/** Where the Nudgy cursor trails relative to the real one (CSS px). */
const OFFSET = { x: 16, y: 14 };
/** Caption lingers this long after the answer finished (and audio stopped). */
const CAPTION_LINGER_MS = 6000;
/** An idle Nudgy cursor fades away after this long without mouse movement. */
const IDLE_FADE_MS = 5000;
const NICE_MS = 1400;
/** Minimum time the "looking at your screen" tag is shown. */
const LOOKING_MIN_MS = 1200;
const FLIP_X = 340;
const FLIP_Y = 200;

interface PointPayload {
  rect: Rect;
  actionHint: string | null;
  highlight: boolean;
}

export function OverlayApp() {
  const { t } = useTranslation();
  const s = useOverlay();
  const anchor = useRef<HTMLDivElement>(null);
  const cursor = useRef<Vec>({ x: -100, y: -100 });
  const pos = useRef<Vec>({ x: -100, y: -100 });
  const lastMove = useRef(performance.now());
  const [idle, setIdle] = useState(false);
  const [pointerFrom, setPointerFrom] = useState<Vec>({ x: 0, y: 0 });
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [speaking, setSpeaking] = useState(false);
  const audio = useRef<AudioQueue | null>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const answerDone = useRef(false);
  const [lesson, setLesson] = useState<TutorView | null>(null);
  const [ownsLesson, setOwnsLesson] = useState(false);
  const lessonRef = useRef<TutorView | null>(null);
  const claimUntil = useRef(0);
  const [nice, setNice] = useState(false);
  const [nudge, setNudge] = useState<Nudge | null>(null);
  const [recording, setRecording] = useState({ recording: false, steps: 0 });
  const [looking, setLooking] = useState(false);
  const lookingSince = useRef(0);
  const lookingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    const st = useOverlay.getState;
    void invoke<Settings>("get_settings").then((v) => {
      setSettings(v);
      st().setPaused(v.paused);
    });

    const scheduleHide = () => {
      clearTimeout(hideTimer.current);
      if (!answerDone.current || audio.current?.isPlaying) return;
      st().finishCaption();
      if (st().mode === "talking" || st().mode === "thinking") st().setMode("idle");
      hideTimer.current = setTimeout(() => st().clearCaption(), CAPTION_LINGER_MS);
    };
    audio.current = new AudioQueue(htmlAudioPlayer(), (playing) => {
      setSpeaking(playing);
      void invoke("escape_listen", { on: playing }).catch(() => {});
      if (playing) st().setMode("talking");
      else scheduleHide();
    });
    const stopTalking = () => {
      audio.current?.reset();
      answerDone.current = true;
      st().clearCaption();
      st().setMode("idle");
      void invoke("escape_listen", { on: false }).catch(() => {});
    };

    const subs = [
      listen<Vec>("cursor", (e) => {
        const moved = Math.abs(e.payload.x - cursor.current.x) + Math.abs(e.payload.y - cursor.current.y) > 1;
        cursor.current = e.payload;
        if (moved) lastMove.current = performance.now();
        st().setActive(true);
        if (claimUntil.current > Date.now()) {
          claimUntil.current = 0;
          setOwnsLesson(true);
        }
      }),
      listen("cursor-left", () => st().setActive(false)),
      // Every screen capture is visible; the tag stays up long enough to notice.
      listen<boolean>("screen-capture", (e) => {
        clearTimeout(lookingTimer.current);
        if (e.payload) {
          lookingSince.current = Date.now();
          setLooking(true);
        } else {
          const left = LOOKING_MIN_MS - (Date.now() - lookingSince.current);
          lookingTimer.current = setTimeout(() => setLooking(false), Math.max(0, left));
        }
      }),
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
      listen("escape-pressed", stopTalking),
      listen<Settings>("settings-changed", (e) => {
        setSettings(e.payload);
        st().setPaused(e.payload.paused);
      }),
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
        const prev = lessonRef.current;
        const wasActive = !!prev && ACTIVE_PHASES.includes(prev.phase);
        lessonRef.current = v;
        setLesson(v);
        // Claim the card when a lesson (or review) starts, or on reload mid-lesson.
        if (!wasActive && ACTIVE_PHASES.includes(v.phase)) {
          setOwnsLesson(st().active);
          if (!st().active) claimUntil.current = Date.now() + CLAIM_WINDOW_MS;
        }
        if (v.phase === "idle") setOwnsLesson(false);
        // A passed step: brief "nice ✓" on the cursor.
        if (prev && prev.phase === "verifying" && (v.stepIndex > prev.stepIndex || v.phase === "finished")) {
          setNice(true);
          setTimeout(() => setNice(false), NICE_MS);
        }
      }),
    ];
    void emit("lesson-state-request");
    return () => {
      subs.forEach((p) => p.then((off) => off()));
      audio.current?.reset();
      clearTimeout(hideTimer.current);
    };
  }, []);

  // The Nudgy cursor trails the real one with a slight, frame-rate independent lag.
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = now - last;
      last = now;
      pos.current = follow(pos.current, { x: cursor.current.x + OFFSET.x, y: cursor.current.y + OFFSET.y }, dt, 55);
      const el = anchor.current;
      if (el) {
        el.style.transform = `translate(${pos.current.x}px, ${pos.current.y}px)`;
        el.dataset.flip = pos.current.x > window.innerWidth - FLIP_X ? "left" : "right";
        el.dataset.flipY = pos.current.y > window.innerHeight - FLIP_Y ? "up" : "down";
      }
      const isIdle = now - lastMove.current > IDLE_FADE_MS;
      setIdle((was) => (was === isIdle ? was : isIdle));
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    if (lesson?.phase !== "finished" && lesson?.phase !== "failed") return;
    const id = setTimeout(() => setOwnsLesson(false), CAPTION_LINGER_MS);
    return () => clearTimeout(id);
  }, [lesson?.phase]);

  const showCard = ownsLesson && !!lesson && lesson.phase !== "idle" && !s.paused;
  const inLesson = showCard && lesson && ACTIVE_PHASES.includes(lesson.phase);

  let label: CursorLabel = null;
  if (nice) label = "nice";
  else if (s.mode === "listening") label = "listening";
  else if (s.mode === "thinking") label = "thinking";
  else if (s.mode === "talking" || speaking) label = "talking";
  else if (inLesson && lesson?.phase === "verifying") label = "checking";
  else if (inLesson && lesson?.phase === "waiting") label = "watching";

  const busy = label !== null || !!s.caption;
  const hidden = !s.active || s.paused || !!s.target;
  const faded = !busy && !inLesson && (idle || settings.hideCursorIdle);
  const opacity = hidden || faded ? 0 : busy || inLesson ? 1 : 0.55;

  let pill: PillState = null;
  if (speaking) pill = { kind: "speaking" };
  else if (showCard && lesson?.phase === "waiting") pill = { kind: "your_turn" };
  else if (showCard && lesson?.phase === "waiting_app") pill = { kind: "open_app", app: lesson.app };
  else if (showCard && lesson?.phase === "planning") pill = { kind: "planning" };

  return (
    <div className="overlay-root">
      <div ref={anchor} className="anchor" style={{ opacity }}>
        <div className={`anchor__cursor ${nice ? "hop" : ""}`}>
          <NudgyCursor color={settings.cursorColor} size={settings.cursorSize} />
          <StateLabel label={label} text={label ? t(`cursor.${label}`) : ""} />
        </div>
        {s.caption && <CaptionBubble caption={s.caption} />}
      </div>
      {s.target && !s.paused && (
        <Pointer
          key={s.target.seq}
          target={s.target}
          from={pointerFrom}
          color={settings.cursorColor}
          size={settings.cursorSize}
          onDone={s.clearTarget}
        />
      )}
      {looking && s.active && (
        <div className="capture" role="status">
          <i aria-hidden />
          {t("capture.looking")}
        </div>
      )}
      {showCard && lesson && <LessonCard view={lesson} />}
      {s.active && !s.paused && <StatusPill state={pill} />}
      {nudge && !s.paused && !showCard && <ReviewNudge nudge={nudge} onClose={() => setNudge(null)} />}
      {recording.recording && s.active && <RecorderBar steps={recording.steps} />}
    </div>
  );
}
