import { NextResponse } from "next/server";
import { ZodError, z } from "zod";

import { listUserLikedSetIds, setUserSetLiked } from "@/lib/archive/set-likes.server";
import { getSessionActor } from "@/lib/auth/session";
import { isJsonRequest, readRequestBody } from "@/lib/http/request-body";

// Likes belong to a signed-in browser session only (no API tokens), so a
// private collection's likes never leave its members' own sessions.
export const dynamic = "force-dynamic";

const uuidSchema = z.string().uuid();
const setLikedSchema = z.object({ liked: z.boolean(), setId: uuidSchema });

const noStore = { "cache-control": "private, no-store" };

const parseSetIds = (request: Request) => {
  const { searchParams } = new URL(request.url);
  const raw = [
    ...searchParams.getAll("setId"),
    ...searchParams.getAll("setIds").flatMap((value) => value.split(",")),
  ].map((value) => value.trim()).filter(Boolean);
  return raw.length ? z.array(uuidSchema).max(200).parse(raw) : undefined;
};

export async function GET(request: Request) {
  const actor = await getSessionActor();
  if (!actor) return NextResponse.json({ error: "Authentication required" }, { status: 401, headers: noStore });

  try {
    const likedSetIds = await listUserLikedSetIds(actor.userId, parseSetIds(request));
    return NextResponse.json({ likedSetIds }, { headers: noStore });
  } catch (error) {
    if (error instanceof ZodError) {
      return NextResponse.json({ error: "Invalid set ids" }, { status: 400, headers: noStore });
    }
    throw error;
  }
}

export async function PUT(request: Request) {
  const actor = await getSessionActor();
  if (!actor) return NextResponse.json({ error: "Authentication required" }, { status: 401, headers: noStore });

  // JSON only: a cross-site page can't send a JSON PUT without CORS approval.
  if (!isJsonRequest(request)) {
    return NextResponse.json({ error: "Invalid like payload" }, { status: 415, headers: noStore });
  }

  try {
    const input = setLikedSchema.parse(await readRequestBody(request));
    const liked = await setUserSetLiked(actor.userId, input.setId, input.liked);
    if (liked === null) return NextResponse.json({ error: "Set not found" }, { status: 404, headers: noStore });
    return NextResponse.json({ liked, setId: input.setId }, { headers: noStore });
  } catch (error) {
    if (error instanceof ZodError || error instanceof SyntaxError) {
      return NextResponse.json({ error: "Invalid like payload" }, { status: 400, headers: noStore });
    }
    throw error;
  }
}
