// Local opt-in diagnostics for playback QA. No URLs, track IDs, account data or
// server transmission. Times are relative to this page's navigation only.
// With ?audioTiming=1 lines also go to a small session-local log that the
// page can show, so a real phone can report what happened (see AudioDebugLog).

const STORAGE_KEY = "audio-timing-log";
const MAX_LINES = 300;
type Listener = () => void;
const listeners = new Set<Listener>();
let lines: string[] | null = null;

export const audioTimingEnabled = () =>
  typeof window !== "undefined" && new URLSearchParams(window.location.search).get("audioTiming") === "1";

const load = (): string[] => {
  if (lines) return lines;
  try {
    const stored = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? "[]");
    lines = Array.isArray(stored) ? stored.filter((line): line is string => typeof line === "string") : [];
  } catch {
    lines = [];
  }
  return lines;
};

const save = () => {
  try { window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(lines ?? [])); } catch { /* private mode */ }
};

export function traceAudioTiming(event: string, provider: string) {
  if (!audioTimingEnabled()) return;
  const line = `${new Date().toISOString().slice(11, 23)} +${performance.now().toFixed(0)} ${provider} ${event}`;
  console.info(`[audio-timing] ${performance.now().toFixed(1)} ${provider} ${event}`);
  const log = load();
  log.push(line);
  if (log.length > MAX_LINES) log.splice(0, log.length - MAX_LINES);
  save();
  for (const listener of listeners) listener();
}

export function readAudioTimingLog(): string[] {
  return audioTimingEnabled() ? [...load()] : [];
}

export function clearAudioTimingLog() {
  lines = [];
  save();
  for (const listener of listeners) listener();
}

export function subscribeAudioTimingLog(listener: Listener) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
