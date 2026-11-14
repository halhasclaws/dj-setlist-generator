"use client";

import { signIn, useSession } from "next-auth/react";
import { useState } from "react";

type SaveState = "idle" | "busy" | "saved" | "connect" | "error";

function reconnectCallbackUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("spotify", "connected");
  return url.toString();
}

// Remembers what this browser saved, so closing and reopening a track's Spotify
// player (or reloading the page) keeps the green check. The site can't ask
// Spotify which songs are liked without an extra read permission, so a track
// removed in the Spotify app still shows the check here until pressed.
const SAVED_KEY = "spotify-saved-tracks";
const savedTracks = (() => {
  let cache: Set<string> | null = null;
  const load = () => {
    if (cache) return cache;
    cache = new Set();
    try {
      const raw = window.localStorage.getItem(SAVED_KEY);
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) for (const id of parsed) if (typeof id === "string") cache.add(id);
    } catch { /* storage unavailable: keep in memory only */ }
    return cache;
  };
  return {
    has: (id: string) => load().has(id),
    set: (id: string, saved: boolean) => {
      const set = load();
      if (saved) set.add(id); else set.delete(id);
      try { window.localStorage.setItem(SAVED_KEY, JSON.stringify([...set])); } catch { /* ignore */ }
    },
  };
})();

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
  const [state, setState] = useState<SaveState>(() => (savedTracks.has(trackId) ? "saved" : "idle"));
  const [message, setMessage] = useState<string | null>(null);
  const { status } = useSession();

  const update = async (saved: boolean) => {
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
        savedTracks.set(trackId, saved);
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
