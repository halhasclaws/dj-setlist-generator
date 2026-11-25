import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { actor } from "@/lib/yoon-fest/fixtures.test-support";

const mocks = vi.hoisted(() => ({ actor: vi.fn(), names: vi.fn() }));
vi.mock("@/lib/yoon-fest/access.server", () => ({
  getYoonActor: mocks.actor, YOON_PRIVATE_HEADERS: { "Cache-Control": "private, no-store, max-age=0, must-revalidate", "X-Robots-Tag": "noindex, nofollow, noarchive" },
}));
vi.mock("@/lib/yoon-fest/data.server", () => ({ listYoonSetNames: mocks.names }));
import { GET } from "./route";

const request = (q: string) => new NextRequest(`https://example.invalid/api/yoon-fest/search?q=${encodeURIComponent(q)}`);

describe("private collection search route", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.names.mockResolvedValue([{ id: "10000000-0000-4000-8000-000000000001", slug: "synthetic-set", title: "Synthetic Set", performer: "Synthetic Performer", imageUrl: null }]);
  });
  it("gives signed-out viewers and non-members an empty private 404 without reading sets", async () => {
    mocks.actor.mockResolvedValue(null);
    const response = await GET(request("yoon"));
    expect(response.status).toBe(404);
    expect(await response.text()).toBe("");
    expect(response.headers.get("Cache-Control")).toContain("no-store");
    expect(mocks.names).not.toHaveBeenCalled();
  });
  it("returns the collection and its sets to a member, never cacheable", async () => {
    mocks.actor.mockResolvedValue(actor());
    const response = await GET(request("Yoon"));
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toContain("private, no-store");
    const body = await response.json();
    expect(body.results.map((result: { href: string }) => result.href)).toEqual(["/collections/yoon-fest", "/collections/yoon-fest/sets/synthetic-set"]);
    expect(mocks.names).toHaveBeenCalledWith(actor());
  });
  it("skips the lookup for one-letter queries", async () => {
    mocks.actor.mockResolvedValue(actor());
    expect((await (await GET(request("y"))).json()).results).toEqual([]);
    expect(mocks.names).not.toHaveBeenCalled();
  });
});
