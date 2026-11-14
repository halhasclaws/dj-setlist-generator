import { NextResponse } from "next/server";
import { z } from "zod";

import { getSessionActor } from "@/lib/auth/session";
import {
  ensureSpotifyLibraryScope,
  getSpotifyTrackSaved,
  isSpotifyTrackId,
  SPOTIFY_LIBRARY_READ_SCOPE,
  setSpotifyTrackSaved,
  SpotifyLibraryRemoteError,
  SpotifyLibraryScopeError,
} from "@/lib/spotify/library.server";
import {
  refreshSpotifyAccessTokenForUser,
  SpotifyConfigurationError,
  SpotifyConnectionError,
  SpotifyTokenRefreshError,
} from "@/lib/spotify/server";

const librarySchema = z.object({
  saved: z.boolean(),
  trackId: z.string().refine(isSpotifyTrackId, "Invalid Spotify track id"),
});

const libraryErrorResponse = (error: unknown) => {
  if (error instanceof SpotifyConnectionError || error instanceof SpotifyLibraryScopeError) {
    return NextResponse.json({ error: error.message, reason: "connect" }, { status: 409 });
  }
  if (error instanceof SpotifyConfigurationError) {
    return NextResponse.json({ error: error.message }, { status: 503 });
  }
  if (error instanceof SpotifyTokenRefreshError || error instanceof SpotifyLibraryRemoteError) {
    return NextResponse.json({ error: error.message }, { status: 502 });
  }
  throw error;
};

// GET ?trackId=ID: is this track in the viewer's Liked Songs right now?
export async function GET(request: Request) {
  const actor = await getSessionActor();
  if (!actor) {
    return NextResponse.json({ error: "Sign in to check saved tracks", reason: "signin" }, { status: 401 });
  }

  const trackId = new URL(request.url).searchParams.get("trackId");
  if (!isSpotifyTrackId(trackId)) {
    return NextResponse.json({ error: "Invalid Spotify track id" }, { status: 400 });
  }

  try {
    const token = await refreshSpotifyAccessTokenForUser(actor.userId);
    ensureSpotifyLibraryScope(token.scopes, SPOTIFY_LIBRARY_READ_SCOPE);
    const saved = await getSpotifyTrackSaved({ accessToken: token.accessToken, trackId });
    return NextResponse.json({ saved }, { headers: { "cache-control": "private, no-store" } });
  } catch (error) {
    return libraryErrorResponse(error);
  }
}

// Browser-session only: a cross-site page cannot send a JSON body without a
// CORS preflight, which this route never approves.
export async function POST(request: Request) {
  if (!(request.headers.get("content-type") ?? "").includes("application/json")) {
    return NextResponse.json({ error: "JSON body required" }, { status: 415 });
  }

  const actor = await getSessionActor();
  if (!actor) {
    return NextResponse.json({ error: "Sign in to save tracks", reason: "signin" }, { status: 401 });
  }

  const parsed = librarySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.issues[0]?.message ?? "Invalid request" }, { status: 400 });
  }

  try {
    const token = await refreshSpotifyAccessTokenForUser(actor.userId);
    ensureSpotifyLibraryScope(token.scopes);
    await setSpotifyTrackSaved({
      accessToken: token.accessToken,
      saved: parsed.data.saved,
      trackId: parsed.data.trackId,
    });
    return NextResponse.json({ saved: parsed.data.saved });
  } catch (error) {
    return libraryErrorResponse(error);
  }
}
