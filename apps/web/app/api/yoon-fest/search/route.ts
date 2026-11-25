import { NextRequest } from "next/server";
import { getYoonActor, YOON_PRIVATE_HEADERS } from "@/lib/yoon-fest/access.server";
import { listYoonSetNames } from "@/lib/yoon-fest/data.server";
import { matchYoonSearch, type YoonSearchPayload } from "@/lib/yoon-fest/search";
export const dynamic = "force-dynamic";
export const revalidate = 0;

// Private companion to /api/archive/search: the public route never sees this
// collection. Anyone who isn't a member gets the same empty 404 as /access.
export async function GET(request: NextRequest) {
  const actor = await getYoonActor();
  if (!actor) return new Response(null, { status: 404, headers: YOON_PRIVATE_HEADERS });
  const query = (request.nextUrl.searchParams.get("q") ?? "").trim().slice(0, 100);
  const results = query.length < 2 ? [] : matchYoonSearch(query, await listYoonSetNames(actor));
  const payload: YoonSearchPayload = { query, results };
  return Response.json(payload, { headers: YOON_PRIVATE_HEADERS });
}
