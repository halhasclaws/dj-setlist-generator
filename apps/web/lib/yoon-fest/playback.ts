export type RecordingSpan = {
  recordingId: string;
  startSample: number;
  endSample: number;
  sampleRate: number;
};

export function spanDuration(span: RecordingSpan): number {
  if (!span.recordingId || !Number.isSafeInteger(span.startSample) || !Number.isSafeInteger(span.endSample) ||
    !Number.isSafeInteger(span.sampleRate) || span.sampleRate <= 0 || span.startSample < 0 || span.endSample <= span.startSample) {
    throw new Error("Invalid recording span");
  }
  return (span.endSample - span.startSample) / span.sampleRate;
}

// Half-open spans: a seam belongs to the next file. The set endpoint belongs
// to the final span. Provenance is retained even when playback uses one derivative.
export function locateRecordingTime(spans: RecordingSpan[], seconds: number) {
  if (!spans.length || !Number.isFinite(seconds)) throw new Error("Invalid set position");
  const durations = spans.map(spanDuration);
  const total = durations.reduce((sum, value) => sum + value, 0);
  const target = Math.max(0, Math.min(seconds, total));
  let start = 0;
  for (let index = 0; index < spans.length; index += 1) {
    const span = spans[index]!;
    const duration = durations[index]!;
    if (target < start + duration || index === spans.length - 1) {
      const offset = Math.min(duration, target - start);
      return { recordingId: span.recordingId, spanIndex: index,
        sourceSeconds: span.startSample / span.sampleRate + offset,
        sourceSample: Math.min(span.endSample, span.startSample + Math.floor(offset * span.sampleRate)),
        setSeconds: target };
    }
    start += duration;
  }
  throw new Error("Invalid set position");
}

// Browsers report media time with less precision than a sample-exact start
// (Chrome rounds to microseconds), so a position just "before" a window start
// is the start itself. Without this, a source window starting mid-file looks
// permanently out of range and every tick re-seeks it.
export const SOURCE_TIME_TOLERANCE_SECONDS = 0.002;
// A requested play that the element silently dropped (for example at a file
// seam while the next source was still loading) is retried after this long.
const PLAY_WATCHDOG_MS = 1200;

// Seamless file seams: a second, off-page element loads the next original file
// shortly before the boundary and keeps playing from it while the visible
// element switches files, then hands back at a buffered point.
const PRELOAD_SECONDS = 20;
const HANDOFF_LEAD_SECONDS = 1.5;
// A set's last window can end at the very end of an original file whose final
// sample frame is incomplete (a data chunk that is not a whole number of
// frames). Decoding that frame raises a demuxer error instead of "ended", so
// the set finishes at its mapped end frame, a little before the file's end.
export const FINAL_END_GUARD_SECONDS = 0.05;
// A media error this close to the active window's mapped end is the end of
// that window, not a dead provider URL: move on (or finish), never reload.
export const NEAR_END_ERROR_SECONDS = 2;

export type NativeAudioSegment = { src: string; startSeconds: number; durationSeconds: number };
export type StandbyAudio = NativeAudioPort & { preload: string;
  addEventListener(type: "loadedmetadata" | "error", listener: () => void): void;
  removeEventListener(type: "loadedmetadata" | "error", listener: () => void): void };
export type NativeAudioOptions = { createStandby?: () => StandbyAudio };
export type NativeAudioPort = Pick<HTMLAudioElement, "src" | "load" | "paused" | "currentTime" | "readyState" | "play" | "pause"> & { readonly ended?: boolean };

// The set clock spans original files. Only the selected source window is played;
// source URLs are same-origin authorized redirects, never bearer URLs in props.
export function createNativeAudioController(audio: NativeAudioPort, duration: number, onError: (message: string) => void, sourceSegments?: NativeAudioSegment[], options: NativeAudioOptions = {}) {
  const segments = sourceSegments ?? [{ src: audio.src, startSeconds: 0, durationSeconds: duration }];
  if (!segments.length || segments.some((part) => !Number.isFinite(part.startSeconds) || part.startSeconds < 0 || !Number.isFinite(part.durationSeconds) || part.durationSeconds <= 0) ||
    Math.abs(segments.reduce((sum, part) => sum + part.durationSeconds, 0) - duration) > 0.25) throw new Error("Invalid playback segments");
  const offsets = segments.map((_, index) => segments.slice(0, index).reduce((sum, part) => sum + part.durationSeconds, 0));
  let version = 0;
  let disposed = false;
  let activeIndex = 0;
  let awaitingMetadata = false;
  let pending: { seconds: number; autoplay: boolean } | null = null;
  let playRequested = false;
  let playAttempt: { version: number; settled: Promise<void> } | null = null;
  let stalledSince: number | null = null;
  let standby: StandbyAudio | null = null;
  let prepared: number | null = null;
  let bridge: { index: number; handoffAt: number | null } | null = null;
  let handoffTimer: ReturnType<typeof setInterval> | null = null;
  // Stopped at the set's end without the element reaching its own end.
  let parkedAtEnd = false;
  // The element hit a media error: the next seek must reload its source.
  let mustReload = false;
  const windowEnd = (index: number) => offsets[index]! + segments[index]!.durationSeconds;
  const bridgedPosition = () => {
    const part = segments[bridge!.index]!;
    return Math.max(offsets[bridge!.index]!, Math.min(windowEnd(bridge!.index), offsets[bridge!.index]! + standby!.currentTime - part.startSeconds));
  };
  const endBridge = () => {
    if (handoffTimer !== null) { clearInterval(handoffTimer); handoffTimer = null; }
    if (!bridge) return;
    bridge = null;
    prepared = null;
    standby?.pause();
  };
  const prepareNext = () => {
    const next = activeIndex + 1;
    if (!options.createStandby || bridge || next >= segments.length || prepared === next) return;
    if (!playRequested || audio.paused || pending || awaitingMetadata) return;
    if (windowEnd(activeIndex) - position() > PRELOAD_SECONDS) return;
    const target = standby ?? (standby = options.createStandby());
    const part = segments[next]!;
    prepared = next;
    const cleanup = () => { target.removeEventListener("loadedmetadata", onMeta); target.removeEventListener("error", onFail); };
    const onMeta = () => { cleanup(); if (prepared !== next) return; try { target.currentTime = part.startSeconds; } catch { prepared = null; } };
    const onFail = () => { cleanup(); if (prepared === next && !bridge) prepared = null; };
    target.addEventListener("loadedmetadata", onMeta);
    target.addEventListener("error", onFail);
    target.preload = "auto";
    target.src = part.src;
    target.load();
  };
  const standbyReady = (index: number) => Boolean(standby && prepared === index && !bridge && standby.readyState >= 3 &&
    Math.abs(standby.currentTime - segments[index]!.startSeconds) < 0.25);
  const beginBridge = (next: number) => {
    const voice = standby!;
    bridge = { index: next, handoffAt: null };
    version += 1;
    voice.play().catch(() => {
      if (!bridge || bridge.index !== next) return;
      const at = bridgedPosition();
      endBridge();
      seek(at, true);
    });
    audio.pause();
    activeIndex = next;
    awaitingMetadata = true;
    pending = null;
    audio.src = segments[next]!.src;
    audio.load();
    if (typeof setInterval === "function") handoffTimer = setInterval(handoff, 40);
  };
  const handoff = () => {
    if (disposed || !bridge) { endBridge(); return; }
    if (bridge.handoffAt === null || awaitingMetadata) return;
    const at = bridgedPosition();
    if (at < bridge.handoffAt - 0.02) return;
    if (audio.readyState >= 3) {
      endBridge();
      startPlayback(++version);
      return;
    }
    if (at > bridge.handoffAt + 0.3) aimHandoff(at);
  };
  const aimHandoff = (at: number) => {
    const index = bridge!.index;
    const target = Math.min(windowEnd(index), at + HANDOFF_LEAD_SECONDS);
    bridge!.handoffAt = target;
    audio.currentTime = segments[index]!.startSeconds + target - offsets[index]!;
  };
  let watchdog: ReturnType<typeof setInterval> | null = null;
  const stopWatchdog = () => { if (watchdog !== null) { clearInterval(watchdog); watchdog = null; } stalledSince = null; };
  // Paused media emits no timeupdate, so a dropped play is checked on a timer
  // for as long as play is requested, not only when the explorer polls.
  const armWatchdog = () => {
    if (watchdog !== null || typeof setInterval !== "function") return;
    watchdog = setInterval(() => {
      if (disposed || !playRequested) { stopWatchdog(); return; }
      checkDroppedPlay();
    }, 400);
  };
  const checkDroppedPlay = () => {
    if (bridge || !playRequested || pending || awaitingMetadata || audio.readyState < 1 || !audio.paused || audio.ended || playAttempt !== null) {
      stalledSince = null; return;
    }
    const now = Date.now();
    if (stalledSince === null) stalledSince = now;
    else if (now - stalledSince >= PLAY_WATCHDOG_MS) { stalledSince = null; startPlayback(++version); }
  };
  const startPlayback = (request: number) => {
    armWatchdog();
    // Keep the pending play promise separate from the pending source seek.
    // A seek may be applied while play() is still starting or being denied.
    const attempt = { version: request, settled: Promise.resolve() };
    playAttempt = attempt;
    attempt.settled = audio.play().then(() => {
      if (playAttempt === attempt) playAttempt = null;
    }, () => {
      if (playAttempt === attempt) playAttempt = null;
      if (disposed || request !== version) return;
      playRequested = false;
      if (pending) pending = { ...pending, autoplay: false };
      audio.pause();
      onError("Playback could not start. Press Play to try again.");
    });
  };
  const pause = () => {
    if (bridge) { const at = bridgedPosition(); endBridge(); seek(at, false); return; }
    version += 1;
    playRequested = false;
    if (pending) pending = { ...pending, autoplay: false };
    audio.pause();
  };
  const seek = (seconds: number, autoplay: boolean) => {
    if (disposed || !Number.isFinite(seconds)) return;
    endBridge();
    parkedAtEnd = false;
    const request = ++version;
    const target = Math.max(0, Math.min(duration, seconds));
    const index = segments.findIndex((part, index) => target < offsets[index]! + part.durationSeconds);
    const selected = index < 0 ? segments.length - 1 : index;
    // The endpoint is a stopped position, never permission to play beyond it.
    playRequested = autoplay && target < duration;
    pending = { seconds: target, autoplay: playRequested };
    audio.pause();
    if (selected !== activeIndex || mustReload) {
      mustReload = false;
      activeIndex = selected;
      awaitingMetadata = true;
      audio.src = segments[selected]!.src;
      audio.load();
    }
    if (audio.readyState < 1 || awaitingMetadata) {
      // Invoke play in the user's gesture even when a mobile browser defers
      // metadata. loadedmetadata applies the pending offset before audio plays.
      if (playRequested) startPlayback(request);
      return;
    }
    try {
      audio.currentTime = Math.min(segments[selected]!.startSeconds + segments[selected]!.durationSeconds, segments[selected]!.startSeconds + target - offsets[selected]!);
      pending = null;
      if (playRequested) startPlayback(request);
    } catch {
      playRequested = false;
      pending = null;
      audio.pause();
      onError("This recording could not seek. Reload the page to try again.");
    }
  };
  const position = (): number => parkedAtEnd ? duration : bridge ? bridgedPosition() : pending?.seconds ?? Math.max(offsets[activeIndex]!, Math.min(offsets[activeIndex]! + segments[activeIndex]!.durationSeconds,
    offsets[activeIndex]! + audio.currentTime - segments[activeIndex]!.startSeconds));
  const resume = (replayAtEnd = true) => {
    if (disposed || bridge) return;
    // A normal pause keeps the decoder, buffer and exact media position.
    // Seeking to our displayed (polled) clock would discard that warm state.
    const part = segments[activeIndex]!;
    const target = position();
    if (target >= duration && !replayAtEnd) { pause(); return; }
    if (parkedAtEnd || mustReload || pending || awaitingMetadata || audio.readyState < 1 || audio.ended || audio.currentTime < part.startSeconds - SOURCE_TIME_TOLERANCE_SECONDS ||
      audio.currentTime >= part.startSeconds + part.durationSeconds) {
      seek(target >= duration ? 0 : target, true);
      return;
    }
    playRequested = true;
    startPlayback(++version);
  };
  // Stop at the set's endpoint without asking the element for more media.
  const finish = () => {
    endBridge();
    version += 1;
    playRequested = false;
    pending = null;
    parkedAtEnd = true;
    audio.pause();
    return duration;
  };
  const ended = () => {
    if (disposed) return duration;
    if (parkedAtEnd) return duration;
    // ended events can already be queued when a user or Spotify pauses us.
    // They cannot grant a new autoplay request after that pause.
    if (!playRequested || bridge) return position();
    if (activeIndex < segments.length - 1) {
      if (standbyReady(activeIndex + 1)) beginBridge(activeIndex + 1);
      else seek(offsets[activeIndex + 1]!, true);
      return position();
    }
    seek(duration, false);
    return duration;
  };
  return {
    seek,
    resume,
    position,
    ended,
    // During a bridge the visible element is paused on purpose; its events
    // must not read as a stall or a user pause.
    isPlayRequested: () => playRequested && !bridge,
    isPending: () => !bridge && (pending !== null || awaitingMetadata),
    async observePause(onPaused: () => void) {
      if (bridge) return;
      const observedVersion = version;
      const attempt = playAttempt;
      // pause events are queued. An internal seek's pause must not cancel a
      // newer play just because metadata/seek completed before play settled.
      if (attempt?.version === observedVersion) await attempt.settled;
      if (disposed || observedVersion !== version || !audio.paused || (pending && playRequested)) return;
      // Native media emits pause before ended at a natural file boundary.
      // Preserve intent for that transition, but never undo an explicit pause.
      if (audio.ended && playRequested) return;
      pause();
      onPaused();
    },
    tick() {
      if (parkedAtEnd || bridge) return position();
      if (disposed || pending || awaitingMetadata || audio.readyState < 1) { stalledSince = null; return position(); }
      const part = segments[activeIndex]!;
      checkDroppedPlay();
      prepareNext();
      const last = activeIndex === segments.length - 1;
      if (last && (!audio.paused || playRequested) && audio.currentTime < part.startSeconds + part.durationSeconds &&
        audio.currentTime >= part.startSeconds + part.durationSeconds - FINAL_END_GUARD_SECONDS) return finish();
      if (audio.currentTime < part.startSeconds - SOURCE_TIME_TOLERANCE_SECONDS) seek(offsets[activeIndex]!, !audio.paused);
      else if (audio.currentTime >= part.startSeconds + part.durationSeconds) {
        // A window that ends at (or a few samples before) the end of its file
        // reaches the browser's own end first: the element is already paused
        // when this timeupdate arrives. Play intent, not paused, decides.
        if (!audio.paused || playRequested) return ended();
        if (audio.currentTime > part.startSeconds + part.durationSeconds) seek(offsets[activeIndex]! + part.durationSeconds, false);
      }
      return position();
    },
    ready() {
      awaitingMetadata = false;
      if (bridge) { try { aimHandoff(bridgedPosition()); } catch { const at = bridgedPosition(); endBridge(); seek(at, true); } return; }
      if (pending) seek(pending.seconds, pending.autoplay);
    },
    // Provider media URLs behind the same-origin route are short-lived and a
    // network error or a dead stall is terminal for the element. Re-request the
    // active source through the route and restore the set position and the
    // current play intent. A pause stays paused; nothing plays past the end.
    recover() {
      if (disposed) return false;
      const target = position();
      parkedAtEnd = false;
      mustReload = false;
      endBridge();
      const request = ++version;
      playRequested = playRequested && target < duration;
      pending = { seconds: target, autoplay: playRequested };
      awaitingMetadata = true;
      audio.pause();
      audio.src = segments[activeIndex]!.src;
      audio.load();
      if (playRequested) startPlayback(request);
      return true;
    },
    // A media error near the active window's mapped end (for example a
    // truncated last sample frame) ends that window. Returns "advanced" when
    // playback moved to the next window, "finished" when the set stopped at its
    // end, or false when the error is not near an end and needs recovery.
    endOnError(): "advanced" | "finished" | false {
      if (disposed || bridge || parkedAtEnd || pending || awaitingMetadata) return false;
      const part = segments[activeIndex]!;
      if (!Number.isFinite(audio.currentTime) || audio.currentTime < part.startSeconds + part.durationSeconds - NEAR_END_ERROR_SECONDS) return false;
      mustReload = true;
      if (activeIndex < segments.length - 1) {
        seek(offsets[activeIndex + 1]!, playRequested);
        return "advanced";
      }
      finish();
      return "finished";
    },
    pause,
    dispose() { endBridge(); disposed = true; version += 1; playRequested = false; pending = null; stopWatchdog(); audio.pause(); if (standby) { standby.src = ""; standby = null; } },
  };
}
