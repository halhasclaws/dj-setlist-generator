"use client";

import { signIn, useSession } from "next-auth/react";
import { useEffect, useRef, useState } from "react";

type SaveState = "idle" | "busy" | "saved" | "connect" | "error";

function reconnectCallbackUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("spotify", "connected");
  return url.toString();
}

// Last known Liked Songs state per track for this page visit, so reopening a
// player shows the right icon at once. Spotify is asked again on every open
// and always wins, so a song liked or removed elsewhere shows correctly.
const knownSaved = new Map<string, boolean>();

const PlusIcon = () => (
  <svg viewBox="0 0 24 24" width="100%" height="100%" aria-hidden="true">
    <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="1.6" />
    <path d="M12 7.5v9M7.5 12h9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" width="100%" height="100%" aria-hidden="true">
    <circle cx="12" cy="12" r="11" fill="#1db954" />
    <path d="M7.2 12.3l3.2 3.2 6.4-6.6" fill="none" stroke="#000" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// A small "+" beside the track's Spotify button, shown while its player is
// open. It saves the track to the viewer's Liked Songs through the site's own
// Spotify connection, so the listener never leaves the set page. The embed's
// built-in "+" cannot be driven from here (cross-origin iframe, separate login).
// Pressing it again after saving removes the track.
export function SpotifySaveButton({ trackId, label }: { trackId: string; label: string }) {
  const [state, setState] = useState<SaveState>(() => (knownSaved.get(trackId) ? "saved" : "idle"));
  const [message, setMessage] = useState<string | null>(null);
  const { status } = useSession();
  const changed = useRef(false);

  useEffect(() => {
    if (status !== "authenticated") return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`/api/spotify/library?trackId=${encodeURIComponent(trackId)}`, { cache: "no-store" });
        const payload = (await response.json().catch(() => ({}))) as { saved?: unknown; error?: string; reason?: string };
        // A press while this check was in flight is newer than its answer.
        if (cancelled || changed.current) return;
        if (response.ok && typeof payload.saved === "boolean") {
          knownSaved.set(trackId, payload.saved);
          setState(payload.saved ? "saved" : "idle");
        } else if (payload.reason === "connect") {
          setState("connect");
          setMessage(payload.error ?? null);
        }
      } catch { /* keep the last known state */ }
    })();
    return () => { cancelled = true; };
  }, [status, trackId]);

  const update = async (saved: boolean) => {
    changed.current = true;
    setState("busy");
    setMessage(null);
    try {
      const response = await fetch("/api/spotify/library", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ trackId, saved }),
      });
      const payload = (await response.json().catch(() => ({}))) as { error?: string; reason?: string };
      if (response.ok) {
        knownSaved.set(trackId, saved);
        setState(saved ? "saved" : "idle");
        return;
      }
      setState(payload.reason === "connect" ? "connect" : "error");
      setMessage(payload.error ?? "Spotify could not save this track.");
    } catch {
      setState("error");
      setMessage("Spotify could not be reached.");
    }
  };

  if (status !== "authenticated") return null;

  const saved = state === "saved";
  const title = saved
    ? "In your Liked Songs. Press to remove."
    : state === "connect"
      ? "Allow saving to Spotify (reconnects Spotify once)"
      : state === "error" && message
        ? message
        : "Save to your Spotify Liked Songs";

  return (
    <button
      type="button"
      className="spotify-save-chip"
      data-state={state}
      aria-label={saved ? `Remove ${label} from your Spotify Liked Songs` : `Save ${label} to your Spotify Liked Songs`}
      aria-pressed={saved}
      title={title}
      disabled={state === "busy"}
      onClick={(event) => {
        event.stopPropagation();
        if (state === "connect") {
          void signIn("spotify", { callbackUrl: reconnectCallbackUrl() });
          return;
        }
        void update(!saved);
      }}
    >
      <span className="ico">{saved ? <CheckIcon /> : <PlusIcon />}</span>
      <span className="visually-hidden" role="status">
        {saved ? "Saved to Liked Songs" : state === "error" || state === "connect" ? message ?? "" : ""}
      </span>
    </button>
  );
}
