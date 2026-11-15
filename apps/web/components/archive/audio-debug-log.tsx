"use client";

import { useEffect, useState, type RefObject } from "react";
import {
  audioTimingEnabled,
  clearAudioTimingLog,
  readAudioTimingLog,
  subscribeAudioTimingLog,
  traceAudioTiming,
} from "@/lib/archive/audio-timing";

const elementState = (audio: HTMLMediaElement) =>
  `rs=${audio.readyState} ns=${audio.networkState} paused=${audio.paused} t=${audio.currentTime.toFixed(1)}` +
  (audio.error ? ` err=${audio.error.code}` : "");

const MEDIA_EVENTS = ["play", "playing", "pause", "waiting", "stalled", "suspend", "abort", "emptied", "error",
  "loadstart", "loadedmetadata", "canplay", "seeking", "seeked", "ended"] as const;

/** Logs every media element event (with its state) and page lifecycle changes. */
export function useAudioDebugEvents(ref: RefObject<HTMLAudioElement | null>, elementKey: string) {
  useEffect(() => {
    const audio = ref.current;
    if (!audio || !audioTimingEnabled()) return;
    const onEvent = (event: Event) => traceAudioTiming(`ev:${event.type} ${elementState(audio)}`, "native-audio");
    for (const name of MEDIA_EVENTS) audio.addEventListener(name, onEvent);
    const onVisibility = () => traceAudioTiming(`page:${document.visibilityState} ${elementState(audio)}`, "page");
    const onPageShow = (event: PageTransitionEvent) => traceAudioTiming(`page:pageshow persisted=${event.persisted}`, "page");
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pageshow", onPageShow);
    traceAudioTiming(`page:mounted ${elementState(audio)}`, "page");
    return () => {
      for (const name of MEDIA_EVENTS) audio.removeEventListener(name, onEvent);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, [ref, elementKey]);
}

/** On-page log for ?audioTiming=1, so a phone can show and copy what happened. */
export function AudioDebugLog() {
  const [enabled, setEnabled] = useState(false);
  const [lines, setLines] = useState<string[]>([]);
  const [open, setOpen] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!audioTimingEnabled()) return;
    setEnabled(true);
    setLines(readAudioTimingLog());
    return subscribeAudioTimingLog(() => setLines(readAudioTimingLog()));
  }, []);

  if (!enabled) return null;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable */ }
  };
  return (
    <div
      aria-label="Audio debug log"
      style={{
        position: "fixed", left: 8, right: 8, bottom: 8, zIndex: 9999, maxHeight: open ? "40vh" : "auto",
        display: "flex", flexDirection: "column", background: "rgba(0,0,0,0.85)", color: "#d6ff6b",
        font: "11px/1.35 ui-monospace, Menlo, monospace", borderRadius: 8, padding: 6,
      }}
    >
      <div style={{ display: "flex", gap: 8, marginBottom: open ? 4 : 0 }}>
        <strong style={{ flex: 1 }}>Audio log ({lines.length})</strong>
        <button type="button" onClick={() => void copy()}>{copied ? "Copied" : "Copy"}</button>
        <button type="button" onClick={clearAudioTimingLog}>Clear</button>
        <button type="button" onClick={() => setOpen((value) => !value)}>{open ? "Hide" : "Show"}</button>
      </div>
      {open ? (
        <pre style={{ margin: 0, overflow: "auto", whiteSpace: "pre-wrap" }}>{lines.slice(-80).join("\n")}</pre>
      ) : null}
    </div>
  );
}
