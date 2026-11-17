import { beforeEach, describe, expect, it, vi } from "vitest";

const getSessionActor = vi.fn();
const listUserLikedSetIds = vi.fn();
const setUserSetLiked = vi.fn();

vi.mock("@/lib/auth/session", () => ({ getSessionActor }));
vi.mock("@/lib/archive/set-likes.server", () => ({ listUserLikedSetIds, setUserSetLiked }));

const SET = "4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99";
const put = (body: unknown, contentType = "application/json") =>
  new Request("http://localhost/api/archive/set-likes", {
    body: typeof body === "string" ? body : JSON.stringify(body),
    headers: { "content-type": contentType },
    method: "PUT",
  });

describe("/api/archive/set-likes (N10)", () => {
  beforeEach(() => {
    getSessionActor.mockReset();
    listUserLikedSetIds.mockReset();
    setUserSetLiked.mockReset();
  });

  it("requires a signed-in session to read or write", async () => {
    getSessionActor.mockResolvedValue(null);
    const { GET, PUT } = await import("./route");
    expect((await GET(new Request("http://localhost/api/archive/set-likes"))).status).toBe(401);
    expect((await PUT(put({ liked: true, setId: SET }))).status).toBe(401);
    expect(listUserLikedSetIds).not.toHaveBeenCalled();
    expect(setUserSetLiked).not.toHaveBeenCalled();
  });

  it("lists all of the viewer's likes, or only the requested sets", async () => {
    getSessionActor.mockResolvedValue({ userId: "user-1" });
    listUserLikedSetIds.mockResolvedValue([SET]);
    const { GET } = await import("./route");

    const all = await GET(new Request("http://localhost/api/archive/set-likes"));
    expect(all.status).toBe(200);
    expect(all.headers.get("cache-control")).toContain("no-store");
    expect(await all.json()).toEqual({ likedSetIds: [SET] });
    expect(listUserLikedSetIds).toHaveBeenLastCalledWith("user-1", undefined);

    await GET(new Request(`http://localhost/api/archive/set-likes?setIds=${SET}`));
    expect(listUserLikedSetIds).toHaveBeenLastCalledWith("user-1", [SET]);
  });

  it("rejects malformed set ids", async () => {
    getSessionActor.mockResolvedValue({ userId: "user-1" });
    const { GET } = await import("./route");
    expect((await GET(new Request("http://localhost/api/archive/set-likes?setIds=nope"))).status).toBe(400);
  });

  it("likes and unlikes a readable set", async () => {
    getSessionActor.mockResolvedValue({ userId: "user-1" });
    setUserSetLiked.mockImplementation(async (_user: string, _set: string, liked: boolean) => liked);
    const { PUT } = await import("./route");

    const liked = await PUT(put({ liked: true, setId: SET }));
    expect(await liked.json()).toEqual({ liked: true, setId: SET });
    const unliked = await PUT(put({ liked: false, setId: SET }));
    expect(await unliked.json()).toEqual({ liked: false, setId: SET });
    expect(setUserSetLiked).toHaveBeenCalledWith("user-1", SET, false);
  });

  it("does not reveal sets the viewer can't read", async () => {
    getSessionActor.mockResolvedValue({ userId: "outsider" });
    setUserSetLiked.mockResolvedValue(null);
    const { PUT } = await import("./route");
    const response = await PUT(put({ liked: true, setId: SET }));
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "Set not found" });
  });

  it("accepts JSON bodies only", async () => {
    getSessionActor.mockResolvedValue({ userId: "user-1" });
    const { PUT } = await import("./route");
    expect((await PUT(put("liked=true", "application/x-www-form-urlencoded"))).status).toBe(415);
    expect((await PUT(put({ liked: "yes", setId: SET }))).status).toBe(400);
    expect(setUserSetLiked).not.toHaveBeenCalled();
  });
});
