"use client";

import { SessionContext, signIn } from "next-auth/react";
import { useCallback, useContext, useEffect, useSyncExternalStore } from "react";

import styles from "./set-likes.module.css";

// Liked sets (N10). One shared store per page, so every card and the set page
// pill agree. The signed-in viewer's likes load once; a tap updates the store
// at once and reverts if the save fails. Signed-out taps ask the viewer to
// sign in.

type LikesState = { liked: ReadonlySet<string>; loaded: boolean };

let state: LikesState = { liked: new Set(), loaded: false };
let loading: Promise<void> | null = null;
const listeners = new Set<() => void>();

const emit = (next: LikesState) => {
  state = next;
  for (const listener of listeners) listener();
};

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

const getSnapshot = () => state;
const serverSnapshot: LikesState = { liked: new Set(), loaded: false };
const getServerSnapshot = () => serverSnapshot;

const withLiked = (setId: string, liked: boolean) => {
  const next = new Set(state.liked);
  if (liked) next.add(setId);
  else next.delete(setId);
  return next;
};

// The set page knows its own liked state from the server, so its pill is right
// on first paint; later loads of the full list keep any newer local change.
export const seedSetLike = (setId: string, liked: boolean) => {
  if (state.loaded || state.liked.has(setId) === liked) return;
  emit({ ...state, liked: withLiked(setId, liked) });
};

const loadLikes = () => {
  if (loading) return loading;
  loading = fetch("/api/archive/set-likes", { cache: "no-store", credentials: "same-origin" })
    .then(async (response) => {
      if (!response.ok) return;
      const payload = (await response.json()) as { likedSetIds?: unknown };
      if (!Array.isArray(payload.likedSetIds)) return;
      emit({ liked: new Set(payload.likedSetIds.filter((id): id is string => typeof id === "string")), loaded: true });
    })
    .catch(() => undefined)
    .finally(() => {
      if (!state.loaded) loading = null;
    });
  return loading;
};

// Read the session without useSession, which throws outside a provider; with
// no provider the controls stay inert (no fetch, no sign-in prompt).
const useSessionStatus = () => useContext(SessionContext)?.status ?? "loading";

const signInHere = () => {
  void signIn(undefined, { callbackUrl: window.location.href });
};

export function useSetLikes() {
  const status = useSessionStatus();
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const signedIn = status === "authenticated";

  useEffect(() => {
    if (signedIn) void loadLikes();
  }, [signedIn]);

  const toggle = useCallback(
    async (setId: string) => {
      if (status !== "authenticated") {
        if (status === "unauthenticated") signInHere();
        return;
      }
      const liked = !state.liked.has(setId);
      emit({ ...state, liked: withLiked(setId, liked) });
      try {
        const response = await fetch("/api/archive/set-likes", {
          body: JSON.stringify({ liked, setId }),
          credentials: "same-origin",
          headers: { "content-type": "application/json" },
          method: "PUT",
        });
        if (response.status === 401) {
          emit({ ...state, liked: withLiked(setId, !liked) });
          signInHere();
          return;
        }
        if (!response.ok) throw new Error(`Like save failed with ${response.status}`);
      } catch (error) {
        console.error("[set-likes] save failed", error);
        emit({ ...state, liked: withLiked(setId, !liked) });
      }
    },
    [status],
  );

  return {
    isLiked: (setId: string) => snapshot.liked.has(setId),
    likedSetIds: snapshot.liked,
    loaded: snapshot.loaded,
    signedIn,
    status,
    toggle,
  };
}

export const HeartIcon = ({ filled }: { filled: boolean }) => (
  <svg aria-hidden="true" className={styles.heart} viewBox="0 0 24 24">
    <path
      d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.8 4.5c2.2 0 3.6 1.2 5.2 3 1.6-1.8 3-3 5.2-3 3.8 0 5.9 3.9 4.4 7.3C19.5 16.4 12 21 12 21z"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeLinejoin="round"
      strokeWidth="2"
    />
  </svg>
);

const joinClasses = (...values: Array<string | false | null | undefined>) => values.filter(Boolean).join(" ");

export function SetLikePill({
  className,
  initialLiked,
  setId,
  size = "card",
  title,
}: {
  className?: string;
  initialLiked?: boolean | null;
  setId: string;
  size?: "card" | "page";
  title?: string;
}) {
  const likes = useSetLikes();

  useEffect(() => {
    if (typeof initialLiked === "boolean") seedSetLike(setId, initialLiked);
  }, [initialLiked, setId]);

  const liked = likes.isLiked(setId);
  const label = liked ? `Unlike ${title ?? "this set"}` : `Like ${title ?? "this set"}`;

  return (
    <button
      aria-label={label}
      aria-pressed={liked}
      className={joinClasses(styles.likePill, size === "page" && styles.likePillLarge, liked && styles.on, className)}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        void likes.toggle(setId);
      }}
      title={liked ? "Liked. Tap to unlike" : "Like this set"}
      type="button"
    >
      <HeartIcon filled={liked} />
    </button>
  );
}

export function LikedFilterButton({
  active,
  className,
  onChange,
}: {
  active: boolean;
  className?: string;
  onChange: (active: boolean) => void;
}) {
  const status = useSessionStatus();
  return (
    <button
      aria-pressed={active}
      className={joinClasses(styles.likedFilter, active && styles.on, className)}
      onClick={() => {
        if (!active && status === "unauthenticated") {
          signInHere();
          return;
        }
        onChange(!active);
      }}
      title={active ? "Showing liked sets only" : "Show only sets you liked"}
      type="button"
    >
      <HeartIcon filled={active} />
      Liked
    </button>
  );
}
