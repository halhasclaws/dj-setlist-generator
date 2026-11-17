import { NextRequest, NextResponse } from "next/server";

import {
  getArchiveHomeSetLibraryPayload,
  getWorkspaceSetLibraryPayload,
} from "@/lib/archive/home-explorer-data";
import type { ArchiveHomeSetSort } from "@/lib/archive/home-explorer-types";
import { getSessionActor } from "@/lib/auth/session";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const page = Number(searchParams.get("page") ?? "1");
  const query = searchParams.get("query") ?? "";
  const artistFilter = searchParams.get("artist") ?? "ALL";
  const scope = searchParams.get("scope");
  const sort = searchParams.get("sort");
  const resolvedSort: ArchiveHomeSetSort =
    sort === "default" || sort === "duration" || sort === "rate" || sort === "tracks"
      ? (sort as ArchiveHomeSetSort)
      : "default";
  const safePage = Number.isFinite(page) ? page : 1;

  const actor = await getSessionActor();
  // Liked filter (N10): needs a signed-in viewer; signed out it's ignored.
  const likedOnly = Boolean(actor) && searchParams.get("liked") === "1";

  if (scope === "mine") {
    if (actor) {
      const payload = await getWorkspaceSetLibraryPayload({
        artistFilter,
        likedOnly,
        page: safePage,
        query,
        sort: resolvedSort,
        userId: actor.userId,
      });
      return NextResponse.json(payload);
    }
  }

  const payload = await getArchiveHomeSetLibraryPayload({
    artistFilter,
    likedOnly,
    page: safePage,
    query,
    sort: resolvedSort,
    viewerUserId: actor?.userId,
  });

  return NextResponse.json(payload);
}
